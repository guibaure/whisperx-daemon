"""WhisperX integration and transcript output formatting.

This module isolates all direct interaction with WhisperX so the watcher layer
does not need to know anything about model loading, alignment, diarisation, or
output-file formatting details.
"""

from __future__ import annotations

import gc
import importlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

from transcript_postprocess import (
    PostprocessError,
)
from transcript_postprocess import (
    build_person_replacement_map_from_fragments as build_person_map_shared,
)
from transcript_postprocess import (
    load_person_ner_pipeline as load_person_ner_pipeline_shared,
)
from transcript_postprocess import (
    load_term_replacement_map as load_term_replacement_map_shared,
)
from transcript_postprocess import (
    replace_named_terms as replace_named_terms_shared,
)
from transcript_postprocess import (
    replace_person_names as replace_person_names_shared,
)
from transcript_postprocess.core import PersonNerPipeline

from .config import TranscriptionConfig
from .filesystem import write_json_payload

# WhisperX exposes dynamic, version-dependent objects without a stable typed
# public API, so the integration boundary remains intentionally narrow here.
WhisperXModule = Any
WhisperXAudio = Any
WhisperXDiarizationPipelineClass = type[Any]


class TranscriptSegment(TypedDict, total=False):
    """Stable segment shape written to repository transcript artefacts."""

    id: object
    start: int | float | str | None
    end: int | float | str | None
    speaker: str
    text: str


class SpeakerEntry(TypedDict):
    """Stable speaker-index entry written to repository transcript artefacts."""

    label: str


class TranscriptPayload(TypedDict):
    """Top-level JSON payload stored for successful transcriptions."""

    source_path: str
    generated_at: str
    status: str
    text: str
    language: str | None
    segments: list[TranscriptSegment]
    speakers: list[SpeakerEntry]


class WhisperXResult(TypedDict, total=False):
    """Subset of WhisperX result fields consumed by the daemon."""

    text: str
    language: str
    segments: list[Mapping[str, object]]


class TranscriptionError(RuntimeError):
    """Raised when a transcription attempt cannot be completed.

    Callers treat this as an operational failure and convert it into a failure
    report rather than crashing the whole watcher loop.
    """


@dataclass(frozen=True)
class TranscriptDocument:
    """Serializable transcript payload written to disk.

    The JSON file written to ``runtime/output`` is derived directly from this
    object, while the plain-text artefact is built from its segment data.
    """

    source_path: str
    generated_at: str
    status: str
    text: str
    language: str | None
    segments: list[TranscriptSegment]
    speakers: list[SpeakerEntry]

    def to_dict(self) -> TranscriptPayload:
        """Return the JSON payload stored in the output directory."""

        return {
            "source_path": self.source_path,
            "generated_at": self.generated_at,
            "status": self.status,
            "text": self.text,
            "language": self.language,
            "segments": self.segments,
            "speakers": self.speakers,
        }


def load_whisperx_module() -> WhisperXModule:
    """Import WhisperX lazily so the package can start without the dependency.

    Delaying the import makes local development and unit tests cheaper because
    importing WhisperX can pull in heavy ML dependencies.
    """

    try:
        return importlib.import_module("whisperx")
    except ModuleNotFoundError as exc:
        raise TranscriptionError(
            "WhisperX is not installed. Install the 'whisperx' package to "
            "enable transcription."
        ) from exc


def load_person_ner_pipeline(model_name: str) -> PersonNerPipeline:
    """Load a token-classification pipeline for person-name detection lazily.

    The import is deferred so ordinary transcription runs do not pay the cost of
    importing or initialising the Hugging Face pipeline unless pseudonymisation
    is explicitly enabled.
    """

    try:
        return load_person_ner_pipeline_shared(model_name)
    except PostprocessError as exc:
        raise TranscriptionError(str(exc)) from exc


class WhisperXModelSession:
    """Loaded WhisperX ASR model reused by batch and streaming workflows."""

    def __init__(
        self,
        config: TranscriptionConfig,
        whisperx_module: WhisperXModule,
    ) -> None:
        """Load the configured WhisperX model once for repeated transcriptions."""

        self._config = config
        self._model = whisperx_module.load_model(
            config.model_name,
            device=config.device,
            compute_type=config.compute_type,
            language=config.language,
        )

    def transcribe(self, audio: WhisperXAudio) -> WhisperXResult:
        """Transcribe an in-memory WhisperX-compatible audio object."""

        return self._model.transcribe(
            audio,
            batch_size=self._config.batch_size,
            language=self._config.language,
        )

    def close(self) -> None:
        """Release the model reference so Python can reclaim model memory."""

        del self._model


class WhisperXTranscriber:
    """Adapter that isolates WhisperX calls from the watcher logic.

    The class is intentionally state-light. It stores configuration and a module
    loader, then performs one transcription at a time through
    :meth:`transcribe_file`.
    """

    def __init__(
        self,
        config: TranscriptionConfig,
        module_loader: Callable[[], WhisperXModule] | None = None,
        person_ner_pipeline_loader: Callable[[str], PersonNerPipeline] | None = None,
    ) -> None:
        """Store transcription configuration and an optional custom loader."""

        self._config = config
        self._module_loader = module_loader or load_whisperx_module
        self._person_ner_pipeline_loader = (
            person_ner_pipeline_loader or load_person_ner_pipeline
        )

    def transcribe_file(
        self,
        source_path: Path,
        logical_source_path: Path | None = None,
    ) -> TranscriptDocument:
        """Run WhisperX for a single audio file and normalise the JSON payload.

        The method performs the full WhisperX pipeline used by this project:
        audio loading, transcription, timestamp alignment, and optional speaker
        diarisation.
        """

        whisperx_module = self._module_loader()
        try:
            audio = whisperx_module.load_audio(str(source_path))
            result = self.transcribe_loaded_audio(whisperx_module, audio)
            result = self._align_transcript(whisperx_module, audio, result)
            if self._config.diarize:
                result = self._apply_diarization(whisperx_module, audio, result)
        except Exception as exc:  # pragma: no cover - exercised via test doubles
            raise TranscriptionError(f"WhisperX transcription failed: {exc}") from exc
        finally:
            self._release_runtime_memory()

        return self.postprocess_document(
            build_transcript_document(
                source_path=source_path,
                logical_source_path=logical_source_path,
                result=result,
            )
        )

    def postprocess_document(
        self,
        transcript_document: TranscriptDocument,
    ) -> TranscriptDocument:
        """Apply configured transcript post-processing to a document.

        File mode builds the document from a full WhisperX result. Streaming
        mode builds a document from committed window segments. Both paths need
        the same pseudonymisation and proper-noun replacement behaviour, so the
        policy lives in one public method on the transcriber adapter.
        """

        processed_document = transcript_document
        if self._config.pseudonymize_person_names:
            processed_document = pseudonymize_transcript_document(
                processed_document,
                self._person_ner_pipeline_loader(self._config.person_ner_model),
            )
        if self._config.term_replacements_path is not None:
            processed_document = replace_terms_in_transcript_document(
                processed_document,
                load_term_replacement_map(self._config.term_replacements_path),
            )
        return processed_document

    def open_model_session(
        self,
        whisperx_module: WhisperXModule,
    ) -> WhisperXModelSession:
        """Return a reusable WhisperX model session for repeated audio windows."""

        return WhisperXModelSession(self._config, whisperx_module)

    def load_module(self) -> WhisperXModule:
        """Return the configured WhisperX module.

        Streaming mode needs explicit access to the module so it can load the
        ASR model once and reuse it across multiple audio windows.
        """

        return self._module_loader()

    def transcribe_loaded_audio(
        self,
        whisperx_module: WhisperXModule,
        audio: WhisperXAudio,
        model_session: WhisperXModelSession | None = None,
    ) -> WhisperXResult:
        """Transcribe an already-loaded audio object.

        Streaming mode passes a preloaded model session across many windows so
        it does not repeatedly allocate the same WhisperX ASR model.
        """

        session = model_session or self.open_model_session(whisperx_module)
        should_close_session = model_session is None
        try:
            result = session.transcribe(audio)
        except Exception:
            if should_close_session:
                session.close()
            raise
        else:
            if should_close_session:
                session.close()
                self._release_runtime_memory()
            return result

    def _align_transcript(
        self,
        whisperx_module: WhisperXModule,
        audio: WhisperXAudio,
        result: WhisperXResult,
    ) -> WhisperXResult:
        """Refine segment timings with WhisperX alignment when a language is known.

        WhisperX alignment needs a language code. If no language is available
        from either configuration or model output, the raw transcription result
        is returned unchanged.
        """

        language_code = result.get("language") or self._config.language
        if not isinstance(language_code, str) or not language_code:
            return result

        model_a, metadata = whisperx_module.load_align_model(
            language_code=language_code,
            device=self._config.device,
        )
        try:
            return whisperx_module.align(
                result["segments"],
                model_a,
                metadata,
                audio,
                self._config.device,
                return_char_alignments=False,
            )
        finally:
            del model_a
            self._release_runtime_memory()

    def align_transcript(
        self,
        whisperx_module: WhisperXModule,
        audio: WhisperXAudio,
        result: WhisperXResult,
    ) -> WhisperXResult:
        """Public wrapper for alignment used by streaming orchestration."""

        return self._align_transcript(whisperx_module, audio, result)

    def _apply_diarization(
        self,
        whisperx_module: WhisperXModule,
        audio: WhisperXAudio,
        result: WhisperXResult,
    ) -> WhisperXResult:
        """Attach speaker labels using the WhisperX diarisation pipeline.

        Diarisation is explicitly opt-in because it requires additional models
        and a Hugging Face token in most environments.
        """

        if not self._config.hf_token:
            raise TranscriptionError(
                "Speaker diarisation requires a Hugging Face access token. "
                "Pass --hf-token or set HF_TOKEN."
            )

        diarization_pipeline_class = self._load_diarization_pipeline_class(
            whisperx_module
        )
        diarize_pipeline = self._build_diarization_pipeline(diarization_pipeline_class)
        try:
            diarize_segments = diarize_pipeline(
                audio,
                min_speakers=self._config.min_speakers,
                max_speakers=self._config.max_speakers,
            )
            return whisperx_module.assign_word_speakers(diarize_segments, result)
        finally:
            del diarize_pipeline
            self._release_runtime_memory()

    def _load_diarization_pipeline_class(
        self,
        whisperx_module: WhisperXModule,
    ) -> WhisperXDiarizationPipelineClass:
        """Support both legacy and current WhisperX diarisation import layouts.

        WhisperX has exposed the diarisation pipeline in different places across
        versions. This helper keeps the rest of the integration version-tolerant.
        """

        pipeline_class = getattr(whisperx_module, "DiarizationPipeline", None)
        if pipeline_class is not None:
            return pipeline_class

        diarize_module = importlib.import_module("whisperx.diarize")
        return diarize_module.DiarizationPipeline

    def _build_diarization_pipeline(
        self,
        pipeline_class: WhisperXDiarizationPipelineClass,
    ) -> Any:
        """Instantiate the diarisation pipeline across WhisperX API variants.

        Some versions expect ``use_auth_token`` while others accept ``token``.
        Trying the newer signature first keeps the logic straightforward.
        """

        try:
            return pipeline_class(
                use_auth_token=self._config.hf_token,
                device=self._config.device,
            )
        except TypeError:
            return pipeline_class(
                token=self._config.hf_token,
                device=self._config.device,
            )

    def _release_runtime_memory(self) -> None:
        """Release transient Python and CUDA allocations between files and stages.

        WhisperX and pyannote build several GPU-resident models during one
        transcription. Explicit cleanup reduces allocator pressure when the
        daemon processes multiple files sequentially on the same GPU.
        """

        gc.collect()
        if not self._config.device.startswith("cuda"):
            return

        try:
            torch_module = importlib.import_module("torch")
        except ModuleNotFoundError:
            return

        cuda_module = getattr(torch_module, "cuda", None)
        if cuda_module is None or not cuda_module.is_available():
            return

        cuda_module.empty_cache()
        ipc_collect = getattr(cuda_module, "ipc_collect", None)
        if callable(ipc_collect):
            ipc_collect()


def build_transcript_document(
    source_path: Path,
    result: WhisperXResult,
    logical_source_path: Path | None = None,
) -> TranscriptDocument:
    """Convert the WhisperX result into the repository's output schema.

    The function normalises segment shape and extracts a compact speaker index so
    the generated JSON stays stable even if WhisperX returns richer data.
    """

    segments = [normalise_segment(segment) for segment in result.get("segments", [])]
    speakers = build_speaker_index(segments)
    resolved_source_path = logical_source_path or source_path
    return TranscriptDocument(
        source_path=str(resolved_source_path),
        generated_at=datetime.now(UTC).isoformat(),
        status="completed",
        text=str(result.get("text", "")).strip(),
        language=result.get("language"),
        segments=segments,
        speakers=speakers,
    )


def normalise_segment(segment: Mapping[str, object]) -> TranscriptSegment:
    """Keep the segment schema compact, explicit, and JSON-friendly.

    Only the fields currently consumed by this project are preserved in the
    generated JSON and text output.
    """

    speaker_label = segment.get("speaker")
    normalised_segment: TranscriptSegment = {
        "id": segment.get("id"),
        "text": str(segment.get("text", "")),
    }
    start_value = segment.get("start")
    if isinstance(start_value, int | float | str) or start_value is None:
        normalised_segment["start"] = start_value
    end_value = segment.get("end")
    if isinstance(end_value, int | float | str) or end_value is None:
        normalised_segment["end"] = end_value
    if isinstance(speaker_label, str):
        normalised_segment["speaker"] = speaker_label
    return normalised_segment


def pseudonymize_transcript_document(
    document: TranscriptDocument,
    person_ner_pipeline: PersonNerPipeline,
) -> TranscriptDocument:
    """Replace detected person names with stable pseudonyms in transcript text.

    The same detected name is mapped to the same pseudonym throughout the
    document so the transcript remains coherent for readers.
    """

    replacement_map = build_person_map_shared(
        iter_person_detection_fragments(document),
        person_ner_pipeline,
    )
    if not replacement_map:
        return document

    pseudonymized_segments = [
        pseudonymize_segment_text(segment, replacement_map)
        for segment in document.segments
    ]
    return TranscriptDocument(
        source_path=document.source_path,
        generated_at=document.generated_at,
        status=document.status,
        text=replace_person_names_shared(document.text, replacement_map),
        language=document.language,
        segments=pseudonymized_segments,
        speakers=document.speakers,
    )


def replace_terms_in_transcript_document(
    document: TranscriptDocument,
    replacement_map: dict[str, str],
) -> TranscriptDocument:
    """Apply configured proper-noun replacements to transcript text fields."""

    if not replacement_map:
        return document

    updated_segments = [
        replace_terms_in_segment(segment, replacement_map)
        for segment in document.segments
    ]
    return TranscriptDocument(
        source_path=document.source_path,
        generated_at=document.generated_at,
        status=document.status,
        text=replace_named_terms_shared(document.text, replacement_map),
        language=document.language,
        segments=updated_segments,
        speakers=document.speakers,
    )


def replace_terms_in_segment(
    segment: TranscriptSegment,
    replacement_map: dict[str, str],
) -> TranscriptSegment:
    """Return a segment copy whose text field uses configured term replacements."""

    updated_segment = normalise_segment(segment)
    updated_segment["text"] = replace_named_terms_shared(
        str(segment.get("text", "")),
        replacement_map,
    )
    return updated_segment


def load_term_replacement_map(replacements_path: Path) -> dict[str, str]:
    """Load configured proper-noun replacements through the shared package."""

    try:
        return load_term_replacement_map_shared(replacements_path)
    except PostprocessError as exc:
        raise TranscriptionError(str(exc)) from exc


def iter_person_detection_fragments(document: TranscriptDocument) -> list[str]:
    """Return the text fragments that should be scanned for person entities.

    Running token classification over an entire transcript can cause later
    names to disappear once the model exceeds its practical context window.
    Segment texts are therefore the primary detection source. The top-level
    transcript text is used only when no segment text is available.
    """

    segment_fragments = [
        str(segment.get("text", "")).strip()
        for segment in document.segments
        if str(segment.get("text", "")).strip()
    ]
    if segment_fragments:
        return segment_fragments
    if document.text.strip():
        return [document.text]
    return []


def pseudonymize_segment_text(
    segment: TranscriptSegment,
    replacement_map: dict[str, str],
) -> TranscriptSegment:
    """Return a segment copy whose text field uses pseudonymised names."""

    updated_segment = normalise_segment(segment)
    updated_segment["text"] = replace_person_names_shared(
        str(segment.get("text", "")),
        replacement_map,
    )
    return updated_segment


def build_speaker_index(segments: list[TranscriptSegment]) -> list[SpeakerEntry]:
    """Summarise which speakers were observed in the transcript.

    The index is intentionally small: one label per discovered speaker, in first
    appearance order.
    """

    seen_speakers: set[str] = set()
    speakers: list[SpeakerEntry] = []
    for segment in segments:
        speaker_label = segment.get("speaker")
        if not isinstance(speaker_label, str) or speaker_label in seen_speakers:
            continue
        seen_speakers.add(speaker_label)
        speakers.append({"label": speaker_label})
    return speakers


def write_transcript_output(
    document: TranscriptDocument,
    output_dir: Path,
    output_stem: str | None = None,
) -> Path:
    """Write the transcript JSON into the output directory.

    Returns:
        The path to the generated JSON artefact. The watcher stores this path in
        the SQLite job table as the canonical success output.
    """

    output_path = output_dir / f"{output_stem or Path(document.source_path).stem}.json"
    write_json_payload(output_path, document.to_dict())
    return output_path


def write_text_output(
    document: TranscriptDocument,
    output_dir: Path,
    include_time_ranges: bool = True,
    include_speaker_labels: bool = True,
    output_stem: str | None = None,
) -> Path:
    """Write the plain-text transcript into the output directory.

    The plain-text artefact is intended for humans, so it uses one line per
    segment with timing and speaker metadata.
    """

    output_path = output_dir / f"{output_stem or Path(document.source_path).stem}.txt"
    output_path.write_text(
        build_plain_text_transcript(
            document,
            include_time_ranges=include_time_ranges,
            include_speaker_labels=include_speaker_labels,
        ),
        encoding="utf-8",
    )
    return output_path


def build_plain_text_transcript(
    document: TranscriptDocument,
    include_time_ranges: bool = True,
    include_speaker_labels: bool = True,
) -> str:
    """Render one plain-text line per segment with timing and speaker metadata.

    Segment-derived output is preferred because some WhisperX flows return empty
    top-level transcript text even when per-segment text is populated.
    """

    formatted_segments = [
        format_plain_text_segment(
            segment,
            include_time_ranges=include_time_ranges,
            include_speaker_labels=include_speaker_labels,
        )
        for segment in document.segments
        if str(segment.get("text", "")).strip()
    ]
    if formatted_segments:
        return "\n".join(formatted_segments)
    return document.text.strip()


def format_plain_text_segment(
    segment: TranscriptSegment,
    include_time_ranges: bool = True,
    include_speaker_labels: bool = True,
) -> str:
    """Format a segment for the plain-text transcript output."""

    speaker = str(segment.get("speaker") or "UNKNOWN")
    text = str(segment.get("text", "")).strip()
    speaker_prefix = f"{speaker}:" if include_speaker_labels else "-"
    if not include_time_ranges:
        return f"{speaker_prefix} {text}"
    start = format_timestamp(segment.get("start"))
    end = format_timestamp(segment.get("end"))
    return f"[{start}:{end}] {speaker_prefix} {text}"


def format_timestamp(value: Any) -> str:
    """Render segment timestamps consistently for plain-text output.

    Numeric values are normalised to three decimal places because WhisperX
    segment times are typically floating-point seconds.
    """

    if isinstance(value, int | float):
        return f"{value:.3f}"
    return str(value)


def write_transcript_outputs(
    document: TranscriptDocument,
    output_dir: Path,
    include_time_ranges: bool = True,
    include_speaker_labels: bool = True,
    output_stem: str | None = None,
) -> dict[str, Path]:
    """Write all transcript artefacts and return their paths.

    Returns:
        Mapping of logical output kinds to generated filesystem paths.
    """

    return {
        "json": write_transcript_output(document, output_dir, output_stem=output_stem),
        "txt": write_text_output(
            document,
            output_dir,
            include_time_ranges=include_time_ranges,
            include_speaker_labels=include_speaker_labels,
            output_stem=output_stem,
        ),
    }


def write_failure_report(
    source_path: Path,
    failed_dir: Path,
    error_message: str,
    logical_source_path: Path | None = None,
) -> Path:
    """Write a structured failure report for operators and tests.

    Failure reports are JSON so operators can inspect them manually while also
    allowing future automation to parse them reliably.
    """

    failure_path = failed_dir / f"{source_path.stem}.error.json"
    write_json_payload(
        failure_path,
        {
            "source_path": str(logical_source_path or source_path),
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "failed",
            "error": error_message,
        },
    )
    return failure_path
