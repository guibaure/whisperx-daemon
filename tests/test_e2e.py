"""Optional end-to-end tests that exercise the real WhisperX runtime.

These tests are intentionally skipped unless the caller provides a real audio
fixture through environment variables. That keeps the default unit-test path
fast and deterministic while still giving the repository a reproducible way to
validate the full stack against an actual audio file.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from whisperx_daemon.app import run
from whisperx_daemon.config import TranscriptionConfig


def _env_flag_is_enabled(name: str) -> bool:
    """Interpret common truthy strings used in shell-driven test execution."""

    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _build_transcription_config() -> TranscriptionConfig:
    """Assemble a real-runtime configuration for the end-to-end test path."""

    return TranscriptionConfig(
        model_name=os.environ.get("WHISPERX_E2E_MODEL", "small"),
        device=os.environ.get("WHISPERX_E2E_DEVICE", "cpu"),
        language=os.environ.get("WHISPERX_E2E_LANGUAGE") or None,
        compute_type=os.environ.get(
            "WHISPERX_E2E_COMPUTE_TYPE",
            "float16" if os.environ.get("WHISPERX_E2E_DEVICE") == "cuda" else "int8",
        ),
        batch_size=int(os.environ.get("WHISPERX_E2E_BATCH_SIZE", "8")),
        diarize=_env_flag_is_enabled("WHISPERX_E2E_DIARIZE"),
        hf_token=os.environ.get("HF_TOKEN")
        or os.environ.get("HUGGINGFACE_TOKEN")
        or None,
    )


@unittest.skipUnless(
    _env_flag_is_enabled("WHISPERX_E2E"),
    "Set WHISPERX_E2E=1 to run the real-fixture WhisperX end-to-end test.",
)
class RealFixtureEndToEndTests(unittest.TestCase):
    """Exercise the watcher end to end with a caller-provided real audio file."""

    def test_run_once_processes_a_real_audio_fixture(self) -> None:
        fixture_path = os.environ.get("WHISPERX_E2E_AUDIO")
        if not fixture_path:
            self.fail("WHISPERX_E2E_AUDIO must point to a real audio fixture.")

        source_fixture = Path(fixture_path).expanduser().resolve()
        self.assertTrue(source_fixture.is_file(), source_fixture)

        transcription_config = _build_transcription_config()

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir) / "runtime"
            input_path = runtime_dir / "input" / source_fixture.name
            input_path.parent.mkdir(parents=True, exist_ok=True)
            input_path.write_bytes(source_fixture.read_bytes())

            run(
                runtime_dir=runtime_dir,
                poll_interval=0.1,
                stability_window=0.0,
                run_once=True,
                transcription_config=transcription_config,
            )

            output_json_path = runtime_dir / "output" / f"{source_fixture.stem}.json"
            output_text_path = runtime_dir / "output" / f"{source_fixture.stem}.txt"
            failure_path = runtime_dir / "failed" / f"{source_fixture.stem}.error.json"

            self.assertFalse(failure_path.exists(), failure_path)
            self.assertTrue(output_json_path.is_file(), output_json_path)
            self.assertTrue(output_text_path.is_file(), output_text_path)

            payload = json.loads(output_json_path.read_text(encoding="utf-8"))
            text_output = output_text_path.read_text(encoding="utf-8").strip()

            self.assertEqual(payload["status"], "completed")
            self.assertIsInstance(payload["segments"], list)
            self.assertGreater(len(payload["segments"]), 0)
            self.assertTrue(text_output)


if __name__ == "__main__":
    unittest.main()
