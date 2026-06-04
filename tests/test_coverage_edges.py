"""Focused edge-case tests for complete branch coverage.

These tests cover operational failure paths and small pure-function branches
that are not naturally reached by the broader integration tests.
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from textformer import PostprocessError
from textformer import cli as postprocess_cli
from textformer.core import (
    assign_person_pseudonyms,
    build_person_alias_map,
    build_person_replacement_map,
    build_pseudonym,
    build_pseudonym_alias,
    build_single_token_pseudonym,
    build_standalone_person_name_map,
    capitalise_proper_noun,
    extract_person_name_candidate,
    iter_detected_person_names,
    iter_person_alias_tokens,
    iter_person_name_candidates,
    normalise_term_replacement_entries,
    parse_entity_span,
    postprocess_text,
    replace_named_terms,
)
from textformer.core import (
    load_person_ner_pipeline as load_postprocess_person_ner_pipeline,
)
from textformer.core import (
    load_term_replacement_map as load_postprocess_term_replacement_map,
)

from whisperx_daemon import app as app_module
from whisperx_daemon import cli as daemon_cli
from whisperx_daemon.config import RuntimeLayout, StreamingConfig, TranscriptionConfig
from whisperx_daemon.filesystem import (
    compute_file_digest,
    ensure_runtime_directories,
    iter_audio_files,
)
from whisperx_daemon.pipeline import (
    TranscriptDocument,
    TranscriptionError,
    WhisperXTranscriber,
    build_plain_text_transcript,
    format_timestamp,
    iter_person_detection_fragments,
    load_whisperx_module,
    normalise_segment,
    pseudonymize_transcript_document,
    replace_terms_in_transcript_document,
)
from whisperx_daemon.state import JobStore
from whisperx_daemon.streaming import (
    AudioWindow,
    AudioWindowBuffer,
    SegmentCommitter,
    StreamingError,
    StreamingSessionRunner,
    StreamingWindowTranscriber,
    _result_language,
    validate_streaming_config,
)
from whisperx_daemon.watcher import WatcherConfig, WorkspaceWatcher


def _document(
    text: str = "hello",
    segments: list[dict[str, object]] | None = None,
) -> TranscriptDocument:
    """Build a minimal transcript document for pure output tests."""

    return TranscriptDocument(
        source_path="sample.wav",
        generated_at="2026-01-01T00:00:00+00:00",
        status="completed",
        text=text,
        language="en",
        segments=segments or [],
        speakers=[],
    )


class PostprocessCoreEdgeTests(unittest.TestCase):
    """Exercise standalone post-processing failure and edge branches."""

    def test_person_ner_loader_reports_missing_transformers(self) -> None:
        with patch(
            "textformer.core.importlib.import_module",
            side_effect=ModuleNotFoundError("transformers"),
        ):
            with self.assertRaisesRegex(PostprocessError, "transformers"):
                load_postprocess_person_ner_pipeline("example/model")

    def test_term_replacement_loader_validates_file_and_payload_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            missing_path = temp_path / "missing.json"
            invalid_json_path = temp_path / "invalid.json"
            invalid_root_path = temp_path / "invalid-root.json"
            invalid_item_path = temp_path / "invalid-item.json"
            valid_list_path = temp_path / "valid-list.json"

            invalid_json_path.write_text("{", encoding="utf-8")
            invalid_root_path.write_text(json.dumps("Azure"), encoding="utf-8")
            invalid_item_path.write_text(
                json.dumps([{"source": "Azure"}]),
                encoding="utf-8",
            )
            valid_list_path.write_text(
                json.dumps([["Azure", "blue sky"]]),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(PostprocessError, "not found"):
                load_postprocess_term_replacement_map(missing_path)
            with self.assertRaisesRegex(PostprocessError, "valid JSON"):
                load_postprocess_term_replacement_map(invalid_json_path)
            with self.assertRaisesRegex(PostprocessError, "object or a list"):
                load_postprocess_term_replacement_map(invalid_root_path)
            with self.assertRaisesRegex(PostprocessError, "two-item arrays"):
                load_postprocess_term_replacement_map(invalid_item_path)

            self.assertEqual(
                load_postprocess_term_replacement_map(valid_list_path),
                {"Azure": "Blue sky"},
            )

    def test_term_replacement_entry_normalisation_rejects_bad_entries(self) -> None:
        replacements_path = Path("terms.json")

        with self.assertRaisesRegex(PostprocessError, "empty"):
            normalise_term_replacement_entries([("Azure", "")], replacements_path)
        with self.assertRaisesRegex(PostprocessError, "duplicate"):
            normalise_term_replacement_entries(
                [("Azure", "Blue"), ("azure", "Sky")],
                replacements_path,
            )

        self.assertEqual(capitalise_proper_noun(""), "")

    def test_postprocess_text_can_apply_only_term_replacements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            replacements_path = Path(temp_dir) / "terms.json"
            replacements_path.write_text(
                json.dumps({"Azure": "BlueSky"}),
                encoding="utf-8",
            )

            processed = postprocess_text(
                "Azure ships.",
                term_replacements_path=replacements_path,
            )

        self.assertEqual(processed, "BlueSky ships.")

    def test_person_detection_handles_empty_duplicate_and_non_person_entities(
        self,
    ) -> None:
        self.assertEqual(build_person_replacement_map("  ", lambda text: []), {})

        detected_names = iter_detected_person_names(
            "John John",
            lambda text: [
                {"entity_group": "PER", "word": ""},
                {"entity_group": "PER", "word": "John"},
                {"entity_group": "PER", "word": "John"},
            ],
        )
        self.assertEqual(detected_names, ["John"])

        candidates = iter_person_name_candidates(
            "ACME John",
            [
                {"entity_group": "ORG", "word": "ACME"},
                {"entity_group": "PER", "word": ""},
                {"entity_group": "PER", "word": "John"},
            ],
        )
        self.assertEqual(candidates, ["John"])

    def test_person_span_merging_handles_invalid_and_overlapping_entities(self) -> None:
        self.assertEqual(
            extract_person_name_candidate(
                "John Smith",
                [
                    {"entity_group": "PER", "start": 0, "end": 4},
                    {"entity_group": "PER", "start": 5, "end": 10},
                ],
                0,
            ),
            ("John Smith", 2),
        )
        self.assertEqual(
            extract_person_name_candidate(
                "John ACME",
                [
                    {"entity_group": "PER", "start": 0, "end": 4},
                    {"entity_group": "ORG", "start": 5, "end": 9},
                ],
                0,
            ),
            ("John", 1),
        )
        self.assertEqual(
            extract_person_name_candidate(
                "John Smith",
                [
                    {"entity_group": "PER", "start": 0, "end": 4},
                    {"entity_group": "PER", "word": "Smith"},
                ],
                0,
            ),
            ("John", 1),
        )
        self.assertEqual(
            extract_person_name_candidate(
                "Justine",
                [
                    {"entity_group": "PER", "start": 0, "end": 6},
                    {"entity_group": "PER", "start": 5, "end": 7},
                ],
                0,
            ),
            ("Justine", 2),
        )
        self.assertEqual(
            extract_person_name_candidate(
                "John, Smith",
                [
                    {"entity_group": "PER", "start": 0, "end": 4},
                    {"entity_group": "PER", "start": 6, "end": 11},
                ],
                0,
            ),
            ("John", 1),
        )
        self.assertEqual(parse_entity_span({"start": 2, "end": 1}, 10), (None, None))

    def test_person_pseudonym_helpers_cover_alias_and_fallback_paths(self) -> None:
        self.assertEqual(
            assign_person_pseudonyms(["John Smith", "John Smith"])["John Smith"],
            "Alice Archer",
        )
        self.assertEqual(
            assign_person_pseudonyms(["John", "John"]),
            {"John": "Avery"},
        )
        self.assertEqual(
            build_person_alias_map(
                {
                    "John Smith": "Alice Archer",
                    "John Doe": "Benjamin Bennett",
                }
            )["John"],
            "Avery",
        )
        self.assertEqual(
            build_person_alias_map({"John Middle Smith": "Alias"}),
            {},
        )
        self.assertEqual(
            build_standalone_person_name_map(
                ["John", "Smith", "Mary", "Mary"],
                {"John Smith": "Alice Archer"},
                {"Mary": "Existing"},
            ),
            {"John": "Alice", "Smith": "Archer"},
        )
        self.assertEqual(
            build_standalone_person_name_map(["John"], {"John Smith": "Alias"}, {}),
            {"John": "Avery"},
        )
        self.assertEqual(iter_person_alias_tokens("Prince"), tuple())
        self.assertEqual(
            iter_person_alias_tokens("Jean Claude Van Damme"),
            ("Jean", "Damme"),
        )
        self.assertIsNone(build_pseudonym_alias("John", "John", "Alice Archer"))
        self.assertIsNone(build_pseudonym_alias("Other", "Jean Claude", "Alice Archer"))
        self.assertEqual(build_pseudonym(25), "Alias Person 26")
        self.assertEqual(build_single_token_pseudonym(20), "Alias21")
        self.assertEqual(replace_named_terms("No change", {}), "No change")


class StandaloneCliEdgeTests(unittest.TestCase):
    """Cover stdin/stdout branches of the reusable post-processing CLI."""

    def test_cli_reads_stdin_and_writes_stdout(self) -> None:
        stdout = io.StringIO()

        with patch.object(sys, "stdin", io.StringIO("plain text")):
            with patch.object(sys, "stdout", stdout):
                exit_code = postprocess_cli.main([])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue(), "plain text")


class PipelineEdgeTests(unittest.TestCase):
    """Exercise low-level WhisperX adapter branches without loading WhisperX."""

    def test_load_whisperx_module_success_and_failure_paths(self) -> None:
        fake_module = object()
        with patch(
            "whisperx_daemon.pipeline.importlib.import_module",
            return_value=fake_module,
        ):
            self.assertIs(load_whisperx_module(), fake_module)

        with patch(
            "whisperx_daemon.pipeline.importlib.import_module",
            side_effect=ModuleNotFoundError("whisperx"),
        ):
            with self.assertRaisesRegex(TranscriptionError, "WhisperX"):
                load_whisperx_module()

    def test_transcriber_load_module_and_alignment_without_language(self) -> None:
        fake_module = object()
        transcriber = WhisperXTranscriber(
            TranscriptionConfig(),
            module_loader=lambda: fake_module,
        )
        result = {"segments": [{"text": "hello"}]}

        self.assertIs(transcriber.load_module(), fake_module)
        self.assertIs(
            transcriber.align_transcript(fake_module, "audio", result),
            result,
        )

    def test_normalise_segment_drops_unsupported_timestamp_and_speaker_types(
        self,
    ) -> None:
        segment = normalise_segment(
            {
                "id": 7,
                "start": object(),
                "end": object(),
                "speaker": 3,
                "text": "hello",
            }
        )

        self.assertEqual(segment["id"], 7)
        self.assertEqual(segment["text"], "hello")
        self.assertNotIn("start", segment)
        self.assertNotIn("end", segment)
        self.assertNotIn("speaker", segment)

    def test_transcribe_loaded_audio_preserves_external_session_on_failure(
        self,
    ) -> None:
        class _ExternalSession:
            closed = False

            def transcribe(self, audio: object) -> dict[str, object]:
                raise RuntimeError("synthetic failure")

            def close(self) -> None:
                self.closed = True

        session = _ExternalSession()
        transcriber = WhisperXTranscriber(TranscriptionConfig())

        with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
            transcriber.transcribe_loaded_audio(
                object(),
                "audio",
                model_session=session,  # type: ignore[arg-type]
            )

        self.assertFalse(session.closed)

    def test_diarization_pipeline_falls_back_to_token_argument(self) -> None:
        class _TokenOnlyPipeline:
            def __init__(
                self,
                token: str | None = None,
                device: str = "cpu",
                use_auth_token: str | None = None,
            ) -> None:
                if use_auth_token is not None:
                    raise TypeError("legacy signature")
                self.token = token
                self.device = device

        transcriber = WhisperXTranscriber(
            TranscriptionConfig(hf_token="hf-token", device="cpu")
        )

        pipeline = transcriber._build_diarization_pipeline(_TokenOnlyPipeline)

        self.assertEqual(pipeline.token, "hf-token")
        self.assertEqual(pipeline.device, "cpu")

    def test_cuda_memory_release_handles_missing_and_unavailable_cuda(self) -> None:
        transcriber = WhisperXTranscriber(TranscriptionConfig(device="cuda"))

        with patch(
            "whisperx_daemon.pipeline.importlib.import_module",
            side_effect=ModuleNotFoundError("torch"),
        ):
            transcriber._release_runtime_memory()

        with patch(
            "whisperx_daemon.pipeline.importlib.import_module",
            return_value=object(),
        ):
            transcriber._release_runtime_memory()

        class _UnavailableCuda:
            @staticmethod
            def is_available() -> bool:
                return False

        with patch(
            "whisperx_daemon.pipeline.importlib.import_module",
            return_value=SimpleNamespace(cuda=_UnavailableCuda()),
        ):
            transcriber._release_runtime_memory()

    def test_cuda_memory_release_tolerates_missing_ipc_collect(self) -> None:
        class _CudaWithoutIpcCollect:
            def __init__(self) -> None:
                self.empty_cache_calls = 0

            @staticmethod
            def is_available() -> bool:
                return True

            def empty_cache(self) -> None:
                self.empty_cache_calls += 1

        cuda = _CudaWithoutIpcCollect()
        transcriber = WhisperXTranscriber(TranscriptionConfig(device="cuda"))

        with patch(
            "whisperx_daemon.pipeline.importlib.import_module",
            return_value=SimpleNamespace(cuda=cuda),
        ):
            transcriber._release_runtime_memory()

        self.assertEqual(cuda.empty_cache_calls, 1)

    def test_document_postprocessing_noops_and_text_fallbacks(self) -> None:
        document = _document(
            text="plain text",
            segments=[{"text": "   "}],
        )

        self.assertIs(
            pseudonymize_transcript_document(document, lambda text: []),
            document,
        )
        self.assertIs(replace_terms_in_transcript_document(document, {}), document)
        self.assertEqual(iter_person_detection_fragments(document), ["plain text"])
        self.assertEqual(iter_person_detection_fragments(_document(text="")), [])
        self.assertEqual(build_plain_text_transcript(document), "plain text")
        self.assertEqual(format_timestamp("unknown"), "unknown")


class AppAndCliEdgeTests(unittest.TestCase):
    """Cover daemon bootstrap and CLI dispatch branches."""

    def test_run_enters_watch_loop_when_once_is_false(self) -> None:
        class _StopWatchLoop(RuntimeError):
            pass

        class _FakeWatcher:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs

            def watch_forever(self) -> None:
                raise _StopWatchLoop("stop")

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("whisperx_daemon.app.WorkspaceWatcher", _FakeWatcher):
                with self.assertRaisesRegex(_StopWatchLoop, "stop"):
                    app_module.run(
                        runtime_dir=Path(temp_dir) / "runtime",
                        poll_interval=0.1,
                        stability_window=0.0,
                        run_once=False,
                    )

    def test_run_stream_uses_explicit_input_stream(self) -> None:
        captured_payloads: list[bytes] = []

        class _FakeRunner:
            def __init__(self, **kwargs: object) -> None:
                pass

            def run(self, input_stream: io.BytesIO) -> None:
                captured_payloads.append(input_stream.read())

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("whisperx_daemon.app.StreamingSessionRunner", _FakeRunner):
                app_module.run_stream(
                    runtime_dir=Path(temp_dir) / "runtime",
                    streaming_config=StreamingConfig(stream_id="explicit"),
                    input_stream=io.BytesIO(b"explicit"),
                )

        self.assertEqual(captured_payloads, [b"explicit"])

    def test_run_stream_reads_stdin_when_no_input_path_is_configured(self) -> None:
        captured_payloads: list[bytes] = []

        class _FakeRunner:
            def __init__(self, **kwargs: object) -> None:
                pass

            def run(self, input_stream: io.BytesIO) -> None:
                captured_payloads.append(input_stream.read())

        fake_stdin = SimpleNamespace(buffer=io.BytesIO(b"stdin"))

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("whisperx_daemon.app.StreamingSessionRunner", _FakeRunner):
                with patch.object(app_module.sys, "stdin", fake_stdin):
                    app_module.run_stream(
                        runtime_dir=Path(temp_dir) / "runtime",
                        streaming_config=StreamingConfig(stream_id="stdin"),
                    )

        self.assertEqual(captured_payloads, [b"stdin"])

    def test_run_stream_closes_owned_input_file(self) -> None:
        captured_streams: list[io.BufferedReader] = []

        class _FakeRunner:
            def __init__(self, **kwargs: object) -> None:
                pass

            def run(self, input_stream: io.BufferedReader) -> None:
                captured_streams.append(input_stream)
                input_stream.read()

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "stream.pcm"
            input_path.write_bytes(b"file")

            with patch("whisperx_daemon.app.StreamingSessionRunner", _FakeRunner):
                app_module.run_stream(
                    runtime_dir=Path(temp_dir) / "runtime",
                    streaming_config=StreamingConfig(
                        stream_id="file",
                        input_path=input_path,
                    ),
                )

        self.assertTrue(captured_streams[0].closed)

    def test_cli_dispatches_non_stream_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(
                sys,
                "argv",
                [
                    "whisperx-daemon",
                    "--runtime-dir",
                    temp_dir,
                    "--once",
                    "--hf-token",
                    "explicit",
                ],
            ):
                with patch("whisperx_daemon.cli.run") as run_mock:
                    with patch("whisperx_daemon.cli.run_stream") as run_stream_mock:
                        exit_code = daemon_cli.main()

        self.assertEqual(exit_code, 0)
        run_stream_mock.assert_not_called()
        run_mock.assert_called_once()
        self.assertEqual(run_mock.call_args.kwargs["runtime_dir"], Path(temp_dir))
        self.assertEqual(
            run_mock.call_args.kwargs["transcription_config"].hf_token,
            "explicit",
        )

    def test_cli_resolves_stream_input_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "stream.pcm"
            with patch.object(
                sys,
                "argv",
                [
                    "whisperx-daemon",
                    "--stream",
                    "--runtime-dir",
                    temp_dir,
                    "--stream-input",
                    str(input_path),
                ],
            ):
                with patch("whisperx_daemon.cli.run_stream") as run_stream_mock:
                    exit_code = daemon_cli.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            run_stream_mock.call_args.kwargs["streaming_config"].input_path,
            input_path,
        )


class FilesystemAndWatcherEdgeTests(unittest.TestCase):
    """Cover watcher lifecycle branches that integration tests do not hit."""

    def test_iter_audio_files_skips_directories_and_unsupported_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir)
            (input_dir / "nested.wav").mkdir()
            (input_dir / "notes.txt").write_text("ignore", encoding="utf-8")
            (input_dir / "audio.WAV").write_bytes(b"audio")

            self.assertEqual(
                list(iter_audio_files(input_dir)),
                [input_dir / "audio.WAV"],
            )

    def test_run_once_skips_unstable_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            layout = RuntimeLayout.from_root(Path(temp_dir) / "runtime")
            ensure_runtime_directories(layout)
            source_path = layout.input_dir / "sample.wav"
            source_path.write_bytes(b"audio")
            now = time.time()
            os.utime(source_path, (now, now))
            store = JobStore(layout.state_db_path)
            store.initialise()
            watcher = WorkspaceWatcher(
                layout=layout,
                store=store,
                config=WatcherConfig(poll_interval=0.01, stability_window=10.0),
                transcription_config=TranscriptionConfig(),
                logger=logging.getLogger("test-unstable"),
                transcriber=object(),  # type: ignore[arg-type]
            )

            self.assertEqual(watcher.run_once(now=now), [])
            self.assertTrue(source_path.exists())

    def test_run_once_skips_unchanged_recorded_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            layout = RuntimeLayout.from_root(Path(temp_dir) / "runtime")
            ensure_runtime_directories(layout)
            source_path = layout.input_dir / "sample.wav"
            source_path.write_bytes(b"audio")
            old_timestamp = time.time() - 20
            os.utime(source_path, (old_timestamp, old_timestamp))
            store = JobStore(layout.state_db_path)
            store.initialise()
            store.upsert_job(
                source_path=str(source_path),
                file_digest=compute_file_digest(source_path),
                status="completed_transcription",
                output_path=str(layout.output_dir / "sample.json"),
            )
            watcher = WorkspaceWatcher(
                layout=layout,
                store=store,
                config=WatcherConfig(poll_interval=0.01, stability_window=0.0),
                transcription_config=TranscriptionConfig(),
                logger=logging.getLogger("test-unchanged"),
                transcriber=object(),  # type: ignore[arg-type]
            )

            self.assertEqual(watcher.run_once(now=time.time()), [])
            self.assertTrue(source_path.exists())

    def test_watch_forever_sleeps_between_scans(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            layout = RuntimeLayout.from_root(Path(temp_dir) / "runtime")
            ensure_runtime_directories(layout)
            store = JobStore(layout.state_db_path)
            store.initialise()
            watcher = WorkspaceWatcher(
                layout=layout,
                store=store,
                config=WatcherConfig(poll_interval=0.25, stability_window=0.0),
                transcription_config=TranscriptionConfig(),
                logger=logging.getLogger("test-watch-forever"),
                transcriber=object(),  # type: ignore[arg-type]
            )

            with patch.object(
                watcher,
                "run_once",
                side_effect=[[], RuntimeError("stop")],
            ):
                with patch("whisperx_daemon.watcher.time.sleep") as sleep_mock:
                    with self.assertRaisesRegex(RuntimeError, "stop"):
                        watcher.watch_forever()

        sleep_mock.assert_called_once_with(0.25)


class StreamingEdgeTests(unittest.TestCase):
    """Cover stream validation, no-op, and failure branches."""

    def test_streaming_config_validation_reports_each_invalid_field(self) -> None:
        invalid_configs = [
            (StreamingConfig(sample_rate=0), "sample rate"),
            (StreamingConfig(sample_width_bytes=1), "16-bit"),
            (StreamingConfig(window_seconds=0), "window"),
            (StreamingConfig(step_seconds=0), "step"),
            (StreamingConfig(window_seconds=1, step_seconds=2), "exceed"),
            (StreamingConfig(commit_overlap_seconds=-0.1), "negative"),
            (StreamingConfig(stream_id=" "), "session id"),
        ]

        for config, message in invalid_configs:
            with self.subTest(message=message):
                with self.assertRaisesRegex(StreamingError, message):
                    validate_streaming_config(config)

    def test_audio_window_buffer_flushes_empty_when_no_trailing_samples(self) -> None:
        buffer = AudioWindowBuffer(
            StreamingConfig(
                sample_rate=2,
                window_seconds=1.0,
                step_seconds=1.0,
                commit_overlap_seconds=0.0,
            )
        )

        windows = buffer.append(b"\x00\x00\x01\x00")

        self.assertEqual(len(windows), 1)
        self.assertEqual(buffer.flush(), [])

    def test_segment_committer_skips_invalid_duplicate_and_unstable_segments(
        self,
    ) -> None:
        config = StreamingConfig(
            sample_rate=4,
            window_seconds=1.0,
            step_seconds=0.5,
            commit_overlap_seconds=0.25,
        )
        committer = SegmentCommitter(config)
        window = AudioWindow(
            pcm_bytes=b"\x00\x00" * 4,
            start_sample=0,
            sample_rate=4,
            channels=1,
            sample_width_bytes=2,
        )

        committed = committer.commit_segments(
            window,
            {
                "segments": [
                    "not-a-dict",
                    {"id": 1, "start": 0.0, "end": "unknown", "text": "bad"},
                    {"id": 2, "start": 0.0, "end": 0.5, "text": "first"},
                    {"id": 3, "start": 0.1, "end": 0.4, "text": "duplicate"},
                    {"id": 4, "start": 0.5, "end": 0.9, "text": "unstable"},
                ]
            },
        )

        self.assertEqual([segment["text"] for segment in committed], ["first"])

    def test_streaming_window_transcriber_requires_started_context(self) -> None:
        window_transcriber = StreamingWindowTranscriber(
            WhisperXTranscriber(TranscriptionConfig())
        )

        window_transcriber.__exit__(None, None, None)
        with self.assertRaisesRegex(StreamingError, "not been started"):
            window_transcriber.transcribe_window(
                AudioWindow(
                    pcm_bytes=b"\x00\x00",
                    start_sample=0,
                    sample_rate=16_000,
                    channels=1,
                    sample_width_bytes=2,
                )
            )

    def test_result_language_returns_none_for_missing_language(self) -> None:
        self.assertIsNone(_result_language({"language": ""}))
        self.assertIsNone(_result_language({}))

    def test_runner_rejects_diarisation_without_recording(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            layout = RuntimeLayout.from_root(Path(temp_dir) / "runtime")
            ensure_runtime_directories(layout)
            runner = StreamingSessionRunner(
                layout=layout,
                transcription_config=TranscriptionConfig(diarize=True),
                streaming_config=StreamingConfig(
                    stream_id="no-recording",
                    save_recording=False,
                ),
                logger=logging.getLogger("test-stream-no-recording"),
            )

            with self.assertRaisesRegex(StreamingError, "recording"):
                runner.run(io.BytesIO())

    def test_runner_can_complete_without_recording_or_committed_segments(self) -> None:
        class _NoSegmentWindowTranscriber:
            def __enter__(self) -> _NoSegmentWindowTranscriber:
                return self

            def __exit__(self, *_exc_info: object) -> None:
                return None

            def transcribe_window(self, window: AudioWindow) -> dict[str, object]:
                return {"language": "", "segments": []}

        with tempfile.TemporaryDirectory() as temp_dir:
            layout = RuntimeLayout.from_root(Path(temp_dir) / "runtime")
            ensure_runtime_directories(layout)
            runner = StreamingSessionRunner(
                layout=layout,
                transcription_config=TranscriptionConfig(language="en"),
                streaming_config=StreamingConfig(
                    stream_id="no-recording",
                    sample_rate=2,
                    window_seconds=1.0,
                    step_seconds=1.0,
                    commit_overlap_seconds=0.0,
                    save_recording=False,
                ),
                logger=logging.getLogger("test-stream-no-recording-success"),
                transcriber=WhisperXTranscriber(
                    TranscriptionConfig(language="en"),
                    module_loader=lambda: object(),
                ),
                window_transcriber_factory=lambda transcriber: (
                    _NoSegmentWindowTranscriber()
                ),
            )

            result = runner.run(io.BytesIO(b"\x00\x00\x01\x00"))
            self.assertTrue(result.output_paths["json"].is_file())

        self.assertIsNone(result.archived_recording_path)

    def test_runner_handles_direct_streaming_errors_without_recording(self) -> None:
        class _StreamingErrorWindowTranscriber:
            def __enter__(self) -> _StreamingErrorWindowTranscriber:
                return self

            def __exit__(self, *_exc_info: object) -> None:
                return None

            def transcribe_window(self, window: AudioWindow) -> dict[str, object]:
                raise StreamingError("direct streaming failure")

        with tempfile.TemporaryDirectory() as temp_dir:
            layout = RuntimeLayout.from_root(Path(temp_dir) / "runtime")
            ensure_runtime_directories(layout)
            runner = StreamingSessionRunner(
                layout=layout,
                transcription_config=TranscriptionConfig(language="en"),
                streaming_config=StreamingConfig(
                    stream_id="direct-error",
                    sample_rate=2,
                    window_seconds=1.0,
                    step_seconds=1.0,
                    commit_overlap_seconds=0.0,
                    save_recording=False,
                ),
                logger=logging.getLogger("test-stream-direct-error"),
                transcriber=WhisperXTranscriber(
                    TranscriptionConfig(language="en"),
                    module_loader=lambda: object(),
                ),
                window_transcriber_factory=lambda transcriber: (
                    _StreamingErrorWindowTranscriber()
                ),
            )

            with self.assertRaisesRegex(StreamingError, "direct streaming failure"):
                runner.run(io.BytesIO(b"\x00\x00\x01\x00"))

            failure_payload = json.loads(
                (layout.failed_dir / "direct-error.error.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(failure_payload["source_path"], "stream:direct-error")

    def test_archive_recording_failure_noops_when_recording_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            layout = RuntimeLayout.from_root(Path(temp_dir) / "runtime")
            ensure_runtime_directories(layout)
            runner = StreamingSessionRunner(
                layout=layout,
                transcription_config=TranscriptionConfig(language="en"),
                streaming_config=StreamingConfig(stream_id="missing-recording"),
                logger=logging.getLogger("test-stream-missing-recording"),
            )

            self.assertIsNone(runner._archive_recording_on_failure())


if __name__ == "__main__":
    unittest.main()
