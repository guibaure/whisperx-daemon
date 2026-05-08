# Architecture

## Repository Structure

```text
.
├── src/whisperx_daemon/
│   daemon package
├── packages/transcript-postprocess/
│   reusable text post-processing package
├── tests/
│   repository tests
├── Dockerfile
├── Makefile
└── .github/workflows/ci.yml
```

## Module Responsibilities

- `cli.py`
  Argument parsing and environment fallback.
- `app.py`
  Runtime bootstrap, logging configuration, and watcher construction.
- `config.py`
  `TranscriptionConfig`, `StreamingConfig`, and `RuntimeLayout`.
- `watcher.py`
  Polling loop, lifecycle handling, and per-file orchestration.
- `streaming.py`
  Raw PCM stream ingestion, overlapping windowing, live JSONL events, final
  stream output orchestration, and stream recording archival.
- `filesystem.py`
  Runtime directory creation, digest computation, and file moves.
- `state.py`
  SQLite-backed idempotency store.
- `pipeline.py`
  WhisperX integration, alignment, diarisation, post-processing, and output
  shaping.
- `packages/transcript-postprocess`
  Reusable pseudonymisation and configured term replacement.

## Processing Flow

```text
input scan
  -> stability check
  -> digest computation
  -> idempotency lookup
  -> move to processing
  -> WhisperX transcription
  -> alignment
  -> optional diarisation
  -> optional pseudonymisation
  -> optional term replacement
  -> write outputs
  -> archive input
  -> update SQLite state
```

## Streaming Flow

```text
stdin or stream input path
  -> PCM frame validation
  -> overlapping window buffer
  -> reusable WhisperX model session
  -> alignment per window
  -> stable segment commit
  -> JSONL event emission
  -> final JSON/TXT output
  -> optional final full-file diarisation
  -> archive stream recording
```

File mode and stream mode share the same transcription adapter and output
formatters. They deliberately keep separate orchestration paths because stable
file processing and indefinite stream processing have different lifecycle and
failure semantics.

## Design Intent

The codebase is intentionally narrow and explicit:

- configuration is separated from orchestration
- filesystem I/O is separated from business rules
- WhisperX integration is isolated in one layer
- text post-processing lives behind its own package boundary

This keeps the daemon maintainable and allows the reusable text-processing
logic to evolve independently.
