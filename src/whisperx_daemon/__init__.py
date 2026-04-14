"""Public package surface for the WhisperX daemon.

The package exposes :func:`run` as the programmatic entry point used by tests
and by any future embedding code. The command-line interface lives in
``whisperx_daemon.cli`` and calls the same runtime bootstrap function.
"""

from .app import run

__all__ = ["run"]
