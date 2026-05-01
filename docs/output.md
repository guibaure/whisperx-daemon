# Output Contract

Each successful input produces two artefacts in `runtime/output`:

- `<name>.json`
- `<name>.txt`

## JSON Output

The top-level JSON schema is intentionally small and stable:

- `source_path`
- `generated_at`
- `status`
- `text`
- `language`
- `segments`
- `speakers`

Representative shape:

```json
{
  "source_path": "/abs/path/example.mp3",
  "generated_at": "2026-04-14T19:30:00+00:00",
  "status": "completed",
  "text": "Full transcript text",
  "language": "en",
  "segments": [
    {
      "id": 0,
      "start": 0.123,
      "end": 3.456,
      "speaker": "SPEAKER_00",
      "text": "Hello world"
    }
  ],
  "speakers": [
    {
      "label": "SPEAKER_00"
    }
  ]
}
```

## Plain-Text Output

Default format:

```text
[<start>:<end>] <speaker>: <text>
```

Example:

```text
[0.123:3.456] SPEAKER_00: Hello world
```

If diarisation did not assign a speaker, TXT output falls back to `UNKNOWN`.

When `--omit-txt-time-ranges` is enabled:

```text
<speaker>: <text>
```

When `--omit-txt-speaker-labels` is enabled, the speaker prefix is replaced by
a dialogue dash while the JSON speaker metadata remains unchanged:

```text
[<start>:<end>] - <text>
```

When both `--omit-txt-time-ranges` and `--omit-txt-speaker-labels` are enabled:

```text
- <text>
```

## Failure Output

Each failed input produces `<name>.error.json` in `runtime/failed`:

```json
{
  "source_path": "/abs/path/example.mp3",
  "generated_at": "2026-04-14T19:30:00+00:00",
  "status": "failed",
  "error": "WhisperX transcription failed: ..."
}
```
