# Output Contract

Each successful input produces two artefacts in `runtime/output`:

- `<name>.json`
- `<name>.txt`

Stream mode also writes `<stream-id>.events.jsonl` while the stream is running.
The final `<stream-id>.json` and `<stream-id>.txt` files are written after the
stream closes.

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

## Streaming Event Output

Streaming events are newline-delimited JSON records so operators can tail them
while a stream is active:

```json
{
  "stream_id": "meeting",
  "event": "segment_final",
  "generated_at": "2026-04-14T19:30:00+00:00",
  "payload": {
    "language": "en",
    "segment": {
      "id": 0,
      "start": 0.0,
      "end": 2.5,
      "text": "Hello world"
    }
  }
}
```

Supported event names:

- `stream_started`
- `segment_final`
- `stream_completed`
- `stream_failed`

JSONL events are live operational artefacts. The final JSON and TXT transcript
files remain the authoritative outputs, especially when diarisation or
post-processing is enabled.
