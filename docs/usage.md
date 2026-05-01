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
