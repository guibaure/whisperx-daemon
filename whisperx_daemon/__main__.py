"""Local-development ``python -m whisperx_daemon`` entry point."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
