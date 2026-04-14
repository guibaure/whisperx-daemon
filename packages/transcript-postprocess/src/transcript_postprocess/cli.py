"""Standalone CLI for transcript post-processing."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import DEFAULT_PERSON_NER_MODEL, postprocess_text


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the standalone post-processing CLI."""

    parser = argparse.ArgumentParser(
        prog="transcript-postprocess",
        description=(
            "Apply pseudonymisation and configured term replacements to plain text."
        ),
    )
    parser.add_argument(
        "--input-file",
        type=Path,
        default=None,
        help="Optional input text file. Reads stdin when omitted.",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=None,
        help="Optional output text file. Writes stdout when omitted.",
    )
    parser.add_argument(
        "--pseudonymize-person-names",
        action="store_true",
        help="Replace detected person names with pseudonyms.",
    )
    parser.add_argument(
        "--person-ner-model",
        default=DEFAULT_PERSON_NER_MODEL,
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
    return parser


def read_input_text(input_path: Path | None) -> str:
    """Read plain text from a file or stdin."""

    if input_path is None:
        return sys.stdin.read()
    return input_path.read_text(encoding="utf-8")


def write_output_text(output_path: Path | None, text: str) -> None:
    """Write plain text to a file or stdout."""

    if output_path is None:
        sys.stdout.write(text)
        return
    output_path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Run the standalone post-processing CLI."""

    args = build_argument_parser().parse_args(argv)
    input_text = read_input_text(args.input_file)
    output_text = postprocess_text(
        input_text,
        pseudonymize_person_names=args.pseudonymize_person_names,
        person_ner_model=args.person_ner_model,
        term_replacements_path=args.term_replacements_file,
    )
    write_output_text(args.output_file, output_text)
    return 0
