"""Filesystem helpers for runtime directory management and file inspection."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterable
from pathlib import Path

from .config import RuntimeLayout

SUPPORTED_AUDIO_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".wav",
    ".wma",
}


def ensure_runtime_directories(layout: RuntimeLayout) -> None:
    """Create the runtime tree if it does not already exist.

    The function is idempotent so it can be called on every startup without
    forcing callers to distinguish between first-run and steady-state cases.
    """

    for path in (
        layout.root,
        layout.input_dir,
        layout.processing_dir,
        layout.archive_dir,
        layout.archive_succeeded_dir,
        layout.archive_failed_dir,
        layout.output_dir,
        layout.failed_dir,
        layout.logs_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)


def iter_audio_files(input_dir: Path) -> Iterable[Path]:
    """Yield supported audio files from the input directory in a stable order.

    A sorted traversal keeps processing deterministic, which matters for tests,
    logs, and operational debugging.
    """

    for path in sorted(input_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS:
            yield path


def is_file_stable(path: Path, stability_window_seconds: float, now: float) -> bool:
    """Treat a file as stable once it is older than the configured window.

    The watcher does not attempt incremental-write detection. Instead, it uses a
    simple minimum-age heuristic to avoid processing files that are still being
    copied into the input directory.
    """

    stat_result = path.stat()
    return (now - stat_result.st_mtime) >= stability_window_seconds


def compute_file_digest(path: Path) -> str:
    """Hash the file contents to support idempotent processing.

    The digest is computed chunk by chunk so large audio files do not need to be
    loaded into memory at once.
    """

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_payload(path: Path, payload: object) -> None:
    """Persist structured JSON with stable formatting.

    All structured artefacts use the same indentation so generated files are
    readable by humans and diff-friendly in tests.
    """

    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def move_runtime_file(source_path: Path, target_dir: Path) -> Path:
    """Move a runtime-managed file into another lifecycle directory.

    Args:
        source_path: Existing file path to move.
        target_dir: Destination runtime directory, such as ``processing``,
            ``output``, or ``failed``.

    Returns:
        The final destination path after the move completes.
    """

    target_dir.mkdir(parents=True, exist_ok=True)
    destination_path = target_dir / source_path.name
    return Path(shutil.move(str(source_path), str(destination_path)))
