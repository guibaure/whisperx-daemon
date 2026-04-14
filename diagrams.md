<!-- Just before ## Idempotency And Reprocessing -->

### Architecture Diagram

```mermaid
graph LR
  subgraph CLI
    CLI["CLI / __main__"]
  end
  subgraph AppLayer
    App["app.run() / Runtime bootstrap"]
    Config["TranscriptionConfig / RuntimeLayout"]
  end
  subgraph Orchestration
    Watcher["WorkspaceWatcher"]
    Filesystem["filesystem helpers"]
    JobStore["JobStore (SQLite)"]
  end
  subgraph PipelineLayer
    Transcriber["WhisperXTranscriber"]
    WhisperX["whisperx (model)"]
    HF["transformers (NER/pseudonymise)"]
  end
  subgraph RuntimeFS["Runtime filesystem (runtime/)"]
    Input[input/]
    Processing[processing/]
    Output[output/]
    ArchiveSucc[archive/succeeded/]
    ArchiveFail[archive/failed/]
    Failed[failed/]
    Logs[logs/]
    StateDB[jobs.sqlite3]
  end

  CLI --> App
  App --> Orchestration["Orchestration"]
  App --> JobStore
  App --> RuntimeFS
  Watcher --> Filesystem
  Watcher --> Transcriber
  Transcriber --> WhisperX
  Transcriber --> HF
  JobStore --> StateDB
  Filesystem --> RuntimeFS
  Transcriber --> Output
  Filesystem --> Processing
  Filesystem --> ArchiveSucc
  Filesystem --> ArchiveFail
  Output --> Logs

  classDef comp fill:#f9f,stroke:#333,stroke-width:1px;
  class App,Watcher,Transcriber,JobStore comp;
```

### Processing Flow Chart

```mermaid
flowchart TD
  A[Scan runtime input/] --> B{Is file stable (age > stability_window)?}
  B -- No --> A
  B -- Yes --> C[Compute file digest]
  C --> D{Digest matches JobStore record?}
  D -- Yes --> E[Skip file (unchanged)]
  D -- No --> F[Move file -> processing/]
  F --> G[WhisperXTranscriber.transcribe_file]
  G --> H{Transcription success?}
  H -- Yes --> I[Write JSON + TXT to output/]
  I --> J[Move audio -> archive/succeeded/]
  J --> K[Upsert job (completed) in JobStore]
  H -- No --> L[Write failure report to failed/]
  L --> M[Move audio -> archive/failed/]
  M --> N[Upsert job (failed_transcription) in JobStore]
  K --> A
  N --> A

  style A fill:#f8f8ff,stroke:#333,stroke-width:1px
  style G fill:#fff2cc
  style I fill:#d4f4dd
  style L fill:#f8d7da
```
