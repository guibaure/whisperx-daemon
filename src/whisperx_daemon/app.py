"""Application bootstrap for the daemon runtime.

This module translates high-level runtime settings into concrete collaborators:
filesystem layout creation, logging, job-store initialisation, and daemon
construction. The ``run`` function is intentionally small so that orchestration
behaviour is easy to follow and easy to exercise in tests.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import BinaryIO, cast

from .config import RuntimeLayout, StreamingConfig, TranscriptionConfig
from .filesystem import ensure_runtime_directories
from .state import JobStore
from .streaming import StreamingSessionRunner
from .watcher import WatcherConfig, WorkspaceWatcher


def configure_logging(logs_dir: Path) -> logging.Logger:
    """Build the dedicated daemon logger.

    The logger writes to both stderr and ``daemon.log`` inside the runtime log
    directory. Existing handlers are removed first so repeated test runs or
    repeated calls to :func:`run` do not duplicate log lines.
    """

    logger = logging.getLogger("whisperx_daemon")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(logs_dir / "daemon.log")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def run(
    runtime_dir: Path,
    poll_interval: float,
    stability_window: float,
    run_once: bool,
    force_reprocess: bool = False,
    transcription_config: TranscriptionConfig | None = None,
) -> None:
    """Initialise the runtime directory and start the transcription daemon.

    Args:
        runtime_dir: Root directory containing inputs, outputs, logs, and the
            SQLite state database.
        poll_interval: Delay, in seconds, between scans when watch mode runs
            continuously.
        stability_window: Minimum file age, in seconds, before a candidate is
            considered ready for processing.
        run_once: When true, process currently available files and exit instead
            of entering the infinite watch loop.
        force_reprocess: When true, process files even when the same path and
            content digest have already been recorded previously.
        transcription_config: Optional WhisperX-specific runtime settings. A
            default configuration is created when this argument is omitted.
    """

    layout = RuntimeLayout.from_root(runtime_dir)
    ensure_runtime_directories(layout)

    logger = configure_logging(layout.logs_dir)
    store = JobStore(layout.state_db_path)
    store.initialise()
    resolved_transcription_config = resolve_transcription_config(
        transcription_config or TranscriptionConfig(),
        layout,
    )

    watcher = WorkspaceWatcher(
        layout=layout,
        store=store,
        config=WatcherConfig(
            poll_interval=poll_interval,
            stability_window=stability_window,
            force_reprocess=force_reprocess,
        ),
        transcription_config=resolved_transcription_config,
        logger=logger,
    )

    logger.info("Runtime root: %s", layout.root)
    if run_once:
        processed_files = watcher.run_once()
        logger.info("Run complete. Processed %d file(s).", len(processed_files))
        return

    logger.info("Starting watch loop.")
    watcher.watch_forever()


def run_stream(
    runtime_dir: Path,
    streaming_config: StreamingConfig,
    transcription_config: TranscriptionConfig | None = None,
    input_stream: BinaryIO | None = None,
) -> None:
    """Initialise the runtime directory and process one raw PCM stream.

    Args:
        runtime_dir: Root directory for stream artefacts, logs, and state.
        streaming_config: Stream identity, PCM format, and windowing settings.
        transcription_config: Optional WhisperX-specific runtime settings. A
            default configuration is created when this argument is omitted.
        input_stream: Optional binary stream override used by tests. When
            omitted, the configured input path is opened or stdin is consumed.
    """

    layout = RuntimeLayout.from_root(runtime_dir)
    ensure_runtime_directories(layout)

    logger = configure_logging(layout.logs_dir)
    store = JobStore(layout.state_db_path)
    store.initialise()
    resolved_transcription_config = resolve_transcription_config(
        transcription_config or TranscriptionConfig(),
        layout,
    )

    logger.info("Runtime root: %s", layout.root)
    logger.info("Starting stream transcription: %s", streaming_config.stream_id)

    owned_input_stream: BinaryIO | None = None
    if input_stream is None:
        if streaming_config.input_path is None:
            input_stream = cast(BinaryIO, sys.stdin.buffer)
        else:
            owned_input_stream = streaming_config.input_path.open("rb")
            input_stream = owned_input_stream

    try:
        runner = StreamingSessionRunner(
            layout=layout,
            transcription_config=resolved_transcription_config,
            streaming_config=streaming_config,
            logger=logger,
        )
        runner.run(input_stream)
    finally:
        if owned_input_stream is not None:
            owned_input_stream.close()


def resolve_transcription_config(
    transcription_config: TranscriptionConfig,
    layout: RuntimeLayout,
) -> TranscriptionConfig:
    """Resolve runtime-local configuration defaults.

    The CLI remains explicit, but the daemon can still pick up a
    runtime-local term-replacement file when the user has not provided one
    directly.
    """

    if transcription_config.term_replacements_path is not None:
        return transcription_config

    default_term_replacements_path = layout.root / "term-replacements.json"
    if not default_term_replacements_path.is_file():
        return transcription_config

    return TranscriptionConfig(
        model_name=transcription_config.model_name,
        device=transcription_config.device,
        language=transcription_config.language,
        compute_type=transcription_config.compute_type,
        batch_size=transcription_config.batch_size,
        diarize=transcription_config.diarize,
        hf_token=transcription_config.hf_token,
        min_speakers=transcription_config.min_speakers,
        max_speakers=transcription_config.max_speakers,
        pseudonymize_person_names=transcription_config.pseudonymize_person_names,
        person_ner_model=transcription_config.person_ner_model,
        term_replacements_path=default_term_replacements_path,
        omit_txt_time_ranges=transcription_config.omit_txt_time_ranges,
        omit_txt_speaker_labels=transcription_config.omit_txt_speaker_labels,
    )
