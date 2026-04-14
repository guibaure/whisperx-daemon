"""Configuration objects shared across the runtime.

The repository keeps configuration deliberately small and explicit. The two
dataclasses below describe:

- how WhisperX should run for a single processing session
- where the program should read and write runtime artefacts on disk
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from transcript_postprocess import DEFAULT_PERSON_NER_MODEL


@dataclass(frozen=True)
class TranscriptionConfig:
    """Runtime settings for WhisperX transcription.

    These settings are assembled by the CLI and passed through the bootstrap
    layer into :class:`whisperx_daemon.pipeline.WhisperXTranscriber`.
    """

    model_name: str = "small"
    device: str = "cpu"
    language: str | None = None
    compute_type: str = "int8"
    batch_size: int = 8
    diarize: bool = False
    hf_token: str | None = None
    min_speakers: int | None = None
    max_speakers: int | None = None
    pseudonymize_person_names: bool = False
    person_ner_model: str = DEFAULT_PERSON_NER_MODEL
    term_replacements_path: Path | None = None
    omit_txt_time_ranges: bool = False


@dataclass(frozen=True)
class RuntimeLayout:
    """Resolved paths used by the watcher runtime.

    The watcher treats the runtime root as a managed directory tree. Resolving
    all subpaths up front keeps file-handling code simple and avoids scattered
    string concatenation throughout the program.
    """

    root: Path
    input_dir: Path
    processing_dir: Path
    archive_dir: Path
    archive_succeeded_dir: Path
    archive_failed_dir: Path
    output_dir: Path
    failed_dir: Path
    logs_dir: Path
    state_db_path: Path

    @classmethod
    def from_root(cls, root: Path) -> RuntimeLayout:
        """Build the runtime layout from a single root directory.

        Args:
            root: User-provided runtime root, either relative or absolute.

        Returns:
            A layout whose fields all point at concrete absolute paths.
        """

        resolved_root = root.resolve()
        return cls(
            root=resolved_root,
            input_dir=resolved_root / "input",
            processing_dir=resolved_root / "processing",
            archive_dir=resolved_root / "archive",
            archive_succeeded_dir=resolved_root / "archive" / "succeeded",
            archive_failed_dir=resolved_root / "archive" / "failed",
            output_dir=resolved_root / "output",
            failed_dir=resolved_root / "failed",
            logs_dir=resolved_root / "logs",
            state_db_path=resolved_root / "jobs.sqlite3",
        )
