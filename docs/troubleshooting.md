# Troubleshooting

## `docker: failed to discover GPU vendor from CDI`

The host Docker installation is missing GPU container runtime support. Install
and configure the NVIDIA Container Toolkit, then retry `docker run --gpus all`.

## `WhisperX transcription failed: CUDA failed with error out of memory`

Reduce GPU memory pressure:

- lower `--batch-size`
- use a smaller WhisperX model
- split long recordings
- prefer `float16`
- fall back to CPU

## `Could not load libtorchcodec`

Check all of the following together:

- FFmpeg is installed and available
- `torch`, `torchaudio`, and `torchcodec` match the pinned versions
- `torchcodec` has not been upgraded above the supported range

## `module 'whisperx' has no attribute 'DiarizationPipeline'`

Use a current environment or a freshly rebuilt image. The repository supports
both top-level and submodule diarisation imports, but stale images can still
contain older code.

## Permission errors in bind-mounted Docker runtime directories

Run the container with:

```bash
--user "$(id -u):$(id -g)"
```

This avoids root-owned output files on the host.

## `Permission denied: '/home/whisperx/.pyannote/database.yml'`

This happens when the container runs as a host UID/GID that cannot write to the
image user's home directory. The current image derives writable runtime-scoped
cache and configuration paths under `<runtime-dir>/.container-state/` and no
longer pre-creates user-owned cache subdirectories in the image, so rebuild the
image and retry.

If you are using an older image, pass writable overrides explicitly:

```bash
-e HOME=/tmp/whisperx-home \
-e XDG_CACHE_HOME=/tmp/whisperx-cache \
-e XDG_CONFIG_HOME=/tmp/whisperx-config \
-e HF_HOME=/tmp/whisperx-huggingface \
-e TORCH_HOME=/tmp/whisperx-cache/torch \
-e MPLCONFIGDIR=/tmp/whisperx-matplotlib
```

## Matplotlib cache warnings under Docker

If Matplotlib warns that it cannot write to `/home/whisperx/.config`, you are
running an older image whose default config path is not writable for the chosen
UID/GID. Rebuild the image or pass `MPLCONFIGDIR` to a writable path.

## `Permission denied: '/tmp/whisperx-cache/torch'`

This usually means the image was built from an older Dockerfile that exported
cache paths during `docker build`, allowing root-owned cache directories to be
created in the image layer. Rebuild the image from the current repository and
retry. The current image creates Torch and Hugging Face cache directories only
at container start, using the actual runtime UID/GID.

## Pseudonymisation misses names

This feature depends on the selected NER model. If names are missed:

- try a different model with `--person-ner-model`
- verify that the text contains explicit person names rather than pronouns or
  indirect references
- remember that this is best-effort NER, not full coreference resolution

## `PCM input ended with a partial audio frame`

Stream mode expects signed 16-bit PCM, so every audio frame is exactly two
bytes. This error means the stream ended with an odd number of bytes or another
format was supplied accidentally.

Use an adapter command that enforces the stream contract:

```bash
ffmpeg -hide_banner -loglevel error \
  -i input.mp3 \
  -f s16le \
  -acodec pcm_s16le \
  -ac 1 \
  -ar 16000 \
  -
```

## `Stream diarisation requires stream recording to be enabled`

Stream diarisation is a final full-file pass. Keep stream recording enabled, or
remove `--diarize`. `--no-stream-recording` is only suitable when final
diarisation is not required.

## No live streaming events appear

Check:

- the command includes `--stream`
- Docker stream commands include `-i`
- the upstream producer is writing raw PCM data
- the window length is not too large for the amount of audio already received
- `runtime/output/<stream-id>.events.jsonl` is being tailed, not the final TXT
  file
