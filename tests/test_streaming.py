"""Tests for stream ingestion and PCM windowing."""

from __future__ import annotations

import io
import json
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from typing import Any

from whisperx_daemon.config import StreamingConfig
from whisperx_daemon.streaming import (
    AudioWindow,
    AudioWindowBuffer,
    JsonlStreamEventWriter,
    PcmStreamReader,
    PcmWaveRecorder,
    SegmentCommitter,
    StreamingError,
    StreamingTranscriptAccumulator,
    StreamingWindowTranscriber,
    build_stream_event,
    offset_segment_timestamps,
    pcm_window_to_float32_audio,
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
