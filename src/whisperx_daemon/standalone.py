"""Compatibility wrapper around the standalone textformer CLI.

The reusable post-processing logic now lives in the independent
``textformer`` package. This module preserves the historical
``python -m whisperx_daemon.standalone`` entrypoint so existing workflows do
not break while the reusable package is extracted cleanly.
"""

from __future__ import annotations

from textformer import PostprocessError
from textformer.cli import main

__all__ = ["main"]


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PostprocessError as exc:
        raise SystemExit(str(exc)) from exc
