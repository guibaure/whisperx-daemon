# Getting Started

This guide takes a clean checkout to a first successful transcription.

## Prerequisites

- Python `3.11` or newer
- FFmpeg installed on the host
- enough free disk space for model caches, logs, outputs, and archives

Optional:

- NVIDIA GPU and compatible driver for CUDA execution
- NVIDIA Container Toolkit for CUDA inside Docker
- Hugging Face token for diarisation

## First CPU Run

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

After success:

- transcripts are written to `runtime/output`
- the original audio file moves to `runtime/archive/succeeded`
- the daemon records the job in `runtime/jobs.sqlite3`

If transcription fails:

- a structured failure report is written to `runtime/failed`
- the original audio file moves to `runtime/archive/failed`

## First CUDA Run

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

`float16` is the practical default on CUDA because it reduces VRAM pressure
significantly compared with full precision.

If you hit CUDA out-of-memory errors:

- lower `--batch-size`
- use a smaller model
- split long recordings
- fall back to CPU

## Continuous Watch Mode

Run without `--once` to keep scanning `runtime/input`:

```bash
python3 -m whisperx_daemon \
  --runtime-dir ./runtime \
  --model small \
  --device cpu \
  --compute-type int8
```

The daemon will keep polling for stable files and processing only newly
eligible inputs.
