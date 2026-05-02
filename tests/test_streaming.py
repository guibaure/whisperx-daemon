"""Tests for stream ingestion and PCM windowing."""

from __future__ import annotations

import io
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from whisperx_daemon.config import StreamingConfig
from whisperx_daemon.streaming import (
    AudioWindowBuffer,
    PcmStreamReader,
    PcmWaveRecorder,
    StreamingError,
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
