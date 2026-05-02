"""Integration-oriented unit tests for the watcher scaffold.

The test suite uses lightweight WhisperX doubles so behaviour around runtime
layout creation, idempotency, diarisation wiring, and output formatting can be
validated without downloading heavy ML models during local development.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from transcript_postprocess import postprocess_text
from whisperx_daemon.app import configure_logging, resolve_transcription_config, run
from whisperx_daemon.cli import build_argument_parser
from whisperx_daemon.config import RuntimeLayout, StreamingConfig, TranscriptionConfig
from whisperx_daemon.filesystem import ensure_runtime_directories
from whisperx_daemon.pipeline import (
    TranscriptionError,
    WhisperXTranscriber,
    load_person_ner_pipeline,
)
from whisperx_daemon.standalone import main as standalone_main
from whisperx_daemon.state import JobStore
from whisperx_daemon.watcher import WatcherConfig, WorkspaceWatcher


class _FakeWhisperXModel:
    """Minimal stand-in for a WhisperX model used by unit tests."""

    def transcribe(
        self,
        audio: str,
        batch_size: int,
        language: str | None,
    ) -> dict[str, object]:
        return {
            "text": f"Transcript for {Path(audio).name}",
            "language": language or "en",
            "segments": [
                {
                    "id": 0,
                    "start": 0.0,
                    "end": 1.0,
                    "text": "Hello world",
                }
            ],
        }


class _FakeDiarizationPipeline:
    """Simple diarisation double that returns one speaker segment."""

    def __init__(
        self,
        token: str | None = None,
        device: str = "cpu",
        use_auth_token: str | None = None,
    ) -> None:
        resolved_token = use_auth_token or token
        if resolved_token != "hf-token":
            raise AssertionError(resolved_token)
        if device != "cpu":
            raise AssertionError(device)

    def __call__(
        self,
        audio: str,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
    ) -> list[dict[str, object]]:
        if Path(audio).name != "sample.wav":
            raise AssertionError(audio)
        if min_speakers != 1:
            raise AssertionError(min_speakers)
        if max_speakers != 2:
            raise AssertionError(max_speakers)
        return [{"speaker": "SPEAKER_00", "start": 0.0, "end": 1.0}]


class _FakeWhisperXModule:
    """Small module double that mimics whisperx.load_model."""

    DiarizationPipeline = _FakeDiarizationPipeline

    @staticmethod
    def load_audio(audio_path: str) -> str:
        return audio_path

    @staticmethod
    def load_model(
        model_name: str,
        device: str,
        compute_type: str,
        language: str | None,
    ) -> _FakeWhisperXModel:
        if model_name != "small":
            raise AssertionError(model_name)
        if device != "cpu":
            raise AssertionError(device)
        if compute_type != "int8":
            raise AssertionError(compute_type)
        if language != "en":
            raise AssertionError(language)
        return _FakeWhisperXModel()

    @staticmethod
    def load_align_model(
        language_code: str,
        device: str,
    ) -> tuple[str, dict[str, object]]:
        if language_code != "en":
            raise AssertionError(language_code)
        if device != "cpu":
            raise AssertionError(device)
        return "align-model", {"language": "en"}

    @staticmethod
    def align(
        segments: list[dict[str, object]],
        model_a: str,
        metadata: dict[str, object],
        audio: str,
        device: str,
        return_char_alignments: bool,
    ) -> dict[str, object]:
        if model_a != "align-model":
            raise AssertionError(model_a)
        if metadata != {"language": "en"}:
            raise AssertionError(metadata)
        if Path(audio).name not in {"sample.wav", "missing.wav"}:
            raise AssertionError(audio)
        if device != "cpu":
            raise AssertionError(device)
        if return_char_alignments is not False:
            raise AssertionError(return_char_alignments)
        return {
            "text": "Hello world",
            "language": "en",
            "segments": [
                {
                    "id": 0,
                    "start": 0.1,
                    "end": 1.1,
                    "text": segments[0]["text"],
                    "words": [{"word": "Hello", "start": 0.1, "end": 0.4}],
                }
            ],
        }

    @staticmethod
    def assign_word_speakers(
        diarize_segments: list[dict[str, object]],
        result: dict[str, object],
    ) -> dict[str, object]:
        enriched_segment = dict(result["segments"][0])
        enriched_segment["speaker"] = diarize_segments[0]["speaker"]
        return {
            "text": result["text"],
            "language": result["language"],
            "segments": [enriched_segment],
        }


def _fake_person_ner_pipeline(text: str) -> list[dict[str, object]]:
    """Small NER double that marks two person entities in first-appearance order."""

    entities: list[dict[str, object]] = []
    if "John Smith" in text:
        entities.append({"entity_group": "PER", "word": "John Smith"})
    if "Mary Johnson" in text:
        entities.append({"entity_group": "PER", "word": "Mary Johnson"})
    return entities


def _fake_single_name_ner_pipeline(text: str) -> list[dict[str, object]]:
    """NER double that marks standalone first-name person entities."""

    entities: list[dict[str, object]] = []
    if "John" in text:
        entities.append({"entity_group": "PER", "word": "John"})
    if "Mary" in text:
        entities.append({"entity_group": "PER", "word": "Mary"})
    return entities


def _fake_split_french_name_ner_pipeline(text: str) -> list[dict[str, object]]:
    """NER double that mimics multilingual subword splitting for ``Justine``."""

    entities: list[dict[str, object]] = []
    justine_positions = [match.start() for match in re.finditer("Justine", text)]
    if justine_positions:
        first_justine_start = justine_positions[0]
        first_justine_end = first_justine_start + len("Justine")
        entities.extend(
            [
                {
                    "entity_group": "PER",
                    "word": "Justin",
                    "start": first_justine_start,
                    "end": first_justine_end - 1,
                },
                {
                    "entity_group": "PER",
                    "word": "e",
                    "start": first_justine_end - 1,
                    "end": first_justine_end,
                },
            ]
        )
        for justine_start in justine_positions[1:]:
            entities.append(
                {
                    "entity_group": "PER",
                    "word": "Justine",
                    "start": justine_start,
                    "end": justine_start + len("Justine"),
                }
            )
    if "Jonathan" in text:
        jonathan_start = text.index("Jonathan")
        entities.append(
            {
                "entity_group": "PER",
                "word": "Jonathan",
                "start": jonathan_start,
                "end": jonathan_start + len("Jonathan"),
            }
        )
    return sorted(entities, key=lambda entity: int(entity["start"]))


def _fake_length_sensitive_french_ner_pipeline(text: str) -> list[dict[str, object]]:
    """NER double that fails on long text but succeeds on short segment text."""

    if len(text) > 200:
        return [{"entity_group": "ORG", "word": "Sentinel"}]

    entities: list[dict[str, object]] = []
    if "Justine" in text:
        entities.append({"entity_group": "PER", "word": "Justine"})
    if "Jonathan" in text:
        entities.append({"entity_group": "PER", "word": "Jonathan"})
    return entities


class AppBootstrapTests(unittest.TestCase):
    def test_run_once_creates_runtime_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir) / "runtime"

            with patch(
                "whisperx_daemon.pipeline.load_whisperx_module",
                return_value=_FakeWhisperXModule(),
            ):
                run(
                    runtime_dir=runtime_dir,
                    poll_interval=0.1,
                    stability_window=0.0,
                    run_once=True,
                    transcription_config=TranscriptionConfig(language="en"),
                )

            for name in ("input", "processing", "output", "failed", "logs"):
                self.assertTrue((runtime_dir / name).is_dir(), name)
            self.assertTrue((runtime_dir / "archive").is_dir())
            self.assertTrue((runtime_dir / "archive" / "succeeded").is_dir())
            self.assertTrue((runtime_dir / "archive" / "failed").is_dir())
            self.assertTrue((runtime_dir / "jobs.sqlite3").is_file())
            self.assertTrue((runtime_dir / "logs" / "daemon.log").is_file())

    def test_run_once_uses_runtime_local_term_replacements_file_by_default(
        self,
    ) -> None:
        class _FakeWhisperXModuleWithTerms(_FakeWhisperXModule):
            @staticmethod
            def align(
                segments: list[dict[str, object]],
                model_a: str,
                metadata: dict[str, object],
                audio: str,
                device: str,
                return_char_alignments: bool,
            ) -> dict[str, object]:
                return {
                    "text": "Azure responds.",
                    "language": "en",
                    "segments": [
                        {
                            "id": 0,
                            "start": 0.1,
                            "end": 1.1,
                            "text": "Azure responds.",
                        }
                    ],
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir) / "runtime"
            input_dir = runtime_dir / "input"
            input_dir.mkdir(parents=True)
            source_path = input_dir / "sample.wav"
            source_path.write_bytes(b"audio-bytes")
            stable_timestamp = time.time() - 10
            os.utime(source_path, (stable_timestamp, stable_timestamp))

            (runtime_dir / "term-replacements.json").write_text(
                json.dumps({"Azure": "BlueSky"}),
                encoding="utf-8",
            )

            with patch(
                "whisperx_daemon.pipeline.load_whisperx_module",
                return_value=_FakeWhisperXModuleWithTerms(),
            ):
                run(
                    runtime_dir=runtime_dir,
                    poll_interval=0.1,
                    stability_window=0.0,
                    run_once=True,
                    transcription_config=TranscriptionConfig(language="en"),
                )

            payload = json.loads(
                (runtime_dir / "output" / "sample.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["text"], "BlueSky responds.")


class CliDefaultsTests(unittest.TestCase):
    def test_person_ner_default_model_is_multilingual(self) -> None:
        args = build_argument_parser().parse_args([])
        self.assertEqual(args.person_ner_model, "Davlan/xlm-roberta-base-ner-hrl")
        self.assertIsNone(args.term_replacements_file)


class ConfigResolutionTests(unittest.TestCase):
    def test_runtime_local_term_replacements_file_is_used_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            layout = RuntimeLayout.from_root(Path(temp_dir) / "runtime")
            layout.root.mkdir(parents=True)
            default_path = layout.root / "term-replacements.json"
            default_path.write_text("{}", encoding="utf-8")

            resolved_config = resolve_transcription_config(
                TranscriptionConfig(),
                layout,
            )

        self.assertEqual(resolved_config.term_replacements_path, default_path)

    def test_explicit_term_replacements_path_takes_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            layout = RuntimeLayout.from_root(Path(temp_dir) / "runtime")
            layout.root.mkdir(parents=True)
            (layout.root / "term-replacements.json").write_text("{}", encoding="utf-8")
            explicit_path = layout.root / "custom-replacements.json"

            resolved_config = resolve_transcription_config(
                TranscriptionConfig(term_replacements_path=explicit_path),
                layout,
            )

        self.assertEqual(resolved_config.term_replacements_path, explicit_path)


class StreamingConfigTests(unittest.TestCase):
    def test_streaming_defaults_describe_pcm_stdin_contract(self) -> None:
        config = StreamingConfig()

        self.assertEqual(config.stream_id, "stream")
        self.assertIsNone(config.input_path)
        self.assertEqual(config.sample_rate, 16_000)
        self.assertEqual(config.channels, 1)
        self.assertEqual(config.sample_width_bytes, 2)
        self.assertGreater(config.window_seconds, config.step_seconds)
        self.assertTrue(config.save_recording)


class PersonNerLoaderTests(unittest.TestCase):
    def test_loader_uses_explicit_slow_tokenizer(self) -> None:
        captured_calls: dict[str, object] = {}

        class _FakeAutoTokenizer:
            @staticmethod
            def from_pretrained(model_name: str, use_fast: bool) -> str:
                captured_calls["tokenizer_model_name"] = model_name
                captured_calls["use_fast"] = use_fast
                return "tokenizer"

        class _FakeAutoModelForTokenClassification:
            @staticmethod
            def from_pretrained(model_name: str) -> str:
                captured_calls["model_model_name"] = model_name
                return "model"

        class _FakeTransformersModule:
            AutoTokenizer = _FakeAutoTokenizer
            AutoModelForTokenClassification = _FakeAutoModelForTokenClassification

            @staticmethod
            def pipeline(
                task: str,
                model: str,
                tokenizer: str,
                aggregation_strategy: str,
            ) -> str:
                captured_calls["task"] = task
                captured_calls["pipeline_model"] = model
                captured_calls["pipeline_tokenizer"] = tokenizer
                captured_calls["aggregation_strategy"] = aggregation_strategy
                return "ner-pipeline"

        with patch(
            "transcript_postprocess.core.importlib.import_module",
            return_value=_FakeTransformersModule(),
        ):
            pipeline = load_person_ner_pipeline("example/model")

        self.assertEqual(pipeline, "ner-pipeline")
        self.assertEqual(captured_calls["tokenizer_model_name"], "example/model")
        self.assertFalse(captured_calls["use_fast"])
        self.assertEqual(captured_calls["model_model_name"], "example/model")
        self.assertEqual(captured_calls["task"], "token-classification")
        self.assertEqual(captured_calls["pipeline_model"], "model")
        self.assertEqual(captured_calls["pipeline_tokenizer"], "tokenizer")
        self.assertEqual(captured_calls["aggregation_strategy"], "simple")

    def test_loader_wraps_tokenizer_initialisation_failures(self) -> None:
        class _BrokenAutoTokenizer:
            @staticmethod
            def from_pretrained(model_name: str, use_fast: bool) -> str:
                raise AttributeError("'NoneType' object has no attribute 'endswith'")

        class _FakeTransformersModule:
            AutoTokenizer = _BrokenAutoTokenizer

            class AutoModelForTokenClassification:
                @staticmethod
                def from_pretrained(model_name: str) -> str:
                    raise AssertionError("Model loading should not be reached")

        with patch(
            "transcript_postprocess.core.importlib.import_module",
            return_value=_FakeTransformersModule(),
        ):
            with self.assertRaises(TranscriptionError) as context:
                load_person_ner_pipeline("example/model")

        self.assertIn("sentencepiece", str(context.exception))


class StandalonePostprocessTests(unittest.TestCase):
    def test_postprocess_text_applies_pseudonymization_then_term_replacements(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            replacements_path = Path(temp_dir) / "replacements.json"
            replacements_path.write_text(
                json.dumps({"Azure": "BlueSky"}),
                encoding="utf-8",
            )

            output_text = postprocess_text(
                "John Smith works on Azure.",
                pseudonymize_person_names=True,
                term_replacements_path=replacements_path,
                person_ner_pipeline_loader=lambda model_name: _fake_person_ner_pipeline,
            )

        self.assertEqual(output_text, "Alice Archer works on BlueSky.")

    def test_standalone_cli_reads_and_writes_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.txt"
            output_path = Path(temp_dir) / "output.txt"
            replacements_path = Path(temp_dir) / "replacements.json"
            input_path.write_text("Azure meets Sentinel.", encoding="utf-8")
            replacements_path.write_text(
                json.dumps({"Azure": "BlueSky", "Sentinel": "Northstar"}),
                encoding="utf-8",
            )

            exit_code = standalone_main(
                [
                    "--input-file",
                    str(input_path),
                    "--output-file",
                    str(output_path),
                    "--term-replacements-file",
                    str(replacements_path),
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "BlueSky meets Northstar.",
            )


class RuntimeMemoryReleaseTests(unittest.TestCase):
    def test_release_runtime_memory_empties_cuda_cache(self) -> None:
        class _FakeCudaModule:
            def __init__(self) -> None:
                self.empty_cache_calls = 0
                self.ipc_collect_calls = 0

            @staticmethod
            def is_available() -> bool:
                return True

            def empty_cache(self) -> None:
                self.empty_cache_calls += 1

            def ipc_collect(self) -> None:
                self.ipc_collect_calls += 1

        fake_cuda_module = _FakeCudaModule()

        class _FakeTorchModule:
            cuda = fake_cuda_module

        transcriber = WhisperXTranscriber(
            config=TranscriptionConfig(device="cuda"),
        )

        with patch("whisperx_daemon.pipeline.gc.collect") as mock_gc_collect:
            with patch(
                "whisperx_daemon.pipeline.importlib.import_module",
                return_value=_FakeTorchModule(),
            ):
                transcriber._release_runtime_memory()

        mock_gc_collect.assert_called_once_with()
        self.assertEqual(fake_cuda_module.empty_cache_calls, 1)
        self.assertEqual(fake_cuda_module.ipc_collect_calls, 1)

    def test_transcriber_releases_runtime_memory_between_pipeline_stages(self) -> None:
        class _TrackingTranscriber(WhisperXTranscriber):
            def __init__(self, *args, **kwargs) -> None:
                super().__init__(*args, **kwargs)
                self.release_calls = 0

            def _release_runtime_memory(self) -> None:
                self.release_calls += 1

        transcriber = _TrackingTranscriber(
            config=TranscriptionConfig(
                language="en",
                diarize=True,
                hf_token="hf-token",
                min_speakers=1,
                max_speakers=2,
            ),
            module_loader=lambda: _FakeWhisperXModule(),
        )

        transcriber.transcribe_file(Path("sample.wav"))

        self.assertEqual(transcriber.release_calls, 4)

    def test_transcribe_loaded_audio_can_reuse_model_session(self) -> None:
        class _CountingWhisperXModule(_FakeWhisperXModule):
            def __init__(self) -> None:
                self.load_model_calls = 0

            def load_model(
                self,
                model_name: str,
                device: str,
                compute_type: str,
                language: str | None,
            ) -> _FakeWhisperXModel:
                self.load_model_calls += 1
                return _FakeWhisperXModule.load_model(
                    model_name,
                    device,
                    compute_type,
                    language,
                )

        module = _CountingWhisperXModule()
        transcriber = WhisperXTranscriber(config=TranscriptionConfig(language="en"))
        session = transcriber.open_model_session(module)
        try:
            first_result = transcriber.transcribe_loaded_audio(
                module,
                "sample.wav",
                model_session=session,
            )
            second_result = transcriber.transcribe_loaded_audio(
                module,
                "sample.wav",
                model_session=session,
            )
        finally:
            session.close()

        self.assertEqual(module.load_model_calls, 1)
        self.assertEqual(first_result["text"], "Transcript for sample.wav")
        self.assertEqual(second_result["text"], "Transcript for sample.wav")

    def test_transcriber_releases_runtime_memory_after_failure(self) -> None:
        class _ExplodingWhisperXModel:
            def transcribe(
                self,
                audio: str,
                batch_size: int,
                language: str | None,
            ) -> dict[str, object]:
                raise RuntimeError("CUDA failed with error out of memory")

        class _FailingWhisperXModule(_FakeWhisperXModule):
            @staticmethod
            def load_model(
                model_name: str,
                device: str,
                compute_type: str,
                language: str | None,
            ) -> _ExplodingWhisperXModel:
                return _ExplodingWhisperXModel()

        class _TrackingTranscriber(WhisperXTranscriber):
            def __init__(self, *args, **kwargs) -> None:
                super().__init__(*args, **kwargs)
                self.release_calls = 0

            def _release_runtime_memory(self) -> None:
                self.release_calls += 1

        transcriber = _TrackingTranscriber(
            config=TranscriptionConfig(language="en"),
            module_loader=lambda: _FailingWhisperXModule(),
        )

        with self.assertRaises(TranscriptionError):
            transcriber.transcribe_file(Path("sample.wav"))

        self.assertEqual(transcriber.release_calls, 1)


class IdempotencyTests(unittest.TestCase):
    def test_run_once_registers_same_file_once_when_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir) / "runtime"
            input_dir = runtime_dir / "input"
            input_dir.mkdir(parents=True)
            audio_path = input_dir / "sample.wav"
            audio_path.write_bytes(b"audio-bytes")

            stable_timestamp = time.time() - 10
            os.utime(audio_path, (stable_timestamp, stable_timestamp))

            with patch(
                "whisperx_daemon.pipeline.load_whisperx_module",
                return_value=_FakeWhisperXModule(),
            ):
                run(
                    runtime_dir=runtime_dir,
                    poll_interval=0.1,
                    stability_window=0.0,
                    run_once=True,
                    transcription_config=TranscriptionConfig(language="en"),
                )
            first_output = (runtime_dir / "output" / "sample.json").read_text(
                encoding="utf-8"
            )
            first_text_output = (runtime_dir / "output" / "sample.txt").read_text(
                encoding="utf-8"
            )

            with patch(
                "whisperx_daemon.pipeline.load_whisperx_module",
                return_value=_FakeWhisperXModule(),
            ):
                run(
                    runtime_dir=runtime_dir,
                    poll_interval=0.1,
                    stability_window=0.0,
                    run_once=True,
                    transcription_config=TranscriptionConfig(language="en"),
                )
            second_output = (runtime_dir / "output" / "sample.json").read_text(
                encoding="utf-8"
            )
            second_text_output = (runtime_dir / "output" / "sample.txt").read_text(
                encoding="utf-8"
            )

            self.assertEqual(first_output, second_output)
            self.assertEqual(first_text_output, second_text_output)
            self.assertFalse((runtime_dir / "input" / "sample.wav").exists())
            self.assertFalse((runtime_dir / "processing" / "sample.wav").exists())
            self.assertTrue(
                (runtime_dir / "archive" / "succeeded" / "sample.wav").is_file()
            )

            with closing(sqlite3.connect(runtime_dir / "jobs.sqlite3")) as connection:
                job_count = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[
                    0
                ]
            self.assertEqual(job_count, 1)

    def test_run_once_can_force_reprocess_unchanged_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir) / "runtime"
            input_dir = runtime_dir / "input"
            input_dir.mkdir(parents=True)
            audio_path = input_dir / "sample.wav"
            audio_path.write_bytes(b"audio-bytes")

            stable_timestamp = time.time() - 10
            os.utime(audio_path, (stable_timestamp, stable_timestamp))

            with patch(
                "whisperx_daemon.pipeline.load_whisperx_module",
                return_value=_FakeWhisperXModule(),
            ):
                run(
                    runtime_dir=runtime_dir,
                    poll_interval=0.1,
                    stability_window=0.0,
                    run_once=True,
                    transcription_config=TranscriptionConfig(language="en"),
                )

            archived_audio_path = runtime_dir / "archive" / "succeeded" / "sample.wav"
            self.assertTrue(archived_audio_path.is_file())

            requeued_audio_path = input_dir / "sample.wav"
            requeued_audio_path.write_bytes(archived_audio_path.read_bytes())
            os.utime(requeued_audio_path, (stable_timestamp, stable_timestamp))

            with patch(
                "whisperx_daemon.pipeline.load_whisperx_module",
                return_value=_FakeWhisperXModule(),
            ):
                run(
                    runtime_dir=runtime_dir,
                    poll_interval=0.1,
                    stability_window=0.0,
                    run_once=True,
                    force_reprocess=True,
                    transcription_config=TranscriptionConfig(language="en"),
                )

            self.assertFalse(requeued_audio_path.exists())
            self.assertTrue(archived_audio_path.is_file())
            with closing(sqlite3.connect(runtime_dir / "jobs.sqlite3")) as connection:
                job_count = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[
                    0
                ]
            self.assertEqual(job_count, 1)


class CliFlagTests(unittest.TestCase):
    def test_force_reprocess_flag_defaults_to_false(self) -> None:
        args = build_argument_parser().parse_args([])
        self.assertFalse(args.force_reprocess)

    def test_force_reprocess_flag_can_be_enabled(self) -> None:
        args = build_argument_parser().parse_args(["--force-reprocess"])
        self.assertTrue(args.force_reprocess)

    def test_omit_txt_time_ranges_flag_defaults_to_false(self) -> None:
        args = build_argument_parser().parse_args([])
        self.assertFalse(args.omit_txt_time_ranges)

    def test_omit_txt_time_ranges_flag_can_be_enabled(self) -> None:
        args = build_argument_parser().parse_args(["--omit-txt-time-ranges"])
        self.assertTrue(args.omit_txt_time_ranges)

    def test_omit_txt_speaker_labels_flag_defaults_to_false(self) -> None:
        args = build_argument_parser().parse_args([])
        self.assertFalse(args.omit_txt_speaker_labels)

    def test_omit_txt_speaker_labels_flag_can_be_enabled(self) -> None:
        args = build_argument_parser().parse_args(["--omit-txt-speaker-labels"])
        self.assertTrue(args.omit_txt_speaker_labels)


class PipelineIntegrationTests(unittest.TestCase):
    def test_shared_postprocess_package_can_be_used_directly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            replacements_path = Path(temp_dir) / "term-replacements.json"
            replacements_path.write_text(
                json.dumps(
                    {
                        "Boeing": "Test",
                        "Boeing Defense": "Test Toto",
                        "Boeing Defense and Space": "Tata",
                    }
                ),
                encoding="utf-8",
            )

            processed_text = postprocess_text(
                "John Smith met Boeing Defense and Space.",
                pseudonymize_person_names=True,
                person_ner_pipeline_loader=lambda model_name: _fake_person_ner_pipeline,
                term_replacements_path=replacements_path,
            )

        self.assertEqual(processed_text, "Alice Archer met Tata.")

    def test_transcriber_writes_real_transcript_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir) / "runtime"
            layout = RuntimeLayout.from_root(runtime_dir)
            ensure_runtime_directories(layout)
            source_path = layout.input_dir / "sample.wav"
            source_path.write_bytes(b"audio-bytes")

            stable_timestamp = time.time() - 10
            os.utime(source_path, (stable_timestamp, stable_timestamp))

            watcher = WorkspaceWatcher(
                layout=layout,
                store=JobStore(layout.state_db_path),
                config=WatcherConfig(poll_interval=0.1, stability_window=0.0),
                transcription_config=TranscriptionConfig(language="en"),
                logger=configure_logging(layout.logs_dir),
                transcriber=WhisperXTranscriber(
                    config=TranscriptionConfig(language="en"),
                    module_loader=lambda: _FakeWhisperXModule(),
                ),
            )
            watcher._store.initialise()

            processed_files = watcher.run_once()

            self.assertEqual(processed_files, [source_path])
            payload = json.loads(
                (layout.output_dir / "sample.json").read_text(encoding="utf-8")
            )
            text_output = (layout.output_dir / "sample.txt").read_text(encoding="utf-8")
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["source_path"], str(source_path))
            self.assertEqual(payload["language"], "en")
            self.assertEqual(payload["segments"][0]["start"], 0.1)
            self.assertNotIn("speaker", payload["segments"][0])
            self.assertEqual(payload["speakers"], [])
            self.assertEqual(text_output, "[0.100:1.100] UNKNOWN: Hello world")
            self.assertFalse((layout.processing_dir / "sample.wav").exists())
            self.assertTrue((layout.archive_succeeded_dir / "sample.wav").is_file())

    def test_text_output_falls_back_to_segments_when_top_level_text_is_empty(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir) / "runtime"
            layout = RuntimeLayout.from_root(runtime_dir)
            ensure_runtime_directories(layout)
            source_path = layout.input_dir / "sample.wav"
            source_path.write_bytes(b"audio-bytes")

            class _FakeWhisperXModuleWithEmptyText(_FakeWhisperXModule):
                @staticmethod
                def align(
                    segments: list[dict[str, object]],
                    model_a: str,
                    metadata: dict[str, object],
                    audio: str,
                    device: str,
                    return_char_alignments: bool,
                ) -> dict[str, object]:
                    return {
                        "text": "",
                        "language": "en",
                        "segments": [
                            {
                                "id": 0,
                                "start": 0.1,
                                "end": 1.1,
                                "text": "First line",
                            },
                            {
                                "id": 1,
                                "start": 1.2,
                                "end": 2.0,
                                "text": "Second line",
                            },
                        ],
                    }

            stable_timestamp = time.time() - 10
            os.utime(source_path, (stable_timestamp, stable_timestamp))

            watcher = WorkspaceWatcher(
                layout=layout,
                store=JobStore(layout.state_db_path),
                config=WatcherConfig(poll_interval=0.1, stability_window=0.0),
                transcription_config=TranscriptionConfig(language="en"),
                logger=configure_logging(layout.logs_dir),
                transcriber=WhisperXTranscriber(
                    config=TranscriptionConfig(language="en"),
                    module_loader=lambda: _FakeWhisperXModuleWithEmptyText(),
                ),
            )
            watcher._store.initialise()

            processed_files = watcher.run_once()

            self.assertEqual(processed_files, [source_path])
            text_output = (layout.output_dir / "sample.txt").read_text(encoding="utf-8")
            self.assertEqual(
                text_output,
                "[0.100:1.100] UNKNOWN: First line\n[1.200:2.000] UNKNOWN: Second line",
            )
            self.assertFalse((layout.processing_dir / "sample.wav").exists())
            self.assertTrue((layout.archive_succeeded_dir / "sample.wav").is_file())

    def test_text_output_can_omit_time_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir) / "runtime"
            layout = RuntimeLayout.from_root(runtime_dir)
            ensure_runtime_directories(layout)
            source_path = layout.input_dir / "sample.wav"
            source_path.write_bytes(b"audio-bytes")

            stable_timestamp = time.time() - 10
            os.utime(source_path, (stable_timestamp, stable_timestamp))

            watcher = WorkspaceWatcher(
                layout=layout,
                store=JobStore(layout.state_db_path),
                config=WatcherConfig(poll_interval=0.1, stability_window=0.0),
                transcription_config=TranscriptionConfig(
                    language="en",
                    omit_txt_time_ranges=True,
                ),
                logger=configure_logging(layout.logs_dir),
                transcriber=WhisperXTranscriber(
                    config=TranscriptionConfig(
                        language="en",
                        omit_txt_time_ranges=True,
                    ),
                    module_loader=lambda: _FakeWhisperXModule(),
                ),
            )
            watcher._store.initialise()

            processed_files = watcher.run_once()

            self.assertEqual(processed_files, [source_path])
            text_output = (layout.output_dir / "sample.txt").read_text(encoding="utf-8")
            self.assertEqual(text_output, "UNKNOWN: Hello world")

    def test_text_output_can_omit_speaker_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir) / "runtime"
            layout = RuntimeLayout.from_root(runtime_dir)
            ensure_runtime_directories(layout)
            source_path = layout.input_dir / "sample.wav"
            source_path.write_bytes(b"audio-bytes")

            stable_timestamp = time.time() - 10
            os.utime(source_path, (stable_timestamp, stable_timestamp))

            transcription_config = TranscriptionConfig(
                language="en",
                diarize=True,
                hf_token="hf-token",
                min_speakers=1,
                max_speakers=2,
                omit_txt_time_ranges=True,
                omit_txt_speaker_labels=True,
            )
            watcher = WorkspaceWatcher(
                layout=layout,
                store=JobStore(layout.state_db_path),
                config=WatcherConfig(poll_interval=0.1, stability_window=0.0),
                transcription_config=transcription_config,
                logger=configure_logging(layout.logs_dir),
                transcriber=WhisperXTranscriber(
                    config=transcription_config,
                    module_loader=lambda: _FakeWhisperXModule(),
                ),
            )
            watcher._store.initialise()

            processed_files = watcher.run_once()

            self.assertEqual(processed_files, [source_path])
            payload = json.loads(
                (layout.output_dir / "sample.json").read_text(encoding="utf-8")
            )
            text_output = (layout.output_dir / "sample.txt").read_text(encoding="utf-8")
            self.assertEqual(payload["segments"][0]["speaker"], "SPEAKER_00")
            self.assertEqual(text_output, "- Hello world")

    def test_diarization_attaches_speaker_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir) / "runtime"
            layout = RuntimeLayout.from_root(runtime_dir)
            ensure_runtime_directories(layout)
            source_path = layout.input_dir / "sample.wav"
            source_path.write_bytes(b"audio-bytes")

            stable_timestamp = time.time() - 10
            os.utime(source_path, (stable_timestamp, stable_timestamp))

            store = JobStore(layout.state_db_path)
            store.initialise()
            transcription_config = TranscriptionConfig(
                language="en",
                diarize=True,
                hf_token="hf-token",
                min_speakers=1,
                max_speakers=2,
            )
            watcher = WorkspaceWatcher(
                layout=layout,
                store=store,
                config=WatcherConfig(poll_interval=0.1, stability_window=0.0),
                transcription_config=transcription_config,
                logger=configure_logging(layout.logs_dir),
                transcriber=WhisperXTranscriber(
                    config=transcription_config,
                    module_loader=lambda: _FakeWhisperXModule(),
                ),
            )

            processed_files = watcher.run_once()

            self.assertEqual(processed_files, [source_path])
            payload = json.loads(
                (layout.output_dir / "sample.json").read_text(encoding="utf-8")
            )
            text_output = (layout.output_dir / "sample.txt").read_text(encoding="utf-8")
            self.assertEqual(payload["segments"][0]["speaker"], "SPEAKER_00")
            self.assertEqual(payload["speakers"], [{"label": "SPEAKER_00"}])
            self.assertEqual(text_output, "[0.100:1.100] SPEAKER_00: Hello world")
            self.assertFalse((layout.processing_dir / "sample.wav").exists())
            self.assertTrue((layout.archive_succeeded_dir / "sample.wav").is_file())

    def test_missing_whisperx_writes_failure_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir) / "runtime"
            layout = RuntimeLayout.from_root(runtime_dir)
            ensure_runtime_directories(layout)
            source_path = layout.input_dir / "missing.wav"
            source_path.write_bytes(b"audio-bytes")

            stable_timestamp = time.time() - 10
            os.utime(source_path, (stable_timestamp, stable_timestamp))

            store = JobStore(layout.state_db_path)
            store.initialise()
            watcher = WorkspaceWatcher(
                layout=layout,
                store=store,
                config=WatcherConfig(poll_interval=0.1, stability_window=0.0),
                transcription_config=TranscriptionConfig(),
                logger=configure_logging(layout.logs_dir),
                transcriber=WhisperXTranscriber(
                    config=TranscriptionConfig(),
                    module_loader=lambda: (_ for _ in ()).throw(
                        TranscriptionError("WhisperX is not installed")
                    ),
                ),
            )

            processed_files = watcher.run_once()

            self.assertEqual(processed_files, [source_path])
            failure_payload = json.loads(
                (layout.failed_dir / "missing.error.json").read_text(encoding="utf-8")
            )
            self.assertEqual(failure_payload["status"], "failed")
            self.assertEqual(failure_payload["source_path"], str(source_path))
            self.assertIn("WhisperX is not installed", failure_payload["error"])
            self.assertFalse((layout.processing_dir / "missing.wav").exists())
            self.assertTrue((layout.archive_failed_dir / "missing.wav").is_file())

            job_record = store.fetch_by_source_path(str(source_path))
            self.assertIsNotNone(job_record)
            self.assertEqual(job_record.status, "failed_transcription")

    def test_diarization_requires_hf_token(self) -> None:
        transcriber = WhisperXTranscriber(
            config=TranscriptionConfig(language="en", diarize=True),
            module_loader=lambda: _FakeWhisperXModule(),
        )

        with self.assertRaises(TranscriptionError):
            transcriber.transcribe_file(Path("sample.wav"))

    def test_diarization_supports_submodule_pipeline_import(self) -> None:
        class _FakeWhisperXModuleWithoutTopLevelPipeline:
            load_audio = staticmethod(_FakeWhisperXModule.load_audio)
            load_model = staticmethod(_FakeWhisperXModule.load_model)
            load_align_model = staticmethod(_FakeWhisperXModule.load_align_model)
            align = staticmethod(_FakeWhisperXModule.align)
            assign_word_speakers = staticmethod(
                _FakeWhisperXModule.assign_word_speakers
            )

        class _FakeWhisperXDiarizeModule:
            DiarizationPipeline = _FakeDiarizationPipeline

        transcriber = WhisperXTranscriber(
            config=TranscriptionConfig(
                language="en",
                diarize=True,
                hf_token="hf-token",
                min_speakers=1,
                max_speakers=2,
            ),
            module_loader=lambda: _FakeWhisperXModuleWithoutTopLevelPipeline(),
        )

        from whisperx_daemon import pipeline as pipeline_module

        original_import_module = pipeline_module.importlib.import_module

        def _fake_import_module(module_name: str):
            if module_name == "whisperx.diarize":
                return _FakeWhisperXDiarizeModule()
            return original_import_module(module_name)

        with patch(
            "whisperx_daemon.pipeline.importlib.import_module",
            side_effect=_fake_import_module,
        ):
            transcript = transcriber.transcribe_file(Path("sample.wav"))

        self.assertEqual(transcript.speakers, [{"label": "SPEAKER_00"}])

    def test_pseudonymize_person_names_rewrites_output_text(self) -> None:
        class _FakeWhisperXModuleWithNames(_FakeWhisperXModule):
            @staticmethod
            def align(
                segments: list[dict[str, object]],
                model_a: str,
                metadata: dict[str, object],
                audio: str,
                device: str,
                return_char_alignments: bool,
            ) -> dict[str, object]:
                return {
                    "text": "John Smith met Mary Johnson. John Smith spoke first.",
                    "language": "en",
                    "segments": [
                        {
                            "id": 0,
                            "start": 0.1,
                            "end": 1.1,
                            "text": "John Smith met Mary Johnson.",
                        },
                        {
                            "id": 1,
                            "start": 1.2,
                            "end": 2.2,
                            "text": "John Smith spoke first.",
                        },
                    ],
                }

        transcriber = WhisperXTranscriber(
            config=TranscriptionConfig(
                language="en",
                pseudonymize_person_names=True,
            ),
            module_loader=lambda: _FakeWhisperXModuleWithNames(),
            person_ner_pipeline_loader=lambda model_name: _fake_person_ner_pipeline,
        )

        transcript = transcriber.transcribe_file(Path("sample.wav"))

        self.assertEqual(
            transcript.text,
            "Alice Archer met Benjamin Bennett. Alice Archer spoke first.",
        )
        self.assertEqual(
            transcript.segments[0]["text"],
            "Alice Archer met Benjamin Bennett.",
        )
        self.assertEqual(
            transcript.segments[1]["text"],
            "Alice Archer spoke first.",
        )

    def test_term_replacements_rewrite_document_and_segment_text(self) -> None:
        class _FakeWhisperXModuleWithTerms(_FakeWhisperXModule):
            @staticmethod
            def align(
                segments: list[dict[str, object]],
                model_a: str,
                metadata: dict[str, object],
                audio: str,
                device: str,
                return_char_alignments: bool,
            ) -> dict[str, object]:
                return {
                    "text": "Azure meets Sentinel. Azure responds.",
                    "language": "en",
                    "segments": [
                        {
                            "id": 0,
                            "start": 0.1,
                            "end": 1.1,
                            "text": "Azure meets Sentinel.",
                        },
                        {
                            "id": 1,
                            "start": 1.2,
                            "end": 2.2,
                            "text": "Azure responds.",
                        },
                    ],
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            replacements_path = Path(temp_dir) / "replacements.json"
            replacements_path.write_text(
                json.dumps(
                    {
                        "Azure": "BlueSky",
                        "Sentinel": "Northstar",
                    }
                ),
                encoding="utf-8",
            )

            transcriber = WhisperXTranscriber(
                config=TranscriptionConfig(
                    language="en",
                    term_replacements_path=replacements_path,
                ),
                module_loader=lambda: _FakeWhisperXModuleWithTerms(),
            )

            transcript = transcriber.transcribe_file(Path("sample.wav"))

        self.assertEqual(
            transcript.text,
            "BlueSky meets Northstar. BlueSky responds.",
        )
        self.assertEqual(
            transcript.segments[0]["text"],
            "BlueSky meets Northstar.",
        )
        self.assertEqual(
            transcript.segments[1]["text"],
            "BlueSky responds.",
        )

    def test_term_replacements_prefer_longest_overlapping_match(self) -> None:
        class _FakeWhisperXModuleWithTerms(_FakeWhisperXModule):
            @staticmethod
            def align(
                segments: list[dict[str, object]],
                model_a: str,
                metadata: dict[str, object],
                audio: str,
                device: str,
                return_char_alignments: bool,
            ) -> dict[str, object]:
                return {
                    "text": (
                        "Boeing Defense and Space meets Boeing Defense. Boeing arrives."
                    ),
                    "language": "en",
                    "segments": [
                        {
                            "id": 0,
                            "start": 0.1,
                            "end": 1.1,
                            "text": "Boeing Defense and Space meets Boeing Defense.",
                        },
                        {
                            "id": 1,
                            "start": 1.2,
                            "end": 2.2,
                            "text": "Boeing arrives.",
                        },
                    ],
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            replacements_path = Path(temp_dir) / "replacements.json"
            replacements_path.write_text(
                json.dumps(
                    {
                        "Boeing": "test",
                        "Boeing Defense": "test toto",
                        "Boeing Defense and Space": "tata",
                    }
                ),
                encoding="utf-8",
            )

            transcriber = WhisperXTranscriber(
                config=TranscriptionConfig(
                    language="en",
                    term_replacements_path=replacements_path,
                ),
                module_loader=lambda: _FakeWhisperXModuleWithTerms(),
            )

            transcript = transcriber.transcribe_file(Path("sample.wav"))

        self.assertEqual(
            transcript.text,
            "Tata meets Test toto. Test arrives.",
        )
        self.assertEqual(
            transcript.segments[0]["text"],
            "Tata meets Test toto.",
        )
        self.assertEqual(
            transcript.segments[1]["text"],
            "Test arrives.",
        )

    def test_term_replacements_match_case_insensitively(self) -> None:
        class _FakeWhisperXModuleWithTerms(_FakeWhisperXModule):
            @staticmethod
            def align(
                segments: list[dict[str, object]],
                model_a: str,
                metadata: dict[str, object],
                audio: str,
                device: str,
                return_char_alignments: bool,
            ) -> dict[str, object]:
                return {
                    "text": "boeing meets BOEING defense and Boeing Defense and Space.",
                    "language": "en",
                    "segments": [
                        {
                            "id": 0,
                            "start": 0.1,
                            "end": 1.1,
                            "text": (
                                "boeing meets BOEING defense and Boeing "
                                "Defense and Space."
                            ),
                        }
                    ],
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            replacements_path = Path(temp_dir) / "replacements.json"
            replacements_path.write_text(
                json.dumps(
                    {
                        "Boeing": "test",
                        "Boeing Defense": "test toto",
                        "Boeing Defense and Space": "tata",
                    }
                ),
                encoding="utf-8",
            )

            transcriber = WhisperXTranscriber(
                config=TranscriptionConfig(
                    language="en",
                    term_replacements_path=replacements_path,
                ),
                module_loader=lambda: _FakeWhisperXModuleWithTerms(),
            )

            transcript = transcriber.transcribe_file(Path("sample.wav"))

        self.assertEqual(
            transcript.text,
            "Test meets Test toto and Tata.",
        )
        self.assertEqual(
            transcript.segments[0]["text"],
            "Test meets Test toto and Tata.",
        )

    def test_invalid_term_replacements_file_raises_transcription_error(self) -> None:
        class _FakeWhisperXModuleWithTerms(_FakeWhisperXModule):
            @staticmethod
            def align(
                segments: list[dict[str, object]],
                model_a: str,
                metadata: dict[str, object],
                audio: str,
                device: str,
                return_char_alignments: bool,
            ) -> dict[str, object]:
                return {
                    "text": "Azure responds.",
                    "language": "en",
                    "segments": [
                        {
                            "id": 0,
                            "start": 0.1,
                            "end": 1.1,
                            "text": "Azure responds.",
                        }
                    ],
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            replacements_path = Path(temp_dir) / "replacements.json"
            replacements_path.write_text(
                json.dumps([{"source": "Azure", "replacement": "BlueSky"}]),
                encoding="utf-8",
            )

            transcriber = WhisperXTranscriber(
                config=TranscriptionConfig(
                    language="en",
                    term_replacements_path=replacements_path,
                ),
                module_loader=lambda: _FakeWhisperXModuleWithTerms(),
            )

            with self.assertRaises(TranscriptionError) as context:
                transcriber.transcribe_file(Path("sample.wav"))

        self.assertIn("two-item arrays", str(context.exception))

    def test_pseudonymize_person_names_is_opt_in(self) -> None:
        class _FakeWhisperXModuleWithNames(_FakeWhisperXModule):
            @staticmethod
            def align(
                segments: list[dict[str, object]],
                model_a: str,
                metadata: dict[str, object],
                audio: str,
                device: str,
                return_char_alignments: bool,
            ) -> dict[str, object]:
                return {
                    "text": "John Smith spoke.",
                    "language": "en",
                    "segments": [
                        {
                            "id": 0,
                            "start": 0.1,
                            "end": 1.1,
                            "text": "John Smith spoke.",
                        }
                    ],
                }

        transcriber = WhisperXTranscriber(
            config=TranscriptionConfig(language="en"),
            module_loader=lambda: _FakeWhisperXModuleWithNames(),
            person_ner_pipeline_loader=lambda model_name: _fake_person_ner_pipeline,
        )

        transcript = transcriber.transcribe_file(Path("sample.wav"))

        self.assertEqual(transcript.text, "John Smith spoke.")
        self.assertEqual(transcript.segments[0]["text"], "John Smith spoke.")

    def test_pseudonymize_person_names_rewrites_unique_first_name_references(
        self,
    ) -> None:
        class _FakeWhisperXModuleWithNames(_FakeWhisperXModule):
            @staticmethod
            def align(
                segments: list[dict[str, object]],
                model_a: str,
                metadata: dict[str, object],
                audio: str,
                device: str,
                return_char_alignments: bool,
            ) -> dict[str, object]:
                return {
                    "text": "John Smith arrived. John spoke first.",
                    "language": "en",
                    "segments": [
                        {
                            "id": 0,
                            "start": 0.1,
                            "end": 1.1,
                            "text": "John Smith arrived.",
                        },
                        {
                            "id": 1,
                            "start": 1.2,
                            "end": 2.2,
                            "text": "John spoke first.",
                        },
                    ],
                }

        transcriber = WhisperXTranscriber(
            config=TranscriptionConfig(
                language="en",
                pseudonymize_person_names=True,
            ),
            module_loader=lambda: _FakeWhisperXModuleWithNames(),
            person_ner_pipeline_loader=lambda model_name: _fake_person_ner_pipeline,
        )

        transcript = transcriber.transcribe_file(Path("sample.wav"))

        self.assertEqual(
            transcript.text,
            "Alice Archer arrived. Alice spoke first.",
        )
        self.assertEqual(
            transcript.segments[1]["text"],
            "Alice spoke first.",
        )

    def test_pseudonymize_person_names_rewrites_surname_only_references(self) -> None:
        class _FakeWhisperXModuleWithNames(_FakeWhisperXModule):
            @staticmethod
            def align(
                segments: list[dict[str, object]],
                model_a: str,
                metadata: dict[str, object],
                audio: str,
                device: str,
                return_char_alignments: bool,
            ) -> dict[str, object]:
                return {
                    "text": "John Smith arrived. Smith spoke first.",
                    "language": "en",
                    "segments": [
                        {
                            "id": 0,
                            "start": 0.1,
                            "end": 1.1,
                            "text": "John Smith arrived.",
                        },
                        {
                            "id": 1,
                            "start": 1.2,
                            "end": 2.2,
                            "text": "Smith spoke first.",
                        },
                    ],
                }

        transcriber = WhisperXTranscriber(
            config=TranscriptionConfig(
                language="en",
                pseudonymize_person_names=True,
            ),
            module_loader=lambda: _FakeWhisperXModuleWithNames(),
            person_ner_pipeline_loader=lambda model_name: _fake_person_ner_pipeline,
        )

        transcript = transcriber.transcribe_file(Path("sample.wav"))

        self.assertEqual(
            transcript.text,
            "Alice Archer arrived. Archer spoke first.",
        )
        self.assertEqual(
            transcript.segments[1]["text"],
            "Archer spoke first.",
        )

    def test_pseudonymize_person_names_rewrites_standalone_first_name_entities(
        self,
    ) -> None:
        class _FakeWhisperXModuleWithSingleNames(_FakeWhisperXModule):
            @staticmethod
            def align(
                segments: list[dict[str, object]],
                model_a: str,
                metadata: dict[str, object],
                audio: str,
                device: str,
                return_char_alignments: bool,
            ) -> dict[str, object]:
                return {
                    "text": "John arrived. Mary answered.",
                    "language": "en",
                    "segments": [
                        {
                            "id": 0,
                            "start": 0.1,
                            "end": 1.1,
                            "text": "John arrived.",
                        },
                        {
                            "id": 1,
                            "start": 1.2,
                            "end": 2.2,
                            "text": "Mary answered.",
                        },
                    ],
                }

        transcriber = WhisperXTranscriber(
            config=TranscriptionConfig(
                language="en",
                pseudonymize_person_names=True,
            ),
            module_loader=lambda: _FakeWhisperXModuleWithSingleNames(),
            person_ner_pipeline_loader=(
                lambda model_name: _fake_single_name_ner_pipeline
            ),
        )

        transcript = transcriber.transcribe_file(Path("sample.wav"))

        self.assertEqual(
            transcript.text,
            "Avery arrived. Blake answered.",
        )
        self.assertEqual(
            transcript.segments[0]["text"],
            "Avery arrived.",
        )
        self.assertEqual(
            transcript.segments[1]["text"],
            "Blake answered.",
        )

    def test_pseudonymize_person_names_merges_split_multilingual_person_entities(
        self,
    ) -> None:
        class _FakeWhisperXModuleWithFrenchNames(_FakeWhisperXModule):
            @staticmethod
            def load_model(
                model_name: str,
                device: str,
                compute_type: str,
                language: str | None,
            ) -> _FakeWhisperXModel:
                if model_name != "small":
                    raise AssertionError(model_name)
                if device != "cpu":
                    raise AssertionError(device)
                if compute_type != "int8":
                    raise AssertionError(compute_type)
                if language != "fr":
                    raise AssertionError(language)
                return _FakeWhisperXModel()

            @staticmethod
            def load_align_model(
                language_code: str,
                device: str,
            ) -> tuple[str, dict[str, object]]:
                if language_code != "fr":
                    raise AssertionError(language_code)
                if device != "cpu":
                    raise AssertionError(device)
                return "align-model", {"language": "fr"}

            @staticmethod
            def align(
                segments: list[dict[str, object]],
                model_a: str,
                metadata: dict[str, object],
                audio: str,
                device: str,
                return_char_alignments: bool,
            ) -> dict[str, object]:
                return {
                    "text": (
                        "Il y a aussi Justine qui nous accompagne. "
                        "Jonathan parle avec Justine."
                    ),
                    "language": "fr",
                    "segments": [
                        {
                            "id": 0,
                            "start": 0.1,
                            "end": 1.1,
                            "text": "Il y a aussi Justine qui nous accompagne.",
                        },
                        {
                            "id": 1,
                            "start": 1.2,
                            "end": 2.2,
                            "text": "Jonathan parle avec Justine.",
                        },
                    ],
                }

        transcriber = WhisperXTranscriber(
            config=TranscriptionConfig(
                language="fr",
                pseudonymize_person_names=True,
            ),
            module_loader=lambda: _FakeWhisperXModuleWithFrenchNames(),
            person_ner_pipeline_loader=(
                lambda model_name: _fake_split_french_name_ner_pipeline
            ),
        )

        transcript = transcriber.transcribe_file(Path("sample.wav"))

        self.assertEqual(
            transcript.text,
            "Il y a aussi Avery qui nous accompagne. Blake parle avec Avery.",
        )
        self.assertEqual(
            transcript.segments[0]["text"],
            "Il y a aussi Avery qui nous accompagne.",
        )
        self.assertEqual(
            transcript.segments[1]["text"],
            "Blake parle avec Avery.",
        )

    def test_pseudonymize_person_names_uses_segments_for_long_transcripts(self) -> None:
        class _FakeWhisperXModuleWithLongFrenchTranscript(_FakeWhisperXModule):
            @staticmethod
            def load_model(
                model_name: str,
                device: str,
                compute_type: str,
                language: str | None,
            ) -> _FakeWhisperXModel:
                if model_name != "small":
                    raise AssertionError(model_name)
                if device != "cpu":
                    raise AssertionError(device)
                if compute_type != "int8":
                    raise AssertionError(compute_type)
                if language != "fr":
                    raise AssertionError(language)
                return _FakeWhisperXModel()

            @staticmethod
            def load_align_model(
                language_code: str,
                device: str,
            ) -> tuple[str, dict[str, object]]:
                if language_code != "fr":
                    raise AssertionError(language_code)
                if device != "cpu":
                    raise AssertionError(device)
                return "align-model", {"language": "fr"}

            @staticmethod
            def align(
                segments: list[dict[str, object]],
                model_a: str,
                metadata: dict[str, object],
                audio: str,
                device: str,
                return_char_alignments: bool,
            ) -> dict[str, object]:
                segment_one = "Il y a aussi Justine qui nous accompagne."
                segment_two = "Jonathan parle avec Justine."
                filler = "contexte neutre " * 40
                return {
                    "text": f"{filler}{segment_one} {segment_two}",
                    "language": "fr",
                    "segments": [
                        {
                            "id": 0,
                            "start": 0.1,
                            "end": 1.1,
                            "text": segment_one,
                        },
                        {
                            "id": 1,
                            "start": 1.2,
                            "end": 2.2,
                            "text": segment_two,
                        },
                    ],
                }

        transcriber = WhisperXTranscriber(
            config=TranscriptionConfig(
                language="fr",
                pseudonymize_person_names=True,
            ),
            module_loader=lambda: _FakeWhisperXModuleWithLongFrenchTranscript(),
            person_ner_pipeline_loader=(
                lambda model_name: _fake_length_sensitive_french_ner_pipeline
            ),
        )

        transcript = transcriber.transcribe_file(Path("sample.wav"))

        self.assertIn("Avery", transcript.text)
        self.assertIn("Blake", transcript.text)
        self.assertNotIn("Justine", transcript.text)
        self.assertNotIn("Jonathan", transcript.text)
        self.assertEqual(
            transcript.segments[0]["text"],
            "Il y a aussi Avery qui nous accompagne.",
        )
        self.assertEqual(
            transcript.segments[1]["text"],
            "Blake parle avec Avery.",
        )


if __name__ == "__main__":
    unittest.main()
