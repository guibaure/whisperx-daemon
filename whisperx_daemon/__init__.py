from __future__ import annotations

from pathlib import Path

"""Development-time import shim for the ``src`` layout.

The repository keeps the importable package under ``src/``. This top-level shim
lets ``python -m whisperx_daemon`` work from a checkout without first
installing the package into the active environment.
"""

# This shim keeps ``python -m whisperx_daemon`` working without installation by
# pointing imports at the ``src`` package during local development.
_SOURCE_PACKAGE_DIR = Path(__file__).resolve().parent.parent / "src" / "whisperx_daemon"

__path__ = [str(_SOURCE_PACKAGE_DIR)]
