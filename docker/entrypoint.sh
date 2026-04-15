#!/bin/sh

set -eu

runtime_dir="/app/runtime"
expect_runtime_dir_value="0"

for argument in "$@"; do
    if [ "$expect_runtime_dir_value" = "1" ]; then
        runtime_dir="$argument"
        expect_runtime_dir_value="0"
        continue
    fi

    case "$argument" in
        --runtime-dir)
            expect_runtime_dir_value="1"
            ;;
        --runtime-dir=*)
            runtime_dir=${argument#--runtime-dir=}
            ;;
    esac
done

container_state_dir=${WHISPERX_DAEMON_CONTAINER_STATE_DIR:-${runtime_dir}/.container-state}

export HOME=${WHISPERX_DAEMON_HOME:-${container_state_dir}/home}
export XDG_CACHE_HOME=${XDG_CACHE_HOME:-${container_state_dir}/cache}
export XDG_CONFIG_HOME=${XDG_CONFIG_HOME:-${container_state_dir}/config}
export HF_HOME=${HF_HOME:-${container_state_dir}/huggingface}
export MPLCONFIGDIR=${MPLCONFIGDIR:-${container_state_dir}/matplotlib}
export TORCH_HOME=${TORCH_HOME:-${XDG_CACHE_HOME}/torch}

mkdir -p \
    "$runtime_dir" \
    "$HOME" \
    "$XDG_CACHE_HOME" \
    "$XDG_CONFIG_HOME" \
    "$HF_HOME" \
    "$MPLCONFIGDIR" \
    "$TORCH_HOME"

exec python -m whisperx_daemon "$@"
