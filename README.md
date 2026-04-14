# WhisperX Daemon

`whisperx-daemon` is a local-first audio transcription daemon built around
WhisperX. It watches a managed runtime directory, transcribes stable audio
files, writes JSON and plain-text outputs, archives the original inputs, and
records job state so unchanged files are not reprocessed accidentally.

It is designed as a production-oriented single-node service baseline, not as a
distributed platform.

## Features

- managed runtime lifecycle for input, processing, output, and archived files
- SQLite-backed idempotency for unchanged-file detection
- WhisperX transcription with alignment when the language is known
- optional speaker diarisation with Hugging Face token wiring
- optional person-name pseudonymisation
- optional deterministic proper-noun replacement
- CPU, CUDA, and Docker execution paths
- independent `transcript-postprocess` package for reusable text sanitisation
- CI, linting, formatting, mypy, and packaging checks

## Quick Start

### Local CPU

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev-cpu.txt

mkdir -p runtime/input
cp /path/to/example.mp3 runtime/input/

python3 -m whisperx_daemon \
  --runtime-dir ./runtime \
  --once \
  --model small \
  --device cpu \
  --compute-type int8
```

### Local CUDA

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev-cuda.txt

mkdir -p runtime/input
cp /path/to/example.mp3 runtime/input/

python3 -m whisperx_daemon \
  --runtime-dir ./runtime \
  --once \
  --model small \
  --device cuda \
  --compute-type float16
```

### Docker

```bash
docker build -t whisperx-daemon:latest .

docker run --rm \
  -v "$(pwd)/runtime:/app/runtime" \
  whisperx-daemon:latest \
  --runtime-dir /app/runtime \
  --once \
  --model small \
  --device cpu \
  --compute-type int8
```

For CUDA containers, the host must provide the NVIDIA Container Toolkit.

## Documentation

Use the focused documents under [`docs/`](./docs):

- [`docs/getting-started.md`](./docs/getting-started.md)
  Zero-to-first-run setup for CPU, CUDA, and continuous watch mode.
- [`docs/installation.md`](./docs/installation.md)
  Dependency pinning strategy, local bootstrap, and package layout.
- [`docs/usage.md`](./docs/usage.md)
  Common CLI workflows and operational examples.
- [`docs/configuration.md`](./docs/configuration.md)
  Runtime directory contract, lifecycle rules, idempotency, and flag reference.
- [`docs/output.md`](./docs/output.md)
  JSON, TXT, and failure-report output contracts.
- [`docs/post-processing.md`](./docs/post-processing.md)
  Pseudonymisation, term replacement, and standalone package usage.
- [`docs/docker.md`](./docs/docker.md)
  Docker build, CPU/CUDA execution, GPU requirements, and entrypoint override.
- [`docs/architecture.md`](./docs/architecture.md)
  Repository structure, module responsibilities, and processing flow.
- [`docs/troubleshooting.md`](./docs/troubleshooting.md)
  Common runtime and environment failures.

## Development

```bash
make setup-cpu
make lint
make format
make typecheck
make test
make check
```

The repository contains two Python packages:

- `whisperx-daemon`
- `transcript-postprocess`

The second is kept as an explicit dependency boundary so the text
post-processing logic remains reusable outside the daemon.

## Status

This project is production-shaped in several areas:

- explicit runtime layout
- deterministic file lifecycle
- structured failure reporting
- optional diarisation and post-processing
- reproducible CPU/CUDA bootstrap
- CI and quality tooling

It remains intentionally lightweight in others:

- no distributed scheduling
- no remote control plane
- no multi-worker coordination

## Licence

AGPL-3.0-or-later. See [`LICENSE`](./LICENSE).
