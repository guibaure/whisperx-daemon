# WhisperX Daemon

`whisperx-daemon` is a local-first audio transcription daemon built around
WhisperX. It watches a managed runtime directory, transcribes stable audio
files, writes JSON and plain-text outputs, archives the original inputs, and
records job state so unchanged files are not reprocessed accidentally.

It is designed as a production-oriented single-node service baseline, not as a
distributed platform. The project uses [uv](https://docs.astral.sh/uv/) for
fast dependency management and virtual environment creation.

## Prerequisites

| Dependency | Install |
|---|---|
| [uv](https://docs.astral.sh/uv/) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Python 3.11+ | via system package manager or [python.org](https://www.python.org) |
| FFmpeg | `apt install ffmpeg` / `brew install ffmpeg` |

Optional: NVIDIA GPU + driver for CUDA, NVIDIA Container Toolkit for Docker
GPU passthrough, Hugging Face token for diarisation.

## Quick Start

### CPU

```bash
make setup-cpu
. .venv/bin/activate

mkdir -p runtime/input
cp /path/to/example.mp3 runtime/input/

python3 -m whisperx_daemon \
  --runtime-dir ./runtime \
  --once \
  --model small \
  --device cpu \
  --compute-type int8
```

### CUDA

```bash
make setup-cuda
. .venv/bin/activate

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

For CUDA containers add `--gpus all` and
`--user "$(id -u):$(id -g)"` to prevent root-owned files. See
[`docs/docker.md`](./docs/docker.md) for full details.

## Development

```bash
make setup-cpu    # or make setup-cuda
make check        # lint + format-check + typecheck + test
```

Individual targets: `make lint`, `make format`, `make typecheck`, `make test`.

The repository contains two Python packages:

| Package | Purpose |
|---|---|
| `whisperx-daemon` | Daemon: runtime lifecycle, transcription pipeline, CLI |
| `transcript-postprocess` | Reusable text pseudonymisation and term replacement |

The second is kept as an explicit dependency boundary so the text
post-processing logic remains reusable outside the daemon.

## Documentation

| Guide | Description |
|---|---|
| [Getting Started](./docs/getting-started.md) | Zero-to-first-run for CPU, CUDA, and watch mode |
| [Installation](./docs/installation.md) | Dependency pinning, local bootstrap, package layout |
| [Usage](./docs/usage.md) | Common CLI workflows and operational examples |
| [Configuration](./docs/configuration.md) | Runtime directory contract, lifecycle, flag reference |
| [Output](./docs/output.md) | JSON, TXT, and failure-report contracts |
| [Post-Processing](./docs/post-processing.md) | Pseudonymisation, term replacement, standalone usage |
| [Docker](./docs/docker.md) | Build, CPU/CUDA execution, GPU, entrypoint override |
| [Architecture](./docs/architecture.md) | Module responsibilities and processing flow |
| [Troubleshooting](./docs/troubleshooting.md) | Common runtime and environment failures |

## Licence

AGPL-3.0-or-later. See [`LICENSE`](./LICENSE).
