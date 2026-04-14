"""Command-line interface for the WhisperX daemon.

The CLI is intentionally thin: it defines user-facing arguments, resolves
environment-variable fallbacks, and hands the parsed values to the application
bootstrap layer.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .app import run
from .config import TranscriptionConfig


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the command-line interface for the daemon.

    Returns:
        A fully configured :class:`argparse.ArgumentParser` for both one-shot
        and continuous daemon execution.
    """

    parser = argparse.ArgumentParser(
        prog="whisperx-daemon",
        description=(
            "Monitor a runtime directory for new audio files and transcribe "
            "them with WhisperX."
        ),
    )
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=Path("./runtime"),
        help=(
            "Runtime root containing input, processing, archive, output, "
            "failed, and logs directories."
        ),
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Polling interval in seconds for watch mode.",
    )
    parser.add_argument(
        "--stability-window",
        type=float,
        default=1.0,
        help="Minimum age in seconds before a file is considered stable.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process available stable files once and then exit.",
    )
    parser.add_argument(
        "--force-reprocess",
        action="store_true",
        help=(
            "Process stable files even when the same path and content digest "
            "were already recorded."
        ),
    )
    parser.add_argument(
        "--model",
        default="small",
        help="WhisperX model name to load.",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="Execution device passed to WhisperX, for example 'cpu' or 'cuda'.",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Optional language override for transcription.",
    )
    parser.add_argument(
        "--compute-type",
        default="int8",
        help="WhisperX compute type, such as 'int8' or 'float16'.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="Batch size passed to the WhisperX transcriber.",
    )
    parser.add_argument(
        "--diarize",
        action="store_true",
        help="Enable speaker diarisation via WhisperX and pyannote.",
    )
    parser.add_argument(
        "--hf-token",
        default=None,
        help=(
            "Hugging Face access token for diarisation. Falls back to "
            "HF_TOKEN or HUGGINGFACE_TOKEN."
        ),
    )
    parser.add_argument(
        "--min-speakers",
        type=int,
        default=None,
        help="Optional minimum speaker count hint for diarisation.",
    )
    parser.add_argument(
        "--max-speakers",
        type=int,
        default=None,
        help="Optional maximum speaker count hint for diarisation.",
    )
    parser.add_argument(
        "--pseudonymize-person-names",
        action="store_true",
        help="Replace detected person names in transcript text with pseudonyms.",
    )
    parser.add_argument(
        "--person-ner-model",
        default="Davlan/xlm-roberta-base-ner-hrl",
        help="Hugging Face token-classification model used for person-name detection.",
    )
    parser.add_argument(
        "--term-replacements-file",
        type=Path,
        default=None,
        help=(
            "Optional JSON file describing proper-noun replacements applied "
            "after pseudonymisation."
        ),
    )
    parser.add_argument(
        "--omit-txt-time-ranges",
        action="store_true",
        help="Write plain-text transcripts without leading [start:end] time ranges.",
    )
    return parser


def main() -> int:
    """Parse CLI arguments and start the application.

    Returns:
        Shell-style process exit status. The current implementation returns
        ``0`` when argument parsing and runtime bootstrap complete without a
        synchronous Python exception.
    """

    args = build_argument_parser().parse_args()
    hf_token = (
        args.hf_token
        or os.environ.get("HF_TOKEN")
        or os.environ.get("HUGGINGFACE_TOKEN")
    )
    run(
        runtime_dir=args.runtime_dir,
        poll_interval=args.poll_interval,
        stability_window=args.stability_window,
        run_once=args.once,
        force_reprocess=args.force_reprocess,
        transcription_config=TranscriptionConfig(
            model_name=args.model,
            device=args.device,
            language=args.language,
            compute_type=args.compute_type,
            batch_size=args.batch_size,
            diarize=args.diarize,
            hf_token=hf_token,
            min_speakers=args.min_speakers,
            max_speakers=args.max_speakers,
            pseudonymize_person_names=args.pseudonymize_person_names,
            person_ner_model=args.person_ner_model,
            term_replacements_path=args.term_replacements_file,
            omit_txt_time_ranges=args.omit_txt_time_ranges,
        ),
    )
    return 0
