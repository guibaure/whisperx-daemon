"""Module entry point for ``python -m transcript_postprocess``."""

from __future__ import annotations

from .cli import main
from .core import PostprocessError

if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(main())
    except PostprocessError as exc:
        raise SystemExit(str(exc)) from exc
