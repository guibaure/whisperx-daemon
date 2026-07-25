"""Compatibility wrapper around the standalone transcript-postprocess CLI.

The reusable post-processing logic now lives in the independent
``transcript_postprocess`` package. This module preserves the historical
``python -m whisperx_daemon.standalone`` entrypoint so existing workflows do
not break while the reusable package is extracted cleanly.
"""

from __future__ import annotations

from transcript_postprocess import PostprocessError
from transcript_postprocess.cli import main

__all__ = ["main"]


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PostprocessError as exc:
        raise SystemExit(str(exc)) from exc
