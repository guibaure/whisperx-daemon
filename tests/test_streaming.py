"""Tests for stream ingestion and PCM windowing."""

from __future__ import annotations

import io
import json
import logging
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from typing import Any

from whisperx_daemon.config import RuntimeLayout, StreamingConfig, TranscriptionConfig
from whisperx_daemon.filesystem import ensure_runtime_directories
from whisperx_daemon.pipeline import TranscriptDocument, WhisperXTranscriber
from whisperx_daemon.streaming import (
    AudioWindow,
    AudioWindowBuffer,
    JsonlStreamEventWriter,
    PcmStreamReader,
    PcmWaveRecorder,
    SegmentCommitter,
    StreamingError,
    StreamingSessionRunner,
    StreamingTranscriptAccumulator,
    StreamingWindowTranscriber,
    build_stream_event,
    offset_segment_timestamps,
    pcm_window_to_float32_audio,
    safe_stream_output_stem,
    samples_for_seconds,
    validate_streaming_config,
)


def _pcm_samples(*samples: int) -> bytes:
    """Encode signed 16-bit PCM samples for deterministic tests."""

    return struct.pack(f"<{len(samples)}h", *samples)


class StreamingValidationTests(unittest.TestCase):
    def test_validate_streaming_config_accepts_default_contract(self) -> None:
        validate_streaming_config(StreamingConfig())

    def test_validate_streaming_config_rejects_non_mono_audio(self) -> None:
        with self.assertRaisesRegex(StreamingError, "mono"):
            validate_streaming_config(StreamingConfig(channels=2))

    def test_validate_streaming_config_rejects_invalid_overlap(self) -> None:
        with self.assertRaisesRegex(StreamingError, "overlap"):
            validate_streaming_config(
                StreamingConfig(window_seconds=5.0, commit_overlap_seconds=5.0)
            )

    def test_samples_for_seconds_rejects_zero_length_values(self) -> None:
        with self.assertRaisesRegex(StreamingError, "at least one sample"):
            samples_for_seconds(0.0, 16_000)


class PcmStreamReaderTests(unittest.TestCase):
    def test_reader_yields_frame_aligned_chunks(self) -> None:
        stream = io.BytesIO(_pcm_samples(1, 2, 3, 4))
        reader = PcmStreamReader(
            stream,
            StreamingConfig(sample_rate=2),
            read_seconds=1.0,
        )

        chunks = list(reader.iter_chunks())

        self.assertEqual(chunks, [_pcm_samples(1, 2), _pcm_samples(3, 4)])

    def test_reader_rejects_partial_final_frame(self) -> None:
        stream = io.BytesIO(_pcm_samples(1) + b"\x00")
        reader = PcmStreamReader(stream, StreamingConfig(sample_rate=2))

        with self.assertRaisesRegex(StreamingError, "partial audio frame"):
            list(reader.iter_chunks())


class AudioWindowBufferTests(unittest.TestCase):
    def test_buffer_emits_overlapping_windows(self) -> None:
        buffer = AudioWindowBuffer(
            StreamingConfig(
                sample_rate=4,
                window_seconds=1.0,
                step_seconds=0.5,
                commit_overlap_seconds=0.25,
            )
        )

        first_windows = buffer.append(_pcm_samples(0, 1, 2, 3))
        second_windows = buffer.append(_pcm_samples(4, 5))

        self.assertEqual(len(first_windows), 1)
        self.assertEqual(first_windows[0].start_sample, 0)
        self.assertEqual(first_windows[0].sample_count, 4)
        self.assertEqual(first_windows[0].start_seconds, 0.0)
        self.assertEqual(first_windows[0].end_seconds, 1.0)
        self.assertFalse(first_windows[0].is_final)
        self.assertEqual(len(second_windows), 1)
        self.assertEqual(second_windows[0].start_sample, 2)
        self.assertEqual(second_windows[0].sample_count, 4)
        self.assertEqual(second_windows[0].start_seconds, 0.5)

    def test_buffer_flush_emits_trailing_final_window(self) -> None:
        buffer = AudioWindowBuffer(
            StreamingConfig(
                sample_rate=4,
                window_seconds=1.0,
                step_seconds=0.5,
                commit_overlap_seconds=0.25,
            )
        )

        self.assertEqual(buffer.append(_pcm_samples(0, 1, 2)), [])
        windows = buffer.flush()

        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].start_sample, 0)
        self.assertEqual(windows[0].sample_count, 3)
        self.assertTrue(windows[0].is_final)

    def test_buffer_rejects_partial_pcm_chunks(self) -> None:
        buffer = AudioWindowBuffer(StreamingConfig(sample_rate=4))

        with self.assertRaisesRegex(StreamingError, "partial audio frame"):
            buffer.append(b"\x00")


class PcmWaveRecorderTests(unittest.TestCase):
    def test_recorder_writes_valid_wav_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "stream.wav"
            recorder = PcmWaveRecorder(
                output_path,
                StreamingConfig(sample_rate=8),
            )
            recorder.write(_pcm_samples(1, 2, 3, 4))
            recorder.close()

            with wave.open(str(output_path), "rb") as handle:
                self.assertEqual(handle.getnchannels(), 1)
                self.assertEqual(handle.getsampwidth(), 2)
                self.assertEqual(handle.getframerate(), 8)
                self.assertEqual(handle.readframes(4), _pcm_samples(1, 2, 3, 4))


class StreamingTranscriptionPrimitiveTests(unittest.TestCase):
    def test_safe_stream_output_stem_replaces_path_unsafe_characters(self) -> None:
        self.assertEqual(safe_stream_output_stem("meeting/live:1"), "meeting_live_1")

    def test_pcm_window_to_float32_audio_normalises_int16_samples(self) -> None:
        window = AudioWindow(
            pcm_bytes=_pcm_samples(-32768, 0, 32767),
            start_sample=0,
            sample_rate=16_000,
            channels=1,
            sample_width_bytes=2,
        )

        audio = pcm_window_to_float32_audio(window)

        self.assertAlmostEqual(float(audio[0]), -1.0)
        self.assertAlmostEqual(float(audio[1]), 0.0)
        self.assertAlmostEqual(float(audio[2]), 32767 / 32768)

    def test_offset_segment_timestamps_preserves_non_numeric_values(self) -> None:
        segment = {"start": 1.0, "end": "unknown", "text": "hello"}

        updated_segment = offset_segment_timestamps(segment, 2.5)

        self.assertEqual(updated_segment["start"], 3.5)
        self.assertEqual(updated_segment["end"], "unknown")
        self.assertEqual(updated_segment["text"], "hello")

    def test_segment_committer_skips_overlap_until_final_window(self) -> None:
        config = StreamingConfig(
            sample_rate=4,
            window_seconds=1.0,
            step_seconds=0.5,
            commit_overlap_seconds=0.25,
        )
        committer = SegmentCommitter(config)
        window = AudioWindow(
            pcm_bytes=_pcm_samples(0, 1, 2, 3),
            start_sample=0,
            sample_rate=4,
            channels=1,
            sample_width_bytes=2,
        )

        committed_segments = committer.commit_segments(
            window,
            {
                "segments": [
                    {"id": 0, "start": 0.0, "end": 0.5, "text": "stable"},
                    {"id": 1, "start": 0.5, "end": 0.9, "text": "overlap"},
                ]
            },
        )

        self.assertEqual(
            [segment["text"] for segment in committed_segments],
            ["stable"],
        )

        final_window = AudioWindow(
            pcm_bytes=_pcm_samples(2, 3),
            start_sample=2,
            sample_rate=4,
            channels=1,
            sample_width_bytes=2,
            is_final=True,
        )
        final_segments = committer.commit_segments(
            final_window,
            {"segments": [{"id": 1, "start": 0.0, "end": 0.5, "text": "overlap"}]},
        )

        self.assertEqual([segment["text"] for segment in final_segments], ["overlap"])
        self.assertEqual(final_segments[0]["start"], 0.5)
        self.assertEqual(final_segments[0]["end"], 1.0)

    def test_transcript_accumulator_builds_final_document(self) -> None:
        accumulator = StreamingTranscriptAccumulator("meeting")
        accumulator.extend(
            [{"id": 0, "start": 0.0, "end": 1.0, "text": "Hello"}],
            language="en",
        )
        accumulator.extend(
            [{"id": 1, "start": 1.0, "end": 2.0, "text": "world"}],
            language="fr",
        )

        document = accumulator.build_document()

        self.assertEqual(document.source_path, "stream:meeting")
        self.assertEqual(document.text, "Hello world")
        self.assertEqual(document.language, "en")
        self.assertEqual(len(document.segments), 2)

    def test_jsonl_event_writer_appends_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "stream.events.jsonl"
            writer = JsonlStreamEventWriter(output_path)
            try:
                writer.write(build_stream_event("stream", "stream_started"))
                writer.write(
                    build_stream_event(
                        "stream",
                        "segment_final",
                        {"text": "hello"},
                    )
                )
            finally:
                writer.close()

            events = [
                json.loads(line)
                for line in output_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(events[0]["event"], "stream_started")
        self.assertEqual(events[1]["payload"], {"text": "hello"})

    def test_streaming_window_transcriber_reuses_loaded_session(self) -> None:
        class _FakeSession:
            def __init__(self) -> None:
                self.closed = False
                self.transcribed_audio: list[str] = []

            def transcribe(self, audio: str) -> dict[str, Any]:
                self.transcribed_audio.append(audio)
                return {
                    "text": "hello",
                    "language": "en",
                    "segments": [{"id": 0, "start": 0.0, "end": 0.5, "text": "hello"}],
                }

            def close(self) -> None:
                self.closed = True

        class _FakeTranscriber:
            def __init__(self) -> None:
                self.load_module_calls = 0
                self.session = _FakeSession()

            def load_module(self) -> object:
                self.load_module_calls += 1
                return object()

            def open_model_session(self, whisperx_module: object) -> _FakeSession:
                return self.session

            def transcribe_loaded_audio(
                self,
                whisperx_module: object,
                audio: str,
                model_session: _FakeSession,
            ) -> dict[str, Any]:
                return model_session.transcribe(audio)

            def align_transcript(
                self,
                whisperx_module: object,
                audio: str,
                result: dict[str, Any],
            ) -> dict[str, Any]:
                return result

        fake_transcriber = _FakeTranscriber()
        window = AudioWindow(
            pcm_bytes=_pcm_samples(1, 2),
            start_sample=0,
            sample_rate=16_000,
            channels=1,
            sample_width_bytes=2,
        )

        with StreamingWindowTranscriber(
            fake_transcriber,  # type: ignore[arg-type]
            audio_converter=lambda audio_window: "converted-audio",
        ) as window_transcriber:
            result = window_transcriber.transcribe_window(window)

        self.assertEqual(fake_transcriber.load_module_calls, 1)
        self.assertEqual(
            fake_transcriber.session.transcribed_audio,
            ["converted-audio"],
        )
        self.assertTrue(fake_transcriber.session.closed)
        self.assertEqual(result["text"], "hello")


class StreamingSessionRunnerTests(unittest.TestCase):
    def test_runner_writes_events_outputs_and_archived_recording(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            layout = RuntimeLayout.from_root(Path(temp_dir) / "runtime")
            ensure_runtime_directories(layout)
            fake_window_transcriber = _FakeWindowTranscriber()
            runner = StreamingSessionRunner(
                layout=layout,
                transcription_config=TranscriptionConfig(language="en"),
                streaming_config=StreamingConfig(
                    stream_id="meeting/live:1",
                    sample_rate=4,
                    window_seconds=1.0,
                    step_seconds=0.5,
                    commit_overlap_seconds=0.25,
                ),
                logger=logging.getLogger("test-stream-success"),
                transcriber=WhisperXTranscriber(
                    TranscriptionConfig(language="en"),
                    module_loader=lambda: object(),
                ),
                window_transcriber_factory=lambda transcriber: fake_window_transcriber,
            )

            result = runner.run(io.BytesIO(_pcm_samples(0, 1, 2, 3, 4, 5)))

            self.assertEqual(result.stream_id, "meeting/live:1")
            self.assertTrue(result.output_paths["json"].is_file())
            self.assertTrue(result.output_paths["txt"].is_file())
            self.assertEqual(result.event_path.name, "meeting_live_1.events.jsonl")
            self.assertTrue(
                (layout.archive_succeeded_dir / "meeting_live_1.wav").is_file()
            )
            self.assertFalse((layout.processing_dir / "meeting_live_1.wav").exists())

            payload = json.loads(result.output_paths["json"].read_text("utf-8"))
            self.assertEqual(payload["source_path"], "stream:meeting/live:1")
            self.assertEqual(
                [segment["text"] for segment in payload["segments"]],
                ["window-0", "window-2", "window-4"],
            )
            text_output = result.output_paths["txt"].read_text("utf-8")
            self.assertIn("[0.000:0.500] UNKNOWN: window-0", text_output)

            events = _read_jsonl_events(result.event_path)
            self.assertEqual(events[0]["event"], "stream_started")
            self.assertEqual(events[-1]["event"], "stream_completed")
            self.assertEqual(
                [event["event"] for event in events].count("segment_final"),
                3,
            )
            self.assertTrue(fake_window_transcriber.closed)

    def test_runner_records_failure_event_report_and_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            layout = RuntimeLayout.from_root(Path(temp_dir) / "runtime")
            ensure_runtime_directories(layout)
            runner = StreamingSessionRunner(
                layout=layout,
                transcription_config=TranscriptionConfig(language="en"),
                streaming_config=StreamingConfig(
                    stream_id="broken",
                    sample_rate=4,
                    window_seconds=1.0,
                    step_seconds=0.5,
                    commit_overlap_seconds=0.25,
                ),
                logger=logging.getLogger("test-stream-failure"),
                transcriber=WhisperXTranscriber(
                    TranscriptionConfig(language="en"),
                    module_loader=lambda: object(),
                ),
                window_transcriber_factory=(
                    lambda transcriber: _FailingWindowTranscriber()
                ),
            )

            with self.assertRaisesRegex(StreamingError, "synthetic stream failure"):
                runner.run(io.BytesIO(_pcm_samples(0, 1, 2, 3)))

            failure_path = layout.failed_dir / "broken.error.json"
            self.assertTrue(failure_path.is_file())
            self.assertTrue((layout.archive_failed_dir / "broken.wav").is_file())
            events = _read_jsonl_events(layout.output_dir / "broken.events.jsonl")
            self.assertEqual(events[-1]["event"], "stream_failed")
            self.assertIn("synthetic stream failure", events[-1]["payload"]["error"])

    def test_runner_uses_final_full_file_transcription_for_diarised_streams(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            layout = RuntimeLayout.from_root(Path(temp_dir) / "runtime")
            ensure_runtime_directories(layout)
            fake_transcriber = _FinalFileTranscriber()
            runner = StreamingSessionRunner(
                layout=layout,
                transcription_config=TranscriptionConfig(
                    language="en",
                    diarize=True,
                    hf_token="hf-token",
                ),
                streaming_config=StreamingConfig(
                    stream_id="diarised",
                    sample_rate=4,
                    window_seconds=1.0,
                    step_seconds=0.5,
                    commit_overlap_seconds=0.25,
                ),
                logger=logging.getLogger("test-stream-diarised"),
                transcriber=fake_transcriber,  # type: ignore[arg-type]
                window_transcriber_factory=lambda transcriber: _FakeWindowTranscriber(),
            )

            result = runner.run(io.BytesIO(_pcm_samples(0, 1, 2, 3)))

            payload = json.loads(result.output_paths["json"].read_text("utf-8"))
            self.assertEqual(payload["text"], "final diarised transcript")
            self.assertEqual(payload["segments"][0]["speaker"], "SPEAKER_00")
            self.assertEqual(
                fake_transcriber.logical_source_path,
                Path("stream:diarised"),
            )


class _FakeWindowTranscriber:
    def __init__(self) -> None:
        self.closed = False
        self.windows: list[AudioWindow] = []

    def __enter__(self) -> _FakeWindowTranscriber:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.closed = True

    def transcribe_window(self, window: AudioWindow) -> dict[str, Any]:
        self.windows.append(window)
        return {
            "language": "en",
            "segments": [
                {
                    "id": len(self.windows) - 1,
                    "start": 0.0,
                    "end": 0.5,
                    "text": f"window-{window.start_sample}",
                }
            ],
        }


class _FailingWindowTranscriber:
    def __enter__(self) -> _FailingWindowTranscriber:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        return None

    def transcribe_window(self, window: AudioWindow) -> dict[str, Any]:
        raise RuntimeError("synthetic stream failure")


class _FinalFileTranscriber:
    def __init__(self) -> None:
        self.source_path: Path | None = None
        self.logical_source_path: Path | None = None

    def transcribe_file(
        self,
        source_path: Path,
        logical_source_path: Path | None = None,
    ) -> TranscriptDocument:
        self.source_path = source_path
        self.logical_source_path = logical_source_path
        return TranscriptDocument(
            source_path=str(logical_source_path),
            generated_at="2026-01-01T00:00:00+00:00",
            status="completed",
            text="final diarised transcript",
            language="en",
            segments=[
                {
                    "id": 0,
                    "start": 0.0,
                    "end": 1.0,
                    "speaker": "SPEAKER_00",
                    "text": "final diarised transcript",
                }
            ],
            speakers=[{"label": "SPEAKER_00"}],
        )

    def postprocess_document(
        self,
        transcript_document: TranscriptDocument,
    ) -> TranscriptDocument:
        raise AssertionError("Diarised streams should use full-file transcription.")


def _read_jsonl_events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
