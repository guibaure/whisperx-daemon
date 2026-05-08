"""Streaming audio ingestion and transcription orchestration.

The streaming path is intentionally separate from the file watcher. File mode
continues to manage stable files, while stream mode consumes raw PCM bytes,
splits them into deterministic overlapping windows, and lets higher layers
transcribe those windows incrementally.
"""

from __future__ import annotations

import importlib
import json
import logging
import wave
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, Protocol

from .config import RuntimeLayout, StreamingConfig, TranscriptionConfig
from .filesystem import move_runtime_file
from .pipeline import (
    TranscriptDocument,
    TranscriptionError,
    WhisperXModelSession,
    WhisperXTranscriber,
    build_speaker_index,
    normalise_segment,
    write_failure_report,
    write_transcript_outputs,
)


class StreamingError(RuntimeError):
    """Raised when stream ingestion or stream processing cannot continue."""


@dataclass(frozen=True)
class AudioWindow:
    """A timestamped PCM window emitted by the stream buffer."""

    pcm_bytes: bytes
    start_sample: int
    sample_rate: int
    channels: int
    sample_width_bytes: int
    is_final: bool = False

    @property
    def sample_count(self) -> int:
        """Return the number of single-channel samples in this window."""

        frame_width = self.channels * self.sample_width_bytes
        return len(self.pcm_bytes) // frame_width

    @property
    def start_seconds(self) -> float:
        """Return the absolute stream start time for this window."""

        return self.start_sample / self.sample_rate

    @property
    def duration_seconds(self) -> float:
        """Return the duration represented by this window."""

        return self.sample_count / self.sample_rate

    @property
    def end_seconds(self) -> float:
        """Return the absolute stream end time for this window."""

        return self.start_seconds + self.duration_seconds


def validate_streaming_config(config: StreamingConfig) -> None:
    """Fail fast for unsupported or internally inconsistent stream settings."""

    if config.sample_rate <= 0:
        raise StreamingError("Streaming sample rate must be positive.")
    if config.channels != 1:
        raise StreamingError("Streaming mode currently supports mono PCM only.")
    if config.sample_width_bytes != 2:
        raise StreamingError(
            "Streaming mode currently supports signed 16-bit PCM only."
        )
    if config.window_seconds <= 0:
        raise StreamingError("Streaming window length must be positive.")
    if config.step_seconds <= 0:
        raise StreamingError("Streaming step length must be positive.")
    if config.step_seconds > config.window_seconds:
        raise StreamingError("Streaming step length cannot exceed window length.")
    if config.commit_overlap_seconds < 0:
        raise StreamingError("Streaming commit overlap cannot be negative.")
    if config.commit_overlap_seconds >= config.window_seconds:
        raise StreamingError(
            "Streaming commit overlap must be shorter than the window."
        )
    if not config.stream_id.strip():
        raise StreamingError("Streaming session id cannot be empty.")


def samples_for_seconds(seconds: float, sample_rate: int) -> int:
    """Convert seconds to a deterministic whole-sample count."""

    sample_count = round(seconds * sample_rate)
    if sample_count <= 0:
        raise StreamingError(
            "Streaming time values must resolve to at least one sample."
        )
    return sample_count


class PcmStreamReader:
    """Read frame-aligned raw PCM chunks from a binary input stream."""

    def __init__(
        self,
        stream: BinaryIO,
        config: StreamingConfig,
        read_seconds: float = 1.0,
    ) -> None:
        validate_streaming_config(config)
        self._stream = stream
        self._config = config
        self._frame_width = config.channels * config.sample_width_bytes
        self._read_size = (
            samples_for_seconds(read_seconds, config.sample_rate) * self._frame_width
        )

    def iter_chunks(self) -> Iterator[bytes]:
        """Yield frame-aligned chunks as the stream produces bytes."""

        while chunk := self._stream.read(self._read_size):
            if len(chunk) % self._frame_width != 0:
                raise StreamingError("PCM input ended with a partial audio frame.")
            yield chunk


class AudioWindowBuffer:
    """Convert incoming PCM chunks into overlapping transcription windows."""

    def __init__(self, config: StreamingConfig) -> None:
        validate_streaming_config(config)
        self._config = config
        self._frame_width = config.channels * config.sample_width_bytes
        self._window_samples = samples_for_seconds(
            config.window_seconds,
            config.sample_rate,
        )
        self._step_samples = samples_for_seconds(
            config.step_seconds,
            config.sample_rate,
        )
        self._buffer = bytearray()
        self._buffer_start_sample = 0
        self._next_window_start_sample = 0

    def append(self, pcm_chunk: bytes) -> list[AudioWindow]:
        """Append PCM bytes and return all complete windows now available."""

        if len(pcm_chunk) % self._frame_width != 0:
            raise StreamingError("PCM chunk contains a partial audio frame.")
        self._buffer.extend(pcm_chunk)
        return self._emit_available_windows(is_final=False)

    def flush(self) -> list[AudioWindow]:
        """Return the final trailing window, if any samples remain."""

        windows = self._emit_available_windows(is_final=False)
        buffer_end_sample = self._buffer_end_sample
        if self._next_window_start_sample < buffer_end_sample:
            windows.append(
                self._build_window(
                    start_sample=self._next_window_start_sample,
                    end_sample=buffer_end_sample,
                    is_final=True,
                )
            )
            self._next_window_start_sample = buffer_end_sample
        self._discard_before(self._next_window_start_sample)
        return windows

    @property
    def _buffer_sample_count(self) -> int:
        return len(self._buffer) // self._frame_width

    @property
    def _buffer_end_sample(self) -> int:
        return self._buffer_start_sample + self._buffer_sample_count

    def _emit_available_windows(self, is_final: bool) -> list[AudioWindow]:
        windows: list[AudioWindow] = []
        while self._next_window_start_sample + self._window_samples <= (
            self._buffer_end_sample
        ):
            window_start = self._next_window_start_sample
            window_end = window_start + self._window_samples
            windows.append(
                self._build_window(
                    start_sample=window_start,
                    end_sample=window_end,
                    is_final=is_final,
                )
            )
            self._next_window_start_sample += self._step_samples
        self._discard_before(self._next_window_start_sample)
        return windows

    def _build_window(
        self,
        start_sample: int,
        end_sample: int,
        is_final: bool,
    ) -> AudioWindow:
        start_offset = (start_sample - self._buffer_start_sample) * self._frame_width
        end_offset = (end_sample - self._buffer_start_sample) * self._frame_width
        return AudioWindow(
            pcm_bytes=bytes(self._buffer[start_offset:end_offset]),
            start_sample=start_sample,
            sample_rate=self._config.sample_rate,
            channels=self._config.channels,
            sample_width_bytes=self._config.sample_width_bytes,
            is_final=is_final,
        )

    def _discard_before(self, sample_index: int) -> None:
        if sample_index <= self._buffer_start_sample:
            return
        discard_samples = min(
            sample_index - self._buffer_start_sample,
            self._buffer_sample_count,
        )
        discard_bytes = discard_samples * self._frame_width
        del self._buffer[:discard_bytes]
        self._buffer_start_sample += discard_samples


class PcmWaveRecorder:
    """Persist a raw PCM stream as WAV for final processing and auditability."""

    def __init__(self, output_path: Path, config: StreamingConfig) -> None:
        validate_streaming_config(config)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.path = output_path
        self._handle = wave.open(str(output_path), "wb")
        self._handle.setnchannels(config.channels)
        self._handle.setsampwidth(config.sample_width_bytes)
        self._handle.setframerate(config.sample_rate)

    def write(self, pcm_chunk: bytes) -> None:
        """Append raw PCM bytes to the recording."""

        self._handle.writeframes(pcm_chunk)

    def close(self) -> None:
        """Close the underlying WAV file."""

        self._handle.close()


@dataclass(frozen=True)
class StreamingRunResult:
    """Filesystem artefacts produced by one completed streaming session."""

    stream_id: str
    event_path: Path
    output_paths: dict[str, Path]
    archived_recording_path: Path | None


class WindowTranscriber(Protocol):
    """Context-managed object able to transcribe PCM windows."""

    def __enter__(self) -> WindowTranscriber:
        """Start the reusable window transcription resources."""
        ...  # pragma: no cover

    def __exit__(self, *_exc_info: object) -> None:
        """Release reusable window transcription resources."""
        ...  # pragma: no cover

    def transcribe_window(self, window: AudioWindow) -> dict[str, Any]:
        """Return the WhisperX-like result for one audio window."""
        ...  # pragma: no cover


WindowTranscriberFactory = Callable[[WhisperXTranscriber], WindowTranscriber]


def pcm_window_to_float32_audio(window: AudioWindow) -> Any:
    """Convert signed 16-bit PCM bytes into WhisperX-compatible float audio."""

    numpy_module = importlib.import_module("numpy")
    samples = numpy_module.frombuffer(window.pcm_bytes, dtype="<i2")
    return samples.astype("float32") / 32768.0


def offset_segment_timestamps(
    segment: dict[str, Any],
    offset_seconds: float,
) -> dict[str, Any]:
    """Return a segment whose timestamps are relative to the full stream."""

    updated_segment = dict(segment)
    for field_name in ("start", "end"):
        value = updated_segment.get(field_name)
        if isinstance(value, int | float):
            updated_segment[field_name] = value + offset_seconds
    return updated_segment


class SegmentCommitter:
    """Commit only stable, non-duplicated segments from overlapping windows."""

    def __init__(self, config: StreamingConfig) -> None:
        validate_streaming_config(config)
        self._config = config
        self._last_committed_end = 0.0

    def commit_segments(
        self,
        window: AudioWindow,
        result: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return stream-offset segments that are safe to emit."""

        commit_limit = (
            float("inf")
            if window.is_final
            else window.end_seconds - self._config.commit_overlap_seconds
        )
        committed_segments: list[dict[str, Any]] = []
        for raw_segment in result.get("segments", []):
            if not isinstance(raw_segment, dict):
                continue
            offset_segment = offset_segment_timestamps(
                raw_segment,
                window.start_seconds,
            )
            normalised_segment = normalise_segment(offset_segment)
            segment_end = normalised_segment.get("end")
            if not isinstance(segment_end, int | float):
                continue
            if segment_end <= self._last_committed_end:
                continue
            if segment_end > commit_limit:
                continue
            committed_segments.append(normalised_segment)
            self._last_committed_end = float(segment_end)
        return committed_segments


class StreamingTranscriptAccumulator:
    """Collect committed stream segments and build a final transcript document."""

    def __init__(self, stream_id: str) -> None:
        self._stream_id = stream_id
        self._segments: list[dict[str, Any]] = []
        self._language: str | None = None

    def extend(self, segments: list[dict[str, Any]], language: str | None) -> None:
        """Append committed segments and remember the detected language."""

        self._segments.extend(segments)
        if self._language is None and language:
            self._language = language

    @property
    def segments(self) -> list[dict[str, Any]]:
        """Return a copy of committed segments."""

        return list(self._segments)

    def build_document(self) -> TranscriptDocument:
        """Build the final stream transcript document from committed segments."""

        text = " ".join(
            str(segment.get("text", "")).strip()
            for segment in self._segments
            if str(segment.get("text", "")).strip()
        )
        return TranscriptDocument(
            source_path=f"stream:{self._stream_id}",
            generated_at=datetime.now(UTC).isoformat(),
            status="completed",
            text=text,
            language=self._language,
            segments=self.segments,
            speakers=build_speaker_index(self.segments),
        )


def build_stream_event(
    stream_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a JSON-serialisable stream event."""

    return {
        "stream_id": stream_id,
        "event": event_type,
        "generated_at": datetime.now(UTC).isoformat(),
        "payload": payload or {},
    }


class JsonlStreamEventWriter:
    """Append stream events as newline-delimited JSON."""

    def __init__(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.path = output_path
        self._handle = output_path.open("a", encoding="utf-8")

    def write(self, event: dict[str, Any]) -> None:
        """Write one JSON event and flush it for tailing consumers."""

        self._handle.write(json.dumps(event, sort_keys=True) + "\n")
        self._handle.flush()

    def close(self) -> None:
        """Close the event file."""

        self._handle.close()


class StreamingWindowTranscriber:
    """Transcribe audio windows with one reusable WhisperX model session."""

    def __init__(
        self,
        transcriber: WhisperXTranscriber,
        audio_converter: Callable[[AudioWindow], Any] = pcm_window_to_float32_audio,
    ) -> None:
        self._transcriber = transcriber
        self._audio_converter = audio_converter
        self._whisperx_module: Any | None = None
        self._model_session: WhisperXModelSession | None = None

    def __enter__(self) -> StreamingWindowTranscriber:
        self._whisperx_module = self._transcriber.load_module()
        self._model_session = self._transcriber.open_model_session(
            self._whisperx_module
        )
        return self

    def __exit__(self, *_exc_info: object) -> None:
        if self._model_session is not None:
            self._model_session.close()
        self._whisperx_module = None
        self._model_session = None

    def transcribe_window(self, window: AudioWindow) -> dict[str, Any]:
        """Transcribe and align one PCM window."""

        if self._whisperx_module is None or self._model_session is None:
            raise StreamingError("Streaming transcriber has not been started.")
        audio = self._audio_converter(window)
        result = self._transcriber.transcribe_loaded_audio(
            self._whisperx_module,
            audio,
            model_session=self._model_session,
        )
        return self._transcriber.align_transcript(
            self._whisperx_module,
            audio,
            result,
        )


def safe_stream_output_stem(stream_id: str) -> str:
    """Return a filesystem-safe stem for stream artefact filenames."""

    cleaned = "".join(
        character if character.isalnum() or character in {"-", "_", "."} else "_"
        for character in stream_id.strip()
    ).strip("._")
    return cleaned or "stream"


def _result_language(result: dict[str, Any]) -> str | None:
    language = result.get("language")
    if isinstance(language, str) and language:
        return language
    return None


class StreamingSessionRunner:
    """Orchestrate one raw PCM stream into live events and final artefacts."""

    def __init__(
        self,
        layout: RuntimeLayout,
        transcription_config: TranscriptionConfig,
        streaming_config: StreamingConfig,
        logger: logging.Logger,
        transcriber: WhisperXTranscriber | None = None,
        window_transcriber_factory: WindowTranscriberFactory | None = None,
    ) -> None:
        validate_streaming_config(streaming_config)
        self._layout = layout
        self._transcription_config = transcription_config
        self._streaming_config = streaming_config
        self._logger = logger
        self._transcriber = transcriber or WhisperXTranscriber(transcription_config)
        self._window_transcriber_factory = window_transcriber_factory or (
            lambda transcriber: StreamingWindowTranscriber(transcriber)
        )
        self._output_stem = safe_stream_output_stem(streaming_config.stream_id)

    def run(self, input_stream: BinaryIO) -> StreamingRunResult:
        """Consume the stream and write live and final transcription artefacts."""

        if (
            self._transcription_config.diarize
            and not self._streaming_config.save_recording
        ):
            raise StreamingError(
                "Stream diarisation requires stream recording to be enabled."
            )

        event_writer = JsonlStreamEventWriter(self._event_path)
        recorder: PcmWaveRecorder | None = None
        try:
            recorder = self._build_recorder()
            event_writer.write(
                build_stream_event(
                    self._streaming_config.stream_id,
                    "stream_started",
                    {
                        "sample_rate": self._streaming_config.sample_rate,
                        "channels": self._streaming_config.channels,
                        "sample_width_bytes": (
                            self._streaming_config.sample_width_bytes
                        ),
                    },
                )
            )
            result = self._run_streaming_transcription(
                input_stream,
                event_writer,
                recorder,
            )
            event_writer.write(
                build_stream_event(
                    self._streaming_config.stream_id,
                    "stream_completed",
                    {
                        "json_path": str(result.output_paths["json"]),
                        "txt_path": str(result.output_paths["txt"]),
                        "event_path": str(result.event_path),
                        "archived_recording_path": (
                            str(result.archived_recording_path)
                            if result.archived_recording_path is not None
                            else None
                        ),
                    },
                )
            )
            return result
        except (StreamingError, TranscriptionError) as exc:
            self._handle_failure(exc, event_writer, recorder)
            raise
        except Exception as exc:
            wrapped_error = StreamingError(f"Streaming transcription failed: {exc}")
            self._handle_failure(wrapped_error, event_writer, recorder)
            raise wrapped_error from exc
        finally:
            event_writer.close()

    @property
    def _event_path(self) -> Path:
        return self._layout.output_dir / f"{self._output_stem}.events.jsonl"

    @property
    def _recording_path(self) -> Path:
        return self._layout.processing_dir / f"{self._output_stem}.wav"

    def _logical_stream_path(self) -> Path:
        return Path(f"stream:{self._streaming_config.stream_id}")

    def _build_recorder(self) -> PcmWaveRecorder | None:
        if not self._streaming_config.save_recording:
            return None
        return PcmWaveRecorder(self._recording_path, self._streaming_config)

    def _run_streaming_transcription(
        self,
        input_stream: BinaryIO,
        event_writer: JsonlStreamEventWriter,
        recorder: PcmWaveRecorder | None,
    ) -> StreamingRunResult:
        reader = PcmStreamReader(input_stream, self._streaming_config)
        window_buffer = AudioWindowBuffer(self._streaming_config)
        committer = SegmentCommitter(self._streaming_config)
        accumulator = StreamingTranscriptAccumulator(self._streaming_config.stream_id)

        with self._window_transcriber_factory(self._transcriber) as window_transcriber:
            for pcm_chunk in reader.iter_chunks():
                if recorder is not None:
                    recorder.write(pcm_chunk)
                self._process_windows(
                    window_buffer.append(pcm_chunk),
                    window_transcriber,
                    committer,
                    accumulator,
                    event_writer,
                )
            self._process_windows(
                window_buffer.flush(),
                window_transcriber,
                committer,
                accumulator,
                event_writer,
            )

        if recorder is not None:
            recorder.close()
            recorder = None

        final_document = self._build_final_document(accumulator)
        output_paths = write_transcript_outputs(
            final_document,
            self._layout.output_dir,
            include_time_ranges=not self._transcription_config.omit_txt_time_ranges,
            include_speaker_labels=(
                not self._transcription_config.omit_txt_speaker_labels
            ),
            output_stem=self._output_stem,
        )
        archived_recording_path = self._archive_recording_on_success()
        self._logger.info(
            "Transcribed stream: %s. Archived recording at %s",
            self._streaming_config.stream_id,
            archived_recording_path,
        )
        return StreamingRunResult(
            stream_id=self._streaming_config.stream_id,
            event_path=self._event_path,
            output_paths=output_paths,
            archived_recording_path=archived_recording_path,
        )

    def _process_windows(
        self,
        windows: list[AudioWindow],
        window_transcriber: WindowTranscriber,
        committer: SegmentCommitter,
        accumulator: StreamingTranscriptAccumulator,
        event_writer: JsonlStreamEventWriter,
    ) -> None:
        for window in windows:
            result = window_transcriber.transcribe_window(window)
            committed_segments = committer.commit_segments(window, result)
            if not committed_segments:
                continue
            accumulator.extend(committed_segments, _result_language(result))
            for segment in committed_segments:
                event_writer.write(
                    build_stream_event(
                        self._streaming_config.stream_id,
                        "segment_final",
                        {"segment": segment, "language": _result_language(result)},
                    )
                )

    def _build_final_document(
        self,
        accumulator: StreamingTranscriptAccumulator,
    ) -> TranscriptDocument:
        if self._transcription_config.diarize:
            return self._transcriber.transcribe_file(
                self._recording_path,
                logical_source_path=self._logical_stream_path(),
            )
        return self._transcriber.postprocess_document(accumulator.build_document())

    def _archive_recording_on_success(self) -> Path | None:
        if not self._streaming_config.save_recording:
            return None
        return move_runtime_file(
            self._recording_path,
            self._layout.archive_succeeded_dir,
        )

    def _handle_failure(
        self,
        error: Exception,
        event_writer: JsonlStreamEventWriter,
        recorder: PcmWaveRecorder | None,
    ) -> None:
        if recorder is not None:
            recorder.close()
        failure_source_path = (
            self._recording_path
            if self._recording_path.exists()
            else self._layout.processing_dir / f"{self._output_stem}.stream"
        )
        archived_recording_path = self._archive_recording_on_failure()
        failure_path = write_failure_report(
            failure_source_path,
            self._layout.failed_dir,
            str(error),
            logical_source_path=self._logical_stream_path(),
        )
        event_writer.write(
            build_stream_event(
                self._streaming_config.stream_id,
                "stream_failed",
                {
                    "error": str(error),
                    "failure_path": str(failure_path),
                    "archived_recording_path": (
                        str(archived_recording_path)
                        if archived_recording_path is not None
                        else None
                    ),
                },
            )
        )
        self._logger.error(
            "Streaming transcription failed for %s: %s",
            self._streaming_config.stream_id,
            error,
        )

    def _archive_recording_on_failure(self) -> Path | None:
        if not self._streaming_config.save_recording:
            return None
        if not self._recording_path.exists():
            return None
        return move_runtime_file(
            self._recording_path,
            self._layout.archive_failed_dir,
        )
