# Configuration

## Runtime Directory Contract

Given `--runtime-dir ./runtime`, the daemon manages:

```text
runtime/
├── input/
├── processing/
├── archive/
│   ├── succeeded/
│   └── failed/
├── output/
├── failed/
├── logs/
├── jobs.sqlite3
└── term-replacements.json
```

Purpose:

- `input/`: stable candidate audio files
- `processing/`: files currently being transcribed
- `archive/succeeded/`: archived original inputs after success
- `archive/failed/`: archived original inputs after failure
- `output/`: generated transcript artefacts only
- `failed/`: structured failure reports only
- `logs/`: daemon log output
- `jobs.sqlite3`: SQLite-backed job state
- `term-replacements.json`: optional default replacement map

## Processing Lifecycle

For each stable candidate:

1. scan `runtime/input`
2. apply the stability window check
3. compute SHA-256 digest
4. compare with stored record for the same source path
5. skip unchanged files unless `--force-reprocess` is set
6. move file to `processing`
7. transcribe
8. align if language is known
9. optionally diarise
10. optionally pseudonymise names
11. optionally replace configured terms
12. write outputs
13. archive source audio
14. update SQLite state

Successful path:

```text
input -> processing -> output + archive/succeeded
```

Failure path:

```text
input -> processing -> failed + archive/failed
```

Stream mode uses the same runtime root but does not scan `input/`. It consumes
stdin or `--stream-input`, writes live events and final transcripts to
`output/`, records the incoming PCM stream as a WAV file in `processing/`, and
archives that recording under `archive/succeeded/` or `archive/failed/`.

## Idempotency

The unchanged-file check uses:

- source path
- SHA-256 digest of file contents

Consequences:

- same path and same bytes: skipped
- same path and changed bytes: reprocessed
- different path and same bytes: treated as new
- `--force-reprocess`: bypasses the unchanged-file skip

The stability window only decides whether a file is old enough to process
safely. It does not determine whether a file changed.

## CLI Flag Reference

### Runtime Control

- `--runtime-dir PATH`
  Managed runtime root. Default: `./runtime`.
- `--poll-interval SECONDS`
  Poll interval for watch mode. Default: `2.0`.
- `--stability-window SECONDS`
  Minimum file age before processing. Default: `1.0`.
- `--once`
  Process the current queue once and exit.
- `--force-reprocess`
  Reprocess files even when the recorded path and digest match.

### Streaming Control

- `--stream`
  Consume raw PCM audio from stdin or `--stream-input` instead of watching
  `runtime/input`.
- `--stream-input PATH`
  Raw PCM stream input path. Use `-` or omit the flag to read from stdin.
- `--stream-id ID`
  Stable identifier used for stream output filenames and JSONL events.
  Default: `stream`.
- `--stream-sample-rate INTEGER`
  Raw PCM sample rate in Hz. Default: `16000`.
- `--stream-window-seconds SECONDS`
  Length of each transcription window. Default: `30.0`.
- `--stream-step-seconds SECONDS`
  Distance between successive transcription windows. Default: `5.0`.
- `--stream-commit-overlap-seconds SECONDS`
  Trailing overlap kept uncommitted until a later window. Default: `2.0`.
- `--no-stream-recording`
  Disable WAV archival of the incoming stream. This cannot be used with
  `--diarize`, because final diarisation requires the recorded WAV.

### WhisperX Configuration

- `--model NAME`
  WhisperX model name. Default: `small`.
- `--device DEVICE`
  Execution device, typically `cpu` or `cuda`. Default: `cpu`.
- `--language CODE`
  Optional language override.
- `--compute-type VALUE`
  WhisperX compute type. Default: `int8`.
- `--batch-size INTEGER`
  Transcription batch size. Default: `8`.
- `--diarize`
  Enable speaker diarisation.
- `--hf-token TOKEN`
  Hugging Face token. Falls back to `HF_TOKEN` then `HUGGINGFACE_TOKEN`.
- `--min-speakers INTEGER`
  Optional diarisation hint.
- `--max-speakers INTEGER`
  Optional diarisation hint.

### Post-Processing Configuration

- `--pseudonymize-person-names`
  Enable NER-based person-name pseudonymisation.
- `--person-ner-model MODEL`
  Hugging Face NER model. Default: `Davlan/xlm-roberta-base-ner-hrl`.
- `--term-replacements-file PATH`
  Optional JSON file for configured proper-noun replacement. If omitted, the
  daemon uses `runtime/term-replacements.json` when present.
- `--omit-txt-time-ranges`
  Write TXT output without `[start:end]` prefixes.
- `--omit-txt-speaker-labels`
  Write TXT output with `-` instead of speaker labels such as `SPEAKER_00:`.
