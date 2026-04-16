# Installation

## Package Manager

This project uses [uv](https://docs.astral.sh/uv/) for virtual environment
creation and dependency installation. Install it with:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Pinning Strategy

All dependency pins live in the root `pyproject.toml`:

- `[project].dependencies` — runtime pins (`torch`, `torchaudio`, `whisperx`,
  `torchcodec`).
- `[project.optional-dependencies].dev` — development-tool pins (`mypy`,
  `ruff`).

Current shared runtime pins:

- `whisperx==3.8.4`
- `torch==2.8.0`
- `torchaudio==2.8.0`
- `torchcodec>=0.7,<0.8`

The `torchcodec` upper bound is intentional because the current WhisperX and
PyTorch combination is incompatible with `torchcodec > 0.7`.

CPU and CUDA variants install the same packages — the PyTorch index URL passed
at install time (`--index-url`) determines which wheel flavour is resolved.

## Local CPU Environment

```bash
make setup-cpu
. .venv/bin/activate
```

## Local CUDA Environment

```bash
make setup-cuda
. .venv/bin/activate
```

## Package Layout

This monorepo contains two Python packages:

- `whisperx-daemon`
- `transcript-postprocess`

The Makefile targets install both packages editably:

- `-e .`
- `-e ./packages/transcript-postprocess[ner]`

This preserves a real package boundary while keeping local development simple.

## Plain-Checkout Convenience

The repository includes checkout-time shims so these commands work from a plain
clone:

```bash
python3 -m whisperx_daemon --help
python3 -m transcript_postprocess --help
```

Installed environments are still the recommended mode for real use and CI.
