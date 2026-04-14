# Docker

## Build

The provided image is CUDA-oriented, but it can still run in CPU mode.

```bash
docker build -t whisperx-daemon:latest .
```

## CPU Run

```bash
docker run --rm \
  -v "$(pwd)/runtime:/app/runtime" \
  whisperx-daemon:latest \
  --runtime-dir /app/runtime \
  --once \
  --model small \
  --device cpu \
  --compute-type int8
```

## CUDA Run

GPU access inside the container requires the NVIDIA Container Toolkit on the
host. Without it, `docker run --gpus all` cannot expose the host GPU runtime to
the container.

Recommended bind-mount invocation:

```bash
docker run --rm --gpus all \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -e XDG_CACHE_HOME=/tmp/.cache \
  -e HF_HOME=/tmp/.cache/huggingface \
  -e TRANSFORMERS_CACHE=/tmp/.cache/huggingface/transformers \
  -v "$(pwd)/runtime:/app/runtime" \
  whisperx-daemon:latest \
  --runtime-dir /app/runtime \
  --once \
  --model small \
  --device cuda \
  --compute-type float16
```

Why these options matter:

- `--user "$(id -u):$(id -g)"` prevents root-owned files in bind-mounted
  runtime directories
- temporary cache environment variables keep model caches writable inside the
  container
- `float16` is the practical CUDA default because it reduces VRAM pressure

## Entrypoint Override

The image entrypoint is `python -m whisperx_daemon`.

To open a shell:

```bash
docker run --rm -it --entrypoint sh whisperx-daemon:latest
```

To run a different Python command:

```bash
docker run --rm --entrypoint python whisperx-daemon:latest -m whisperx_daemon --help
```

Without `--entrypoint`, extra trailing arguments are interpreted as daemon CLI
arguments, not as shell commands.
