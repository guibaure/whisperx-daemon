"""Runtime watcher loop and per-file orchestration.

The watcher scans the runtime input directory, skips unstable files, avoids
reprocessing unchanged content, and delegates actual transcription work to the
pipeline layer.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from .config import RuntimeLayout, TranscriptionConfig
from .filesystem import (
    compute_file_digest,
    is_file_stable,
    iter_audio_files,
    move_runtime_file,
)
from .pipeline import (
    TranscriptionError,
    WhisperXTranscriber,
    write_failure_report,
    write_transcript_outputs,
)
from .state import JobStore


@dataclass(frozen=True)
class WatcherConfig:
    """Settings that control how often the runtime directory is scanned."""

    poll_interval: float
    stability_window: float
    force_reprocess: bool = False


class WorkspaceWatcher:
    """Poll the runtime input directory and process eligible audio files."""

    def __init__(
        self,
        layout: RuntimeLayout,
        store: JobStore,
        config: WatcherConfig,
        transcription_config: TranscriptionConfig,
        logger: logging.Logger,
        transcriber: WhisperXTranscriber | None = None,
    ) -> None:
        self._layout = layout
        self._store = store
        self._config = config
        self._transcription_config = transcription_config
        self._logger = logger
        # The transcriber is injectable so tests can exercise the watcher
        # without importing or loading WhisperX.
        self._transcriber = transcriber or WhisperXTranscriber(transcription_config)

    def run_once(self, now: float | None = None) -> list[Path]:
        """Scan the input directory once and process any stable files.

        Args:
            now: Optional timestamp override used primarily by tests.

        Returns:
            The list of files that were processed during this scan. Unchanged or
            unstable files are omitted.
        """

        stable_now = time.time() if now is None else now
        processed_files: list[Path] = []
        for candidate in iter_audio_files(self._layout.input_dir):
            if not is_file_stable(candidate, self._config.stability_window, stable_now):
                continue
            if self._process_candidate(candidate):
                processed_files.append(candidate)
        return processed_files

    def watch_forever(self) -> None:
        """Poll the runtime directory indefinitely.

        This is the steady-state production loop for the program. The method
        intentionally contains no shutdown policy beyond process termination.
        """

        while True:
            self.run_once()
            time.sleep(self._config.poll_interval)

    def _process_candidate(self, source_path: Path) -> bool:
        """Transcribe a single stable file unless its contents are unchanged.

        Returns:
            ``True`` when the candidate produced a new success or failure
            artefact, and ``False`` when it was skipped because the content
            digest matched the existing database record.
        """

        file_digest = compute_file_digest(source_path)
        existing_record = self._store.fetch_by_source_path(str(source_path))
        if (
            not self._config.force_reprocess
            and existing_record is not None
            and existing_record.file_digest == file_digest
        ):
            self._logger.info("Skipping unchanged file: %s", source_path.name)
            return False

        processing_path = move_runtime_file(source_path, self._layout.processing_dir)
        try:
            transcript_document = self._transcriber.transcribe_file(
                processing_path,
                logical_source_path=source_path,
            )
            output_paths = write_transcript_outputs(
                transcript_document,
                self._layout.output_dir,
                include_time_ranges=not self._transcription_config.omit_txt_time_ranges,
            )
            archived_audio_path = move_runtime_file(
                processing_path,
                self._layout.archive_succeeded_dir,
            )
        except TranscriptionError as exc:
            failed_audio_path = move_runtime_file(
                processing_path,
                self._layout.archive_failed_dir,
            )
            failure_path = write_failure_report(
                processing_path,
                self._layout.failed_dir,
                str(exc),
                logical_source_path=source_path,
            )
            self._store.upsert_job(
                source_path=str(source_path),
                file_digest=file_digest,
                status="failed_transcription",
                output_path=str(failure_path),
            )
            self._logger.error(
                "Transcription failed for %s: %s. Archived failed input at %s",
                source_path.name,
                exc,
                failed_audio_path,
            )
            return True

        self._store.upsert_job(
            source_path=str(source_path),
            file_digest=file_digest,
            status="completed_transcription",
            output_path=str(output_paths["json"]),
        )
        self._logger.info(
            "Transcribed file: %s. Archived processed input at %s",
            source_path.name,
            archived_audio_path,
        )
        return True
