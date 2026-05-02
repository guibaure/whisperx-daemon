"""Streaming audio ingestion and transcription orchestration.

The streaming path is intentionally separate from the file watcher. File mode
continues to manage stable files, while stream mode consumes raw PCM bytes,
splits them into deterministic overlapping windows, and lets higher layers
transcribe those windows incrementally.
"""

from __future__ import annotations

import wave
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .config import StreamingConfig


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
