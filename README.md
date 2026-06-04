# WhisperX Daemon

`whisperx-daemon` is a local-first audio transcription daemon built around
WhisperX. It watches a managed runtime directory, transcribes stable audio
files, writes JSON and plain-text outputs, archives the original inputs, and
records job state so unchanged files are not reprocessed accidentally.

It is designed as a production-oriented single-node service baseline, not as a
distributed platform. The project is managed with
[uv](https://docs.astral.sh/uv/): dependencies are declared in
`pyproject.toml`, resolved in `uv.lock`, and synchronised with `uv sync`.

## Why `whisperx-daemon`

`whisperx-daemon` is not just a thin wrapper around WhisperX. It adds the
operational, privacy-oriented, and workflow features that upstream WhisperX
does not provide out of the box.

| Highlight | What `whisperx-daemon` adds beyond WhisperX |
|---|---|
| Pseudonymisation | Detects explicit person-name mentions and rewrites them to deterministic pseudonyms |
| Anonymisation-oriented post-processing | Supports privacy-oriented transcript sanitisation workflows, while remaining explicit that this is not a formal anonymisation guarantee |
| Proper-noun replacement | Rewrites configured sensitive terms after pseudonymisation with longest-match handling |
| Streaming transcription | Consumes raw PCM streams from stdin or pipes and emits live JSONL events plus final JSON/TXT outputs |
| Managed runtime workflow | Watches `runtime/input`, processes stable files, writes outputs, and archives originals |
| Idempotent processing | Tracks path and digest in SQLite so unchanged files are not reprocessed accidentally |
| Production-shaped outputs | Writes structured JSON, readable TXT, and structured failure reports |
| Continuous daemon mode | Runs once or continuously instead of only acting as a one-shot transcription script |
| Docker/runtime hardening | Supports CPU or CUDA execution, bind-mounted runtimes, and arbitrary host UID/GID mapping |
| Reusable post-processing package | Consumes `textformer` as an external sibling repository or released dependency for standalone sanitisation workflows |

## Privacy Features

The main project-specific extension over WhisperX is transcript sanitisation.

- `Pseudonymisation`: replaces detected explicit person names with stable pseudonyms inside one document
- `Anonymisation-oriented processing`: supports privacy-oriented transcript rewriting, but should not be treated as a legal or formal anonymisation guarantee
- `Term replacement`: rewrites configured proper nouns such as organisation names, product names, or internal project names
- `Standalone reuse`: the same sanitisation logic is available outside the daemon through the separately maintained `textformer` repository

## Prerequisites

| Dependency | Install |
|---|---|
| [uv](https://docs.astral.sh/uv/) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Python 3.11 to 3.13 | via `uv python install 3.11` or [python.org](https://www.python.org) |
| FFmpeg | `apt install ffmpeg` / `brew install ffmpeg` |

Optional: NVIDIA GPU + driver for CUDA, NVIDIA Container Toolkit for Docker
GPU passthrough, Hugging Face token for diarisation.

## Quick Start

### CPU

```bash
make setup-cpu

mkdir -p runtime/input
cp /path/to/example.mp3 runtime/input/

uv run whisperx-daemon \
  --runtime-dir ./runtime \
  --once \
  --model small \
  --device cpu \
  --compute-type int8
```

### CUDA

```bash
make setup-cuda

mkdir -p runtime/input
cp /path/to/example.mp3 runtime/input/

uv run whisperx-daemon \
  --runtime-dir ./runtime \
  --once \
  --model small \
  --device cuda \
  --compute-type float16
```

### Docker

Docker builds require the `textformer` dependency source to be reachable inside
the build context. While local development uses the sibling `../textformer`
source override, build from a released/tagged dependency or an explicit
parent-context workflow before relying on the image path.

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

### Streaming

```bash
ffmpeg -hide_banner -loglevel error \
  -i example.mp3 \
  -f s16le \
  -acodec pcm_s16le \
  -ac 1 \
  -ar 16000 \
  - \
| uv run whisperx-daemon \
    --stream \
    --runtime-dir ./runtime \
    --stream-id example-live \
    --model small \
    --device cpu \
    --compute-type int8
```

Stream mode accepts raw mono `s16le` PCM, emits JSONL live events, and writes
the same final JSON/TXT transcript formats as file mode. See
[`docs/streaming.md`](./docs/streaming.md) for the full contract.

## Development

```bash
make setup-cpu    # or make setup-cuda
make check        # lint + format-check + typecheck + test
make coverage     # test suite with branch coverage enforcement
make docker-smoke # disposable Docker build/run smoke test
```

Individual targets: `make lint`, `make format`, `make typecheck`, `make test`,
`make coverage`, `make docker-smoke`.

The local development layout uses two Python packages:

| Package | Purpose |
|---|---|
| `whisperx-daemon` | Daemon: runtime lifecycle, transcription pipeline, CLI |
| `textformer` | External reusable text pseudonymisation and term replacement package |

The second is kept outside this repository as an explicit dependency boundary
so the text post-processing logic remains reusable outside the daemon.

`make setup-cpu` and `make setup-cuda` select mutually exclusive `uv` extras.
This is intentional: CPU and CUDA PyTorch wheels are different runtime
variants and should not be mixed in the same environment.

## Documentation

| Guide | Description |
|---|---|
| [Getting Started](./docs/getting-started.md) | Zero-to-first-run for CPU, CUDA, and watch mode |
| [Installation](./docs/installation.md) | Dependency pinning, local bootstrap, package layout |
| [Usage](./docs/usage.md) | Common CLI workflows and operational examples |
| [Streaming](./docs/streaming.md) | Raw PCM stream input, JSONL events, and final stream outputs |
| [Configuration](./docs/configuration.md) | Runtime directory contract, lifecycle, flag reference |
| [Output](./docs/output.md) | JSON, TXT, and failure-report contracts |
| [Post-Processing](./docs/post-processing.md) | Pseudonymisation, term replacement, standalone usage |
| [Docker](./docs/docker.md) | Build, CPU/CUDA execution, GPU, entrypoint override |
| [Architecture](./docs/architecture.md) | Module responsibilities and processing flow |
| [Strategy Memo](./STRATEGY.md) | Current state, risks, remaining hardening work, recommended next steps |
| [Troubleshooting](./docs/troubleshooting.md) | Common runtime and environment failures |

## Licence

AGPL-3.0-or-later. See [`LICENSE`](./LICENSE).
