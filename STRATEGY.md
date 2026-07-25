# Strategy Memo

## 1. Project intent

### Executive summary

#### Original purpose

`whisperx-daemon` exists to turn WhisperX into a local-first operational service
for transcription workflows. The repository adds runtime management, output
contracts, idempotent processing, Docker support, and privacy-oriented
post-processing that upstream WhisperX does not provide directly.

#### Current state

The repository has a coherent layered architecture, a reusable post-processing
dependency boundary, repository-wide tests, complete branch-coverage
enforcement, targeted mypy coverage, Docker build and smoke validation, and
GitHub Actions CI. `textformer` has been extracted into a sibling repository
and is consumed as an external dependency rather than a workspace member. The
validated documentation, type-safety, extraction, and dependency-rename stack
has been consolidated into `develop`. One CUDA cleanup fix remains explicitly
work in progress and is not part of the integration baseline. The repository
is stronger than a prototype, but is not yet fully hardened from a governance,
security, provenance, observability, privacy-operations, and recovery
perspective.

#### Main achievements

- Established a single-node daemon architecture around a managed runtime tree.
- Added streaming transcription with live JSONL events and final artefacts.
- Separated reusable transcript sanitisation into the standalone
  `textformer` repository.
- Standardised development and packaging on `uv`.
- Added quality, test, coverage, package-build, and Docker-build CI jobs.
- Added Docker smoke validation and complete branch coverage enforcement.
- Consolidated the validated June 2026 branch stack and removed redundant local
  branch references after proving ancestry or patch equivalence.

#### Main remaining work

- Create and maintain project-level governance and hardening documentation.
- Add security, dependency, secret, and supply-chain scanning gates.
- Define privacy, retention, observability, and recovery operating procedures.
- Add stronger real-environment validation beyond the current optional path.

#### Main risks

- Dynamic WhisperX and transformers boundaries remain only partially typed
  because upstream libraries do not expose a stable typed API.
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
2026-07-25:

- The repository contains one Python package: `whisperx-daemon`.
- The reusable `textformer` package now lives in a separate sibling
  repository and is consumed as an external dependency.
- The root package uses `src/whisperx_daemon/`.
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
- No repository file currently defines dedicated CI jobs for security scanning,
  image scanning, SBOM generation, provenance, privacy operations,
  observability, or recovery drills.
- Local validation passes 114 tests with one opt-in real-runtime test skipped,
  plus Ruff, format, mypy, and 100% statement and branch coverage.
- The unmerged CUDA cleanup branch has an associated WIP stash; its final scope
  and integration status therefore remain unresolved.

## 3. Reasonable inferences

These points are inferred from repository evidence and should be treated as
working assumptions until validated against maintainer intent:

- The project intent has expanded from a basic transcription wrapper into a
  production-shaped local operational service.
- Streaming support appears to have been a later capability rather than an
  original baseline because the commit history shows a distinct sequence of
  streaming-related feature commits.
- The reusable `textformer` package is intended as a deliberate
  boundary for independent reuse; it has now been extracted into its own
  repository.
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
5. Extraction of the reusable transcript post-processing package into its own
   repository.
6. Consolidation of the validated governance, type-safety, extraction, and
   `textformer` migration changes into the development baseline.

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

- The highest-risk integration modules are now inside the enforced mypy scope.
- Transcript payloads and NER entity payloads now have explicit local typing.
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
- Concrete outputs: standalone sibling repository, CLI, documentation, package
  metadata, packaging tests.
- Evidence: sibling `textformer` repository, package README,
  packaging tests.
- Current status: complete with limitations.
- Remaining limitations: dynamic transformers integration remains a narrow
  external typing boundary.

### Critical-module type-safety expansion

- Purpose: bring the highest-risk integration and text-processing modules into
  the enforced mypy contract.
- Concrete outputs: daemon mypy scope extended to `pipeline.py`, the sibling
  `textformer` repository enforces strict checks for `src/textformer/core.py`,
  packaging regression tests added, and transcript and NER payload shapes
  tightened with explicit local types.
- Evidence: `pyproject.toml`, `tests/test_packaging.py`,
  `src/whisperx_daemon/pipeline.py`, and sibling `textformer` validation.
- Current status: complete with limitations.
- Remaining limitations: WhisperX and transformers remain narrow dynamic
  integration boundaries due to unstable upstream type surfaces.

### Development and packaging standardisation

- Purpose: make local and CI workflows reproducible.
- Concrete outputs: `pyproject.toml`, `uv.lock`, dependency source override,
  Makefile targets, package build jobs.
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

### Hardening backlog definition

- Status: in progress.
- Evidence: repository baseline exists, but the hardening controls listed below
  are not yet implemented in the current snapshot.
- Why active: the next phase is to convert the existing disciplined baseline
  into an auditable and operationally safer project.

### CUDA cleanup failure handling

- Status: in progress.
- Evidence: the local `fix/cuda-cleanup-failure` branch contains a focused
  cleanup-error commit and has an associated WIP stash.
- Why active: the committed change is not sufficient evidence that all intended
  work is complete; it remains deliberately unmerged pending stash review and a
  clean validation run against the current `develop` baseline.

## 11. Remaining work

### Workstream status classification

| Workstream | Current status | Evidence | Remaining work | Risk level | Recommended next action |
|---|---|---|---|---|---|
| Strategy and governance memo | Complete with limitations | `STRATEGY.md` and documentation links | Keep evidence and status current | Medium | Update with each material workstream |
| Type-checking expansion | Complete with limitations | Mypy includes critical daemon modules; `make check` passes | Continue narrowing dynamic ML boundaries | Medium | Add types only where upstream contracts are stable |
| `textformer` extraction | Complete with limitations | Sibling dependency, updated imports, lockfile, and packaging tests | Resolve release and Docker build-context strategy | High | Publish a versioned dependency or define a joint build context |
| Branch consolidation | Complete | Ancestry and patch-equivalence audit; validated stack integrated into `develop` | Review the remaining WIP branch | Low | Keep topic branches short-lived and delete after integration |
| CUDA cleanup failure handling | In progress | Focused commit plus associated WIP stash | Rebase, inspect stash, validate, and review | Medium | Retain as `fix/cuda-cleanup-failure` until complete |
| Security and CI scanning baseline | Not started | No dedicated workflow jobs | Add vulnerability, secret, and licence gates | High | Add one maintainable CI security job |
| Container provenance and SBOM | Not started | No scan, SBOM, or provenance artefact | Select tools and define update policy | High | Extend the existing Docker CI job |
| Retention and privacy operations | Not started | Runtime artefacts documented but no retention policy | Define retention, deletion, and logging rules | High | Add `docs/privacy.md` |
| Real-environment smoke validation | Partially implemented | Opt-in `tests/test_e2e.py` path | Make a deterministic CPU lane reproducible | High | Establish a small maintained fixture |
| Structured observability | Not started | Operational logs exist without a stable event contract | Define events and sensitive-data exclusions | Medium | Add a minimal typed event model |
| Recovery and failure-mode validation | Not started | No named recovery test workstream | Test partial writes, collisions, and corrupt state | High | Start with atomic-write behaviour |
| Production-readiness checklist | Not started | No release decision checklist | Define ownership, waivers, and release evidence | Medium | Add after foundational hardening gates |

### Prioritised remaining tasks

#### 1. Add security and dependency gates

- What must be done: add vulnerability, secret, and licence checks plus
  security documentation and triage rules.
- Why it matters: current CI proves quality, not security posture.
- Dependencies: dev-tooling selection and baseline file management.
- Risk if not completed: known vulnerable or misconfigured dependencies can
  enter releases without a blocking signal.
- Recommended next step: add a dedicated CI job and Makefile targets.

#### 2. Add container provenance, SBOM, and image scanning

- What must be done: scan built images, generate SBOM artefacts, and document
  provenance and digest-management policy.
- Why it matters: the container path is already a first-class delivery channel.
- Dependencies: Docker build job, chosen scanning tools, maintainable base-image
  policy.
- Risk if not completed: container risks remain unaudited and harder to trace.
- Recommended next step: extend the existing Docker job rather than creating a
  separate ad hoc path.

#### 3. Define privacy and retention operations

- What must be done: document artefact classes, retention expectations,
  deletion methods, and logging constraints.
- Why it matters: the runtime tree stores potentially sensitive data.
- Dependencies: current runtime directory contract and existing docs.
- Risk if not completed: operators may keep sensitive artefacts longer than
  intended or handle them inconsistently.
- Recommended next step: add a dedicated `docs/privacy.md` and cross-link it
  from streaming and output guides.

#### 4. Strengthen real-environment validation

- What must be done: convert the optional real-runtime path into a reproducible
  smoke workflow with deterministic fixtures and clear skip policy.
- Why it matters: mocked tests cannot fully prove FFmpeg, WhisperX, Torch, and
  runtime integration behaviour.
- Dependencies: fixture strategy, CPU/GPU lane policy, CI runtime budget.
- Risk if not completed: integration regressions may pass local and CI checks.
- Recommended next step: add a small CPU smoke path first and keep GPU optional.

#### 5. Formalise observability

- What must be done: introduce structured runtime events and document the event
  catalogue.
- Why it matters: current operational posture does not expose a stable event
  contract for monitoring or incident review.
- Dependencies: logger integration points in app, watcher, and streaming paths.
- Risk if not completed: failures remain harder to diagnose consistently.
- Recommended next step: add a minimal dataclass-backed event model without
  logging transcript text.

#### 6. Add recovery and failure-mode validation

- What must be done: test partial writes, archive collisions, state corruption,
  and restore procedures, then document the recovery policy.
- Why it matters: output integrity and state recoverability are production
  concerns for a daemon that moves files and writes persistent state.
- Dependencies: filesystem write paths and SQLite handling semantics.
- Risk if not completed: interrupted or corrupted runs may leave ambiguous state.
- Recommended next step: start with atomic-write tests and corrupted-state
  behaviour.

#### 7. Consolidate release-readiness controls

- What must be done: add a production-readiness checklist, PR template, and
  ownership/update policy.
- Why it matters: hardening work needs a repeatable release decision gate.
- Dependencies: prior hardening workstreams.
- Risk if not completed: release decisions remain inconsistent and implicit.
- Recommended next step: implement after the earlier hardening workstreams land.

## 12. Risks and mitigations

### Technical risks

- Dynamic integration boundaries in WhisperX and related dependencies.
  Mitigation: keep the boundaries narrow, typed locally where possible, and
  document any unavoidable dynamic surfaces explicitly.
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
- The committed local `../textformer` dependency source validates sibling
  development but is not available inside a daemon-only Docker build context.
  Mitigation: publish or tag `textformer` before Docker release validation, or
  implement an explicit parent-context Docker build that includes both sibling
  repositories.

### Validation and governance risks

- Coverage and unit tests may create false confidence without environment-level
  checks.
  Mitigation: make smoke validation explicit and document what each test layer
  proves.
- Without a maintained strategy memo, project status and hardening priorities
  can become ambiguous.
  Mitigation: update this memo at the end of each hardening work item.
- The CUDA cleanup branch may contain intended changes only in its WIP stash.
  Mitigation: do not merge or delete the branch or stash until its scope is
  reviewed and the complete result passes the current quality gate.

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

1. Review and complete `fix/cuda-cleanup-failure`, including its associated WIP
   stash, then rebase and validate it against `develop`.
2. Finalise the versioned distribution and Docker build strategy for
   `textformer`.
3. Start the dedicated CI security-gate branch.

### Short-term priorities

1. Add security, dependency, and secret scanning gates to CI.
2. Add container image scanning and SBOM generation.
3. Add privacy and retention operational documentation.
4. Add reproducible CPU real-smoke validation.
5. Finalise Docker publication strategy for the extracted package dependency
   boundary so `make docker-smoke` can resolve `textformer` inside the image
   build context.

### Medium-term priorities

1. Introduce structured runtime observability.
2. Add recovery tests and backup/restore guidance.
3. Consolidate release-readiness and waiver processes.

### Deferred or optional work

1. GPU-backed CI validation if a stable runner becomes available.
2. Stronger provenance tooling after the baseline security gates are stable.
3. Additional packaging separation work only if the dependency publication
   strategy changes again.

## 15. Change log

- 2026-06-03: Created initial strategy memo from static codebase inventory.
- 2026-06-03: Expanded mypy scope to `pipeline.py` and
  the then-workspace post-processing core, and documented the remaining dynamic
  ML integration boundaries.
- 2026-06-04: Extracted `textformer` into a sibling repository and
  converted `whisperx-daemon` to consume it as an external dependency boundary.
- 2026-06-04: Renamed the extracted post-processing package and daemon
  dependency boundary to `textformer`.
- 2026-06-04: Documented the Docker build-context limitation while the daemon
  consumes `textformer` through a local sibling source path.
- 2026-07-25: Consolidated the validated governance, type-safety, dependency
  extraction, and rename stack into `develop`; classified the CUDA cleanup
  branch as work in progress; and removed redundant merged branch references.
