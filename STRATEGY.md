# Strategy Memo

## 1. Project intent

### Executive summary

#### Original purpose

`whisperx-daemon` exists to turn WhisperX into a local-first operational service
for transcription workflows. The repository adds runtime management, output
contracts, idempotent processing, Docker support, and privacy-oriented
post-processing that upstream WhisperX does not provide directly.

#### Current state

The repository already has a coherent layered architecture, a reusable
post-processing package, repository-wide tests, branch coverage enforcement,
basic mypy coverage, Docker build and smoke validation, and GitHub Actions CI.
It is stronger than a prototype, but it is not yet fully hardened from a
governance, security, provenance, observability, privacy-operations, and
recovery perspective.

#### Main achievements

- Established a single-node daemon architecture around a managed runtime tree.
- Added streaming transcription with live JSONL events and final artefacts.
- Separated reusable transcript sanitisation into `transcript-postprocess`.
- Standardised development and packaging on `uv`.
- Added quality, test, coverage, package-build, and Docker-build CI jobs.
- Added Docker smoke validation and complete branch coverage enforcement.

#### Main remaining work

- Create and maintain project-level governance and hardening documentation.
- Expand type-checking into the highest-risk integration modules.
- Add security, dependency, secret, and supply-chain scanning gates.
- Define privacy, retention, observability, and recovery operating procedures.
- Add stronger real-environment validation beyond the current optional path.

#### Main risks

- Core WhisperX integration modules are not yet fully type-checked.
- CI does not yet prove security posture, container provenance, or SBOM output.
- Operational privacy controls are described in parts, but not consolidated.
- Real-runtime validation depends on optional caller-provided fixtures.
- Recovery behaviour is only partially documented and needs explicit drills.

#### Overall assessment

The project is on a credible engineering trajectory and already demonstrates
disciplined structure. The largest gap is operational hardening around the
existing baseline rather than missing core functionality.

#### Success criteria

The project should be considered substantially hardened when:

- governance and current-state documentation are maintained;
- critical modules are type-checked or have narrow, justified boundaries;
- CI enforces security and supply-chain controls;
- privacy and retention operations are explicit;
- real-environment smoke validation is reproducible;
- observability and recovery procedures are documented and tested.

## 2. Explicit facts

The following points are directly supported by repository contents as of
2026-06-03:

- The repository contains two Python packages: `whisperx-daemon` and
  `transcript-postprocess`.
- The root package uses `src/whisperx_daemon/` and the reusable package lives in
  `packages/transcript-postprocess/`.
- The runtime contract includes `input`, `processing`, `archive/succeeded`,
  `archive/failed`, `output`, `failed`, `logs`, `jobs.sqlite3`, and
  `term-replacements.json`.
- File mode watches a runtime directory and uses SQLite-backed idempotency.
- Stream mode consumes raw PCM, emits JSONL events, and writes final JSON/TXT
  outputs.
- The daemon supports optional diarisation and optional person-name
  pseudonymisation plus configured term replacement.
- The repository uses `uv`, a lockfile (`uv.lock`), a `Makefile`, Ruff, mypy,
  and coverage with `fail_under = 100`.
- CI currently runs test, quality, coverage, package-build, and Docker-build
  jobs.
- The Docker image is CUDA-oriented but can run CPU mode.
- The Docker smoke path exists and has optional GPU diagnostics.
- `tests/test_e2e.py` provides an optional real-runtime test path gated by
  environment variables.
- The current mypy scope excludes `src/whisperx_daemon/pipeline.py` and
  `packages/transcript-postprocess/src/transcript_postprocess/core.py`.
- No repository file currently defines dedicated CI jobs for security scanning,
  image scanning, SBOM generation, provenance, privacy operations,
  observability, or recovery drills.

## 3. Reasonable inferences

These points are inferred from repository evidence and should be treated as
working assumptions until validated against maintainer intent:

- The project intent has expanded from a basic transcription wrapper into a
  production-shaped local operational service.
- Streaming support appears to have been a later capability rather than an
  original baseline because the commit history shows a distinct sequence of
  streaming-related feature commits.
- The reusable `transcript-postprocess` package is intended as a deliberate
  boundary for eventual independent reuse or extraction.
- The current engineering direction prioritises maintainability and explicit
  contracts over framework-heavy expansion.
- The next phase of work should focus on governance and hardening rather than
  major architectural change.

## 4. Development trajectory

### Major phases

1. Baseline daemon and packaging work.
2. Dependency-management consolidation around `uv`.
3. Streaming ingestion, events, and runtime documentation.
4. Quality hardening through Docker smoke, coverage policy, and full branch
   coverage enforcement.

### Evidence of evolution

- Early-to-middle history shows migration from requirements-style dependency
  management to `pyproject.toml` plus `uv`.
- Middle history shows work on CPU/GPU dependency separation and Docker
  packaging behaviour.
- Later history shows a concentrated streaming workstream.
- The most recent commits focus on validation: Docker smoke, GPU diagnostics,
  coverage policy, and complete coverage.

### Scope changes and deferred work

- Scope expanded from file-based daemon behaviour to live streaming.
- Privacy-oriented transcript rewriting became a first-class project feature.
- Operational hardening controls appear intentionally deferred rather than
  rejected; there is currently no evidence of completed security, provenance,
  observability, or recovery workstreams.

## 5. Current architecture

The repository already follows a layered, explicit structure:

- Interface layer: `cli.py`, `__main__.py`, Docker entrypoint behaviour, stream
  stdin contract.
- Application layer: `app.py`, `watcher.py`, stream orchestration.
- Domain and processing layer: `pipeline.py`, output shaping, transcript
  post-processing package.
- Infrastructure layer: `filesystem.py`, `state.py`, Docker image, GitHub
  Actions, local runtime directory management.

Notable design properties:

- configuration is separated from orchestration;
- reusable text processing is separated from audio/runtime orchestration;
- file mode and stream mode share core processing but preserve different
  lifecycle semantics;
- the runtime directory is an explicit contract rather than an incidental
  implementation detail.

## 6. Current quality posture

### Completed or established

- Ruff linting and formatting are wired into local and CI workflows.
- Mypy is enabled for a defined subset of modules.
- The repository test suite is present and enforced in CI.
- Branch coverage is enforced at `100%`.
- Package builds are validated in CI.
- Docker build validation exists in CI.
- Docker smoke validation exists through `make docker-smoke`.

### Limitations

- The highest-risk integration modules are not yet inside the mypy scope.
- Real-runtime validation is optional and not clearly part of the default CI
  contract.
- Complete coverage is useful but does not prove real-environment correctness
  for WhisperX, Torch, CUDA, FFmpeg, or Hugging Face interactions.

## 7. Current security and privacy posture

### Completed or established

- The repository documents privacy-oriented transcript processing.
- The documentation explicitly avoids claiming formal anonymisation.
- The daemon is local-first and single-node by design, which reduces exposure
  relative to a network service architecture.

### Limitations

- No dedicated security scanning job is visible in CI.
- No dependency vulnerability gate is visible in CI.
- No secret scanning baseline is present.
- No licence-reporting or SBOM artefact generation is visible.
- No provenance or image-scanning gate is visible for the container image.
- Runtime privacy, retention, and sensitive-artefact operations are not yet
  consolidated in a dedicated guide.

## 8. Current operational posture

### Completed or established

- The runtime tree is clearly defined.
- Output, failure-report, streaming, installation, Docker, and troubleshooting
  guides exist.
- Docker execution includes arbitrary-UID-safe runtime path handling.
- SQLite provides idempotent job-state tracking for file mode.

### Limitations

- No dedicated observability contract or structured runtime event model exists.
- No dedicated recovery guide exists.
- No documented backup and restore procedure exists.
- Failure-mode validation for partial writes, archive collisions, or state
  corruption is not yet evident as a named workstream.

## 9. Completed workstreams

### File-mode daemon baseline

- Purpose: provide managed runtime processing for stable audio files.
- Concrete outputs: runtime watcher, filesystem handling, SQLite state, JSON and
  TXT outputs, failure reports, archive behaviour.
- Evidence: `src/whisperx_daemon/`, `docs/configuration.md`,
  `docs/output.md`, tests, and README.
- Current status: complete with limitations.
- Remaining limitations: operational hardening is still incomplete.

### Streaming transcription support

- Purpose: support live PCM ingestion and incremental operational events.
- Concrete outputs: `streaming.py`, stream CLI flags, JSONL events, stream
  recording and archival, stream documentation.
- Evidence: commit history, `docs/streaming.md`, `tests/test_streaming.py`.
- Current status: complete with limitations.
- Remaining limitations: privacy caveats and observability formalisation should
  be strengthened.

### Reusable post-processing package

- Purpose: separate transcript sanitisation from daemon orchestration.
- Concrete outputs: independent package, CLI, documentation, workspace
  packaging.
- Evidence: `packages/transcript-postprocess/`, package README, packaging tests.
- Current status: complete with limitations.
- Remaining limitations: core text-processing module is not yet inside the
  configured mypy scope.

### Development and packaging standardisation

- Purpose: make local and CI workflows reproducible.
- Concrete outputs: `pyproject.toml`, `uv.lock`, workspace config, Makefile
  targets, package build jobs.
- Evidence: `pyproject.toml`, `.github/workflows/ci.yml`, `tests/test_packaging.py`.
- Current status: complete.
- Remaining limitations: supply-chain and dependency-governance controls are
  not yet layered on top.

### Validation baseline

- Purpose: keep repository quality checks repeatable.
- Concrete outputs: test job, quality job, coverage job, Docker build job,
  Docker smoke script, optional end-to-end test path.
- Evidence: CI workflow, Makefile, `tests/test_e2e.py`, recent validation
  commits.
- Current status: complete with limitations.
- Remaining limitations: real-runtime validation is not yet a standard gate.

## 10. Active workstreams

### Governance and current-state reconstruction

- Status: in progress.
- Evidence: this memo is being added now because the repository did not yet have
  a project-level strategy memo.
- Why active: the hardening programme needs a maintained source of truth for
  completed work, remaining work, risks, and operating assumptions.

### Hardening backlog definition

- Status: in progress.
- Evidence: repository baseline exists, but the hardening controls listed below
  are not yet implemented in the current snapshot.
- Why active: the next phase is to convert the existing disciplined baseline
  into an auditable and operationally safer project.

## 11. Remaining work

### Workstream status classification

| Workstream | Current status |
|---|---|
| Strategy and governance memo | In progress |
| Type-checking expansion for critical modules | Not started |
| Security and CI scanning baseline | Not started |
| Container provenance and SBOM | Not started |
| Retention and privacy operations | Not started |
| Real-environment smoke validation | Partially implemented |
| Structured observability | Not started |
| Recovery and failure-mode validation | Not started |
| Production-readiness checklist | Not started |

### Prioritised remaining tasks

#### 1. Expand mypy to highest-risk modules

- What must be done: include `pipeline.py` and
  `transcript_postprocess/core.py`, then resolve resulting type issues with
  narrow boundaries around untyped external APIs.
- Why it matters: these modules sit on the highest-risk integration and
  transformation paths.
- Dependencies: current mypy config, repository typing conventions.
- Risk if not completed: latent data-shape and integration faults remain harder
  to detect.
- Recommended next step: create a dedicated branch and add packaging regression
  tests that pin the expected mypy scope.

#### 2. Add security and dependency gates

- What must be done: add vulnerability, secret, and licence checks plus
  security documentation and triage rules.
- Why it matters: current CI proves quality, not security posture.
- Dependencies: dev-tooling selection and baseline file management.
- Risk if not completed: known vulnerable or misconfigured dependencies can
  enter releases without a blocking signal.
- Recommended next step: add a dedicated CI job and Makefile targets.

#### 3. Add container provenance, SBOM, and image scanning

- What must be done: scan built images, generate SBOM artefacts, and document
  provenance and digest-management policy.
- Why it matters: the container path is already a first-class delivery channel.
- Dependencies: Docker build job, chosen scanning tools, maintainable base-image
  policy.
- Risk if not completed: container risks remain unaudited and harder to trace.
- Recommended next step: extend the existing Docker job rather than creating a
  separate ad hoc path.

#### 4. Define privacy and retention operations

- What must be done: document artefact classes, retention expectations,
  deletion methods, and logging constraints.
- Why it matters: the runtime tree stores potentially sensitive data.
- Dependencies: current runtime directory contract and existing docs.
- Risk if not completed: operators may keep sensitive artefacts longer than
  intended or handle them inconsistently.
- Recommended next step: add a dedicated `docs/privacy.md` and cross-link it
  from streaming and output guides.

#### 5. Strengthen real-environment validation

- What must be done: convert the optional real-runtime path into a reproducible
  smoke workflow with deterministic fixtures and clear skip policy.
- Why it matters: mocked tests cannot fully prove FFmpeg, WhisperX, Torch, and
  runtime integration behaviour.
- Dependencies: fixture strategy, CPU/GPU lane policy, CI runtime budget.
- Risk if not completed: integration regressions may pass local and CI checks.
- Recommended next step: add a small CPU smoke path first and keep GPU optional.

#### 6. Formalise observability

- What must be done: introduce structured runtime events and document the event
  catalogue.
- Why it matters: current operational posture does not expose a stable event
  contract for monitoring or incident review.
- Dependencies: logger integration points in app, watcher, and streaming paths.
- Risk if not completed: failures remain harder to diagnose consistently.
- Recommended next step: add a minimal dataclass-backed event model without
  logging transcript text.

#### 7. Add recovery and failure-mode validation

- What must be done: test partial writes, archive collisions, state corruption,
  and restore procedures, then document the recovery policy.
- Why it matters: output integrity and state recoverability are production
  concerns for a daemon that moves files and writes persistent state.
- Dependencies: filesystem write paths and SQLite handling semantics.
- Risk if not completed: interrupted or corrupted runs may leave ambiguous state.
- Recommended next step: start with atomic-write tests and corrupted-state
  behaviour.

#### 8. Consolidate release-readiness controls

- What must be done: add a production-readiness checklist, PR template, and
  ownership/update policy.
- Why it matters: hardening work needs a repeatable release decision gate.
- Dependencies: prior hardening workstreams.
- Risk if not completed: release decisions remain inconsistent and implicit.
- Recommended next step: implement after the earlier hardening workstreams land.

## 12. Risks and mitigations

### Technical risks

- Untyped integration boundaries in WhisperX and related dependencies.
  Mitigation: expand mypy carefully and isolate external calls behind typed
  helpers.
- Real-runtime behaviour may diverge from mocked tests.
  Mitigation: add CPU smoke validation with deterministic artefacts.
- Partial-write and state-corruption behaviour is not yet explicit.
  Mitigation: introduce atomic-write tests and recovery documentation.

### Operational risks

- Sensitive artefacts may be retained or logged without explicit operational
  guidance.
  Mitigation: add privacy, retention, and logging policy documentation.
- No structured observability contract currently supports stable incident
  analysis.
  Mitigation: add structured runtime events and documentation.

### Supply-chain and dependency risks

- Vulnerable dependencies or container layers may go undetected in routine CI.
  Mitigation: add `pip-audit`, security scanning, image scanning, and SBOM
  generation.

### Validation and governance risks

- Coverage and unit tests may create false confidence without environment-level
  checks.
  Mitigation: make smoke validation explicit and document what each test layer
  proves.
- Without a maintained strategy memo, project status and hardening priorities
  can become ambiguous.
  Mitigation: update this memo at the end of each hardening work item.

## 13. Open questions

- Which deployment environments are actually in scope beyond local and
  single-host Docker use?
- Is CPU smoke acceptable as a default CI gate given model-download and runtime
  cost considerations?
- Which security tooling is preferred by maintainers for secret scanning and
  image scanning?
- Are base-image digests acceptable operationally, or is a documented update
  procedure preferred initially?
- What retention defaults are acceptable for archives, logs, outputs, and
  failure reports?
- Should observability stay log-based only, or is a metrics/export contract
  expected later?
- What recovery policy is desired for a corrupt `jobs.sqlite3`: fail fast,
  repair, rotate, or operator-assisted restore?

## 14. Recommended next steps

### Immediate next steps

1. Merge this strategy memo and link it from the documentation index.
2. Expand mypy into `pipeline.py` and `transcript_postprocess/core.py`.
3. Record any unavoidable untyped external boundaries explicitly.

### Short-term priorities

1. Add security, dependency, and secret scanning gates to CI.
2. Add container image scanning and SBOM generation.
3. Add privacy and retention operational documentation.
4. Add reproducible CPU real-smoke validation.

### Medium-term priorities

1. Introduce structured runtime observability.
2. Add recovery tests and backup/restore guidance.
3. Consolidate release-readiness and waiver processes.

### Deferred or optional work

1. GPU-backed CI validation if a stable runner becomes available.
2. Stronger provenance tooling after the baseline security gates are stable.
3. Additional packaging separation if `transcript-postprocess` is later split
   into its own repository.

## 15. Change log

- 2026-06-03: Created initial strategy memo from static codebase inventory.
