"""Command-line entry point for ``python -m whisperx_daemon``.

This thin wrapper deliberately delegates all argument parsing and orchestration
to :mod:`whisperx_daemon.cli` so the CLI remains testable without spawning a
new Python interpreter.
"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
