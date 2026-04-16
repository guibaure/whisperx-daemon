# Installation

## Package Manager

This project uses [uv](https://docs.astral.sh/uv/) for virtual environment
creation and dependency installation. Install it with:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Pinning Strategy

The repository uses shared constraints files plus environment-specific
requirement entrypoints:

- [`../constraints-runtime.txt`](../constraints-runtime.txt)
  Shared runtime version contract.
- [`../constraints-dev.txt`](../constraints-dev.txt)
  Shared development-tool version contract.
- [`../requirements-cpu.txt`](../requirements-cpu.txt)
  CPU runtime dependencies.
- [`../requirements-cuda.txt`](../requirements-cuda.txt)
  CUDA runtime dependencies.
- [`../requirements-dev-cpu.txt`](../requirements-dev-cpu.txt)
  CPU runtime dependencies plus development tools and editable installs.
- [`../requirements-dev-cuda.txt`](../requirements-dev-cuda.txt)
  CUDA runtime dependencies plus development tools and editable installs.

Current shared runtime pins:

- `whisperx==3.8.4`
- `torch==2.8.0`
- `torchaudio==2.8.0`
- `torchcodec>=0.7,<0.8`

The `torchcodec` upper bound is intentional because the current WhisperX and
PyTorch combination is incompatible with `torchcodec > 0.7`.

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

Development requirement files install both packages editably:

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
