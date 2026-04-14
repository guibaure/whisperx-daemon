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

## Pseudonymisation misses names

This feature depends on the selected NER model. If names are missed:

- try a different model with `--person-ner-model`
- verify that the text contains explicit person names rather than pronouns or
  indirect references
- remember that this is best-effort NER, not full coreference resolution
