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
  `TranscriptionConfig` and `RuntimeLayout`.
- `watcher.py`
  Polling loop, lifecycle handling, and per-file orchestration.
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

## Design Intent

The codebase is intentionally narrow and explicit:

- configuration is separated from orchestration
- filesystem I/O is separated from business rules
- WhisperX integration is isolated in one layer
- text post-processing lives behind its own package boundary

This keeps the daemon maintainable and allows the reusable text-processing
logic to evolve independently.
