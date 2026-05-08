# Usage

## Common CLI Examples

Run once on CPU:

```bash
uv run whisperx-daemon \
  --runtime-dir ./runtime \
  --once \
  --model small \
  --device cpu \
  --compute-type int8
```

Run continuously:

```bash
uv run whisperx-daemon \
  --runtime-dir ./runtime \
  --model small \
  --device cpu \
  --compute-type int8
```

Force reprocessing for previously recorded files:

```bash
uv run whisperx-daemon \
  --runtime-dir ./runtime \
  --once \
  --force-reprocess
```

Omit time ranges in TXT output:

```bash
uv run whisperx-daemon \
  --runtime-dir ./runtime \
  --once \
  --omit-txt-time-ranges
```

Omit speaker labels in TXT output:

```bash
uv run whisperx-daemon \
  --runtime-dir ./runtime \
  --once \
  --omit-txt-speaker-labels
```

Run on CUDA with lower batch size:

```bash
uv run whisperx-daemon \
  --runtime-dir ./runtime \
  --once \
  --model small \
  --device cuda \
  --compute-type float16 \
  --batch-size 4
```

Enable diarisation:

```bash
uv run whisperx-daemon \
  --runtime-dir ./runtime \
  --once \
  --diarize \
  --hf-token "$HF_TOKEN"
```

Enable diarisation with speaker-count hints:

```bash
uv run whisperx-daemon \
  --runtime-dir ./runtime \
  --once \
  --diarize \
  --hf-token "$HF_TOKEN" \
  --min-speakers 1 \
  --max-speakers 3
```

Enable pseudonymisation:

```bash
uv run whisperx-daemon \
  --runtime-dir ./runtime \
  --once \
  --pseudonymize-person-names
```

Use an explicit term-replacement file:

```bash
uv run whisperx-daemon \
  --runtime-dir ./runtime \
  --once \
  --term-replacements-file ./term-replacements.json
```

Run stream mode from a file adapted by `ffmpeg`:

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

Run stream mode from a named pipe:

```bash
mkfifo runtime/input.pcm

uv run whisperx-daemon \
  --stream \
  --runtime-dir ./runtime \
  --stream-input runtime/input.pcm \
  --stream-id named-pipe \
  --model small &

ffmpeg -hide_banner -loglevel error \
  -i input.mp3 \
  -f s16le \
  -acodec pcm_s16le \
  -ac 1 \
  -ar 16000 \
  runtime/input.pcm
```

Run stream mode with final diarisation:

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
    --stream-id diarised-stream \
    --model small \
    --device cuda \
    --compute-type float16 \
    --diarize \
    --hf-token "$HF_TOKEN"
```

In stream mode, live events are written to
`runtime/output/<stream-id>.events.jsonl`; final JSON and TXT outputs are
written after the stream closes.
