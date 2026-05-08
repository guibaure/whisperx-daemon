#!/bin/sh

set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

IMAGE_TAG=${WHISPERX_DAEMON_DOCKER_TEST_IMAGE:-whisperx-daemon:test}
RUNTIME_DIR=${WHISPERX_DAEMON_DOCKER_TEST_RUNTIME_DIR:-.docker-smoke-runtime}
RUN_GPU_CHECK=${WHISPERX_DAEMON_DOCKER_TEST_GPU:-0}
KEEP_IMAGE=${WHISPERX_DAEMON_KEEP_DOCKER_TEST_IMAGE:-0}

case "$IMAGE_TAG" in
    *:test)
        ;;
    *)
        printf '%s\n' "Refusing to use non-test Docker image tag: $IMAGE_TAG" >&2
        exit 2
        ;;
esac

case "$RUNTIME_DIR" in
    /*)
        runtime_path=$RUNTIME_DIR
        ;;
    *)
        runtime_path=$PROJECT_ROOT/$RUNTIME_DIR
        ;;
esac

case "$runtime_path" in
    "$PROJECT_ROOT"/*)
        ;;
    *)
        printf '%s\n' "Refusing to use runtime path outside the repository: $runtime_path" >&2
        exit 2
        ;;
esac

HELP_CONTAINER=whisperx-daemon-test-help
ENTRYPOINT_CONTAINER=whisperx-daemon-test-entrypoint
CPU_CONTAINER=whisperx-daemon-test-cpu
GPU_CONTAINER=whisperx-daemon-test-gpu

cleanup() {
    docker rm -f \
        "$HELP_CONTAINER" \
        "$ENTRYPOINT_CONTAINER" \
        "$CPU_CONTAINER" \
        "$GPU_CONTAINER" >/dev/null 2>&1 || true

    rm -rf "$runtime_path"

    if [ "$KEEP_IMAGE" != "1" ]; then
        docker image rm "$IMAGE_TAG" >/dev/null 2>&1 || true
    fi
}

trap cleanup EXIT INT TERM

cleanup
mkdir -p "$runtime_path/input"

docker build -t "$IMAGE_TAG" "$PROJECT_ROOT"

docker run --rm --name "$HELP_CONTAINER" "$IMAGE_TAG" --help >/dev/null

docker run \
    --rm \
    --name "$ENTRYPOINT_CONTAINER" \
    --entrypoint python \
    "$IMAGE_TAG" \
    -m whisperx_daemon --help >/dev/null

docker run \
    --rm \
    --name "$CPU_CONTAINER" \
    --user "$(id -u):$(id -g)" \
    -v "$runtime_path:/app/runtime" \
    "$IMAGE_TAG" \
    --runtime-dir /app/runtime \
    --once \
    --model small \
    --device cpu \
    --compute-type int8 >/dev/null

test -d "$runtime_path/.container-state"
test -d "$runtime_path/input"

if [ "$RUN_GPU_CHECK" = "1" ]; then
    docker run \
        --rm \
        --gpus all \
        --name "$GPU_CONTAINER" \
        --entrypoint python \
        "$IMAGE_TAG" \
        -c 'import torch; raise SystemExit(0 if torch.cuda.is_available() else 1)'
fi

printf '%s\n' "Docker smoke validation passed for $IMAGE_TAG"
