> **v1.3 authoritative override:** React + TypeScript + Vite + Tailwind + WaveSurfer.js frontend; FastAPI backend; docs live in `docs/copilot/`. Any earlier Streamlit or Python-only UI guidance in this document is superseded by `15_FRONTEND_ARCHITECTURE.md`, `16_UI_UX_SPECIFICATION.md`, and `17_UI_WIREFRAMES.md`. Do not implement Streamlit.

# Microservice-ready boundaries — normative v1.2

## Intent and non-goals
WRLD Video Studio is a standalone local POC in its own Git repository. Design it as an extractable media-rendering service, **without** implementing a web API, Docker, Kubernetes, message broker, cloud deployment, multi-worker distributed queue, or Analyzer integration in this POC. The core engine must be callable without Streamlit, CLI argument parsing, or HTTP. Python is the implementation language for now; do not introduce C# or TypeScript orchestration merely for future readiness.

## Component boundaries and dependency direction
- `domain/`: versioned recording, album, render-request, job-status, artifact models and pure validation. No Streamlit, FFmpeg subprocesses, or network code.
- `application/`: use cases (`validate_request`, `prepare_preview`, `submit_render`, `get_job`, `cancel_job`, `verify_artifacts`); defines protocol/ports for media probe, renderer, job store, artifact store, metadata importer, clock, and logging. No UI or FFmpeg command construction.
- `infrastructure/`: FFmpeg/FFprobe adapters, filesystem storage, atomic JSON state, structured JSONL logging, metadata file import. Concrete adapters depend on application ports; application never imports concrete adapters.
- `interfaces/cli/` and `interfaces/ui/`: thin input/output adapters invoking application use cases; Streamlit UI must not call FFmpeg directly. A future `interfaces/http/` may call the same use cases, but **do not implement it now**.
- `tests/`: contract, unit, integration, and UI tests. Legacy v2 code is reference only, not a permanent dependency.

Suggested package layout (adapt to existing repo after WU0):
```
src/wrld_video_studio/
  domain/
  application/
    ports/
    use_cases/
  infrastructure/
    ffmpeg/
    filesystem/
    metadata/
  interfaces/
    cli/
    ui/
tests/
  unit/
  contracts/
  integration/
  ui/
```

## Interoperability contracts
1. Input is a versioned JSON album/render manifest plus filesystem paths or file URIs to source WAV and artwork. The importer validates and normalizes it into internal domain models; legacy manifests use explicit adapters, not scattered conditionals.
2. Musical analysis metadata is a separate versioned record keyed by stable recording identity. Prefer canonical sidecar JSON for rich observations, with optional supported WAV/BWF metadata extraction. **Do not assume all custom analysis fields can be embedded in WAV or recovered from generic WAV tags.** Video Studio must operate without analysis metadata and must not depend on Analyzer implementation code or its repository.
3. Render request contains an immutable snapshot of selected inputs, timestamps, visual presets, requested artifacts, schema version, and stable request ID. Never expose a mutable editor-state object to a running job.
4. Result contains job ID, state, validated artifacts with relative path/URI, media properties, errors, warnings, timestamps, and provenance. Do not conflate render result with canonical album data.
5. Contracts use explicit schema versions and compatibility rules; breaking changes require a new major version and a migration/adapter. Treat unknown required fields as validation failures; unknown optional extension fields follow a documented policy.
6. No cross-repository Python imports, shared mutable database, or hidden global state. Communicate through files/JSON now; future transport adapters may use HTTP/queues without changing domain/application behavior.

## Job and artifact semantics
- POC uses one in-process/local worker with persisted job snapshots and status. Future queue implementation can replace the job scheduler via a port.
- Idempotency key/fingerprint includes normalized render request, input content identity or verified file signatures, relevant renderer version and visual preset versions. A reused artifact must pass validation.
- Temporary outputs are job-scoped; FFprobe verification precedes atomic promotion. A cancelled or failed job cannot be reported completed. Recovery rules follow `11_JOB_LIFECYCLE_AND_RECOVERY.md`.
- Use portable relative paths in manifests; resolve against a declared album root with traversal protections. Do not store Windows-only absolute paths in contracts.
- For now, source media stays on the local filesystem. Do not require S3, databases, Redis, or authentication.

## Contract-first testing requirements
- Unit tests call application use cases with fake ports, without FFmpeg, Streamlit, or live network.
- Contract tests validate representative current/legacy manifests, metadata sidecars, requests, results, and schema migrations, including absent Analyzer metadata.
- Adapter tests ensure CLI and UI produce equivalent render requests and receive equivalent job/result structures.
- Integration tests run real FFmpeg/FFprobe on tiny synthetic fixtures and verify artifacts, excerpt content, failure recovery, and idempotency.
- Tests must demonstrate that importing `domain` or `application` does not import Streamlit or invoke FFmpeg. Add an architecture import-boundary check (static or import test).
- All POC test commands and CI configuration remain governed by `06_TEST_STRATEGY.md` and `13_ENVIRONMENT_AND_DELIVERY.md`.

## Scope gates and migration triggers
- WU0: inspect current repository and identify boundary violations and compatibility blockers, no changes.
- WU1: define ports, domain contracts, adapters skeleton, schema and tests; no service host.
- WU2–WU5: implement features behind ports and use cases, without bypassing boundaries.
- WU6: validate a complete UI/CLI-to-application-to-FFmpeg vertical slice and document future HTTP/queue adapter mapping.
- Introduce an HTTP service only when a separate orchestrator needs remote/process-isolated invocation; introduce a queue only when durable asynchronous multi-process scheduling is needed; consider a monorepo only when cross-project change coordination demonstrably outweighs separation.

## Required Copilot WU0 report additions
Explain: proposed package/dependency diagram; which interfaces are pure vs infrastructural; manifest/metadata boundary; recording identity handling; how a future HTTP worker would reuse application use cases; contract tests; what is deliberately deferred. **Do not implement the future service or modify Music Analyzer.**
