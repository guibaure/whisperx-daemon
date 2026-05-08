# Streaming Mode

Streaming mode transcribes a raw audio stream instead of watching
`runtime/input`. It is designed for UNIX-style pipelines: external tools adapt
microphones, files, sockets, or capture devices into a stable PCM contract, and
`whisperx-daemon` consumes that stream from stdin or a named pipe.

## Input Contract

The daemon accepts:

- signed 16-bit PCM (`s16le`)
- mono audio
- 16 kHz sample rate by default
- stdin by default, or a path passed with `--stream-input`

The daemon intentionally does not open sound devices directly. This keeps the
service portable, testable, and free from device-specific dependencies.

## File-To-Stream Example

```bash
ffmpeg -hide_banner -loglevel error \
  -i input.mp3 \
  -f s16le \
  -acodec pcm_s16le \
  -ac 1 \
  -ar 16000 \
  - \
| uv run whisperx-daemon \
    --stream \
    --runtime-dir ./runtime \
    --stream-id input-live \
    --model small \
    --device cpu \
    --compute-type int8
```

## Microphone Example

On Linux, `arecord` can provide the required PCM stream:

```bash
arecord -f S16_LE -r 16000 -c 1 \
| uv run whisperx-daemon \
    --stream \
    --runtime-dir ./runtime \
    --stream-id microphone \
    --model small \
    --device cuda \
    --compute-type float16
```

## Docker Example

Docker stream mode requires interactive stdin (`-i`):

```bash
ffmpeg -hide_banner -loglevel error \
  -i input.mp3 \
  -f s16le \
  -acodec pcm_s16le \
  -ac 1 \
  -ar 16000 \
  - \
| docker run --rm -i \
    -v "$(pwd)/runtime:/app/runtime" \
    whisperx-daemon:latest \
    --stream \
    --runtime-dir /app/runtime \
    --stream-id input-live \
    --model small \
    --device cpu \
    --compute-type int8
```

For CUDA, add Docker GPU flags and use the same runtime ownership guidance as
file mode:

```bash
ffmpeg -hide_banner -loglevel error \
  -i input.mp3 \
  -f s16le \
  -acodec pcm_s16le \
  -ac 1 \
  -ar 16000 \
  - \
| docker run --rm -i --gpus all \
    --user "$(id -u):$(id -g)" \
    -v "$(pwd)/runtime:/app/runtime" \
    whisperx-daemon:latest \
    --stream \
    --runtime-dir /app/runtime \
    --stream-id input-live \
    --model small \
    --device cuda \
    --compute-type float16
```

## Stream Windowing

The stream is processed through overlapping windows:

- `--stream-window-seconds`: length of each transcription window
- `--stream-step-seconds`: distance between successive windows
- `--stream-commit-overlap-seconds`: trailing overlap kept uncommitted until a
  later window confirms it

This avoids emitting unstable text from the end of a window too early. Live
events are therefore incremental, while the final JSON and TXT artefacts are the
authoritative outputs.

## Outputs

For `--stream-id meeting`, stream mode writes:

- `runtime/output/meeting.events.jsonl`
- `runtime/output/meeting.json`
- `runtime/output/meeting.txt`
- `runtime/archive/succeeded/meeting.wav` when recording is enabled

If the stream id contains characters that are unsafe or awkward in filenames,
the daemon replaces them with underscores for artefact names while preserving
the original stream id inside JSON events and the final transcript metadata.

The JSONL event stream contains:

- `stream_started`
- `segment_final`
- `stream_completed`
- `stream_failed` on error

The final JSON schema is the same top-level schema as file mode:

- `source_path`
- `generated_at`
- `status`
- `text`
- `language`
- `segments`
- `speakers`

## Diarisation

Live diarisation is not currently performed. When `--diarize` is enabled,
stream mode records the incoming PCM stream as WAV and runs the normal full-file
WhisperX diarisation pipeline after stdin closes. This is slower, but it keeps
speaker labelling consistent with file mode and avoids pretending that pyannote
is being used as a real-time diarisation engine.

Because final diarisation requires the WAV recording, `--diarize` is
incompatible with `--no-stream-recording`.

## Post-Processing

Final stream outputs support the same post-processing flags as file mode:

- `--pseudonymize-person-names`
- `--person-ner-model`
- `--term-replacements-file`
- `--omit-txt-time-ranges`
- `--omit-txt-speaker-labels`

Pseudonymisation and term replacement apply to the final JSON and TXT outputs.
Live `segment_final` events are operational events and should not be treated as
the final privacy-reviewed transcript.

## Failure Handling

On failure, stream mode writes:

- `runtime/failed/<stream-id>.error.json`
- `runtime/output/<stream-id>.events.jsonl` with a final `stream_failed` event
- `runtime/archive/failed/<stream-id>.wav` when recording is enabled

Common causes are invalid PCM input, partial final audio frames, missing
WhisperX dependencies, insufficient GPU memory, and diarisation without a
Hugging Face token.
