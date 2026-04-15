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
- `float16` is the practical CUDA default because it reduces VRAM pressure

The image entrypoint derives arbitrary-UID-safe runtime paths under
`<runtime-dir>/.container-state/`, so you do not need to pass `HOME`,
`XDG_CACHE_HOME`, `XDG_CONFIG_HOME`, `HF_HOME`, `TORCH_HOME`, or
`MPLCONFIGDIR` explicitly for the common bind-mounted runtime case.

This is deliberate. The image does not bake cache or config directories into
the filesystem at build time, because doing so creates root-owned paths in the
image layer and later breaks arbitrary host UID/GID execution. The runtime
entrypoint creates the writable directories only when the container starts,
under the identity that will actually execute the daemon.

If you need different locations, override them explicitly with environment
variables such as `WHISPERX_DAEMON_HOME`, `HF_HOME`, or `MPLCONFIGDIR`.

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
