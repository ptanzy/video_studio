> **v1.3 authoritative override:** React + TypeScript + Vite + Tailwind + WaveSurfer.js frontend; FastAPI backend; docs live in `docs/copilot/`. Any earlier Streamlit or Python-only UI guidance in this document is superseded by `15_FRONTEND_ARCHITECTURE.md`, `16_UI_UX_SPECIFICATION.md`, and `17_UI_WIREFRAMES.md`. Do not implement Streamlit.

# Microservice-ready boundaries — normative v1.2

## Intent and non-goals
WRLD Video Studio is a standalone local POC in its own Git repository. Design it as an extractable media-rendering service. WU3 already supplies a loopback-only FastAPI preview adapter; this does not authorize a public/remote API, Docker, Kubernetes, message broker, cloud deployment, multi-worker distributed queue, or Analyzer integration. The core engine must remain callable independently of React, CLI parsing, and HTTP. Python owns domain/application/media orchestration; TypeScript is limited to the later React client.

## Component boundaries and dependency direction
- `domain/`: versioned recording, album, render-request, job-status, artifact models and pure validation. No Streamlit, FFmpeg subprocesses, or network code.
- `application/`: use cases (`validate_request`, `prepare_preview`, `submit_render`, `get_job`, `cancel_job`, `verify_artifacts`); defines protocol/ports for media probe, renderer, job store, artifact store, metadata importer, clock, and logging. No UI or FFmpeg command construction.
- `infrastructure/`: FFmpeg/FFprobe adapters, filesystem storage, atomic JSON state, structured JSONL logging, metadata file import. Concrete adapters depend on application ports; application never imports concrete adapters.
- `interfaces/cli/` and `interfaces/http/`: thin input/output adapters invoking application use cases; WU3 already supplies the local preview HTTP boundary and WU3A adds an approved headless video-export entry point. Future React UI calls HTTP use cases and never FFmpeg directly.
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
1. Input is an explicit trusted runtime album-project directory plus a versioned JSON album/render manifest whose media references are portable and project-relative. The importer resolves and validates them inside that project boundary, normalizes them into internal domain models, and confines final artifacts to the project's `output/`. Legacy manifests use explicit adapters, not scattered conditionals. Do not persist the caller's machine-specific library prefix in portable project or publishing contracts.
2. Musical analysis metadata is a separate versioned record keyed by stable recording identity. Prefer canonical sidecar JSON for rich observations, with optional supported WAV/BWF metadata extraction. **Do not assume all custom analysis fields can be embedded in WAV or recovered from generic WAV tags.** Video Studio must operate without analysis metadata and must not depend on Analyzer implementation code or its repository.
3. Render request contains an immutable snapshot of selected inputs, timestamps, visual presets, requested artifacts, schema version, and stable request ID. Never expose a mutable editor-state object to a running job.
4. Result contains job ID, state, validated artifacts with relative path/URI, media properties, errors, warnings, timestamps, and provenance. Do not conflate render result with canonical album data.
5. Contracts use explicit schema versions and compatibility rules; breaking changes require a new major version and a migration/adapter. Treat unknown required fields as validation failures; unknown optional extension fields follow a documented policy.
6. No cross-repository Python imports, shared mutable database, or hidden global state. Communicate through files/JSON now; future transport adapters may use HTTP/queues without changing domain/application behavior.

## Album Project Initialization versus Video Studio ownership

The future WRLD Music workflow orchestrator owns **Album Project Initialization**: selecting a configured music-library root/channel, creating the primary album directory, establishing album identity/project metadata, initializing source manifests/configuration and standard audio/artwork locations, and preparing the project for generation, ingestion, analysis, rendering, and publishing. That orchestrator communicates through approved project files/contracts; Video Studio does not import its implementation or share hidden mutable state.

WU3A Video Studio consumes an already-existing album project. It validates the supported manifest/media, creates only required managed descendants beneath `output/`, renders requested artifacts, writes render-owned chapters/report data, and returns structured artifact results. It never invents album identity, creates/relocates the primary folder, rewrites source configuration, or overwrites approved publishing content. WU4 may expose the future initialization/selection workflow through an approved adapter, but project creation remains orchestrator-owned rather than FFmpeg/render-service behavior.

## Job and artifact semantics
- POC uses one in-process/local worker with persisted job snapshots and status. Future queue implementation can replace the job scheduler via a port.
- Idempotency key/fingerprint includes normalized render request, input content identity or verified file signatures, relevant renderer version and visual preset versions. A reused artifact must pass validation.
- Temporary outputs are job-scoped; FFprobe verification precedes atomic promotion. A cancelled or failed job cannot be reported completed. Recovery rules follow `11_JOB_LIFECYCLE_AND_RECOVERY.md`.
- Use portable relative paths in manifests and publishing metadata; resolve against the explicit album-project directory with traversal, symlink/reparse, canonical-containment, and source/output-alias protections. Do not store Windows-only absolute paths in portable contracts. Runtime snapshots may record sanitized/resolved provenance where required by the accepted lifecycle contract.
- For now, source media stays on the local filesystem. Do not require S3, databases, Redis, or authentication.
- Final product artifacts are rooted at `<album-project>/output/`. WU3A may create required owned output/staging descendants under approved storage rules but must not create, move, rename, or infer the primary album directory. A future initialization workflow may create album projects beneath configurable/selectable music-library roots and channels without changing application use cases.

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
- WU2–WU3: completed infrastructure and authoritative still-preview capabilities behind ports/use cases.
- WU3A: add the product album/track render contract, timeline/chapters, static MP4 renderer, and headless interface while reusing the established worker, process, artifact and admission ports.
- WU4–WU5: implement Import/Review and Metadata workflows behind existing/new approved application contracts; WU4 owns future project initialization/selection beneath configurable library roots and WU5 preserves portable references. Never duplicate WU3A probing/timeline/encoding in frontend code.
- WU6: validate the complete React/HTTP/application/FFmpeg vertical slice, selected-project boundary, project-local `output/`, remaining Shorts/artifacts, and release packaging; document future queue adapter mapping without implementing one.
- Do not broaden the existing loopback FastAPI adapter into a remote/public service unless a separately approved orchestrator requires process-isolated invocation. Introduce a queue only when durable asynchronous multi-process scheduling is needed; consider a monorepo only when cross-project change coordination demonstrably outweighs separation.

## Required Copilot WU0 report additions
Explain: proposed package/dependency diagram; which interfaces are pure vs infrastructural; manifest/metadata boundary; recording identity handling; how a future HTTP worker would reuse application use cases; contract tests; what is deliberately deferred. **Do not implement the future service or modify Music Analyzer.**
