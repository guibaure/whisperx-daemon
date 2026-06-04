# Docker

## Build

The provided image is CUDA-oriented, but it can still run in CPU mode.
The image uses the repository `uv.lock` during build, so container dependency
resolution follows the same lockfile as local development and CI.

Current local development uses the sibling source dependency
`../textformer`. A plain daemon-only Docker build context cannot contain that
parent-directory dependency, so Docker builds are blocked until one of these is
true:

- `textformer` is consumed from a released package or immutable Git tag; or
- the Docker build is redesigned to use a parent build context that explicitly
  includes both sibling repositories.

```bash
docker build -t whisperx-daemon:latest .
```

Run this command only after the dependency source is reachable inside the
container build context. Otherwise `uv sync --frozen` fails while resolving
`file:///textformer`.

For development validation, use the disposable smoke-test target:

```bash
make docker-smoke
```

The smoke test builds `whisperx-daemon:test`, runs short-lived test containers,
checks the CLI and entrypoint override paths, runs an empty CPU-mode daemon
pass against a bind-mounted runtime directory, and removes the test image and
containers when it exits. To include a CUDA availability check, run:

```bash
WHISPERX_DAEMON_DOCKER_TEST_GPU=1 make docker-smoke
```

The CUDA smoke path first checks `nvidia-smi`, then checks PyTorch CUDA
initialisation. If `nvidia-smi` works but PyTorch reports CUDA as unavailable,
inspect the host NVIDIA Container Toolkit configuration. In particular,
`NVIDIA_VISIBLE_DEVICES=void` inside the container indicates a host runtime
injection problem rather than a daemon CLI problem.

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
