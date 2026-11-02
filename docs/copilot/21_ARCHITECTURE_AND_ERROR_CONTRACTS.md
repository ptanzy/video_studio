# 21 — v1.5 Architecture, Anti-Patterns, and Error Contracts (normative)

## POC boundaries
- React/TypeScript/Vite UI → typed HTTP client → FastAPI adapter → Python application use cases → infrastructure ports for FFmpeg, FFprobe, filesystem and job state.
- Domain/application modules must not import FastAPI, React, Streamlit, HTTP clients, or the Music Analyzer. A CLI adapter invokes the same use cases.
- `legacy_v2/` is **reference material only**. Do not copy the monolithic `build_video.py`, import it, call it as a subprocess, preserve its global mutable state, or let it determine module boundaries. Extract requirements and prove behavior with tests; implement modular ports/adapters anew. No hidden fallbacks to legacy paths.
- No Redis, PostgreSQL, cloud object store, distributed queue, container orchestration, or multiworker scheduler in the POC. Future ports may permit them, but adding infrastructure requires explicit authorization.

WU3A adds a headless album/track export adapter over the same application services and storage/process ports. Its trusted composition accepts the explicit album-project directory, while portable manifests retain project-relative paths. It does not add frontend code, album-folder initialization, publishing-metadata access, or a second FFmpeg path. The approved Doc 38 request/result fields control Phase 1; any additional stable error code still requires explicit contract review. Absolute filesystem paths and raw tool exceptions remain private outside trusted local diagnostics.

## Storage boundary and ownership
- `SourceAssetStore`: read-only WAV, artwork, and canonical album metadata resolved inside the explicit album-project boundary. Never mutate inputs or follow an escape outside the project.
- `EditorStateStore`: versioned overrides and optimistic revision check; atomic same-filesystem replacement. Only application service writes.
- `ScratchStore`: job-scoped transient files under a configurable local scratch root, e.g. `<workspace>/.wrld-scratch/<job_id>/`; never assume `/tmp` exists on Windows. Clean only known job-owned scratch after validation/cancellation; record abandoned job IDs for startup reconciliation.
- `ArtifactStore`: validated final MP4/JPG/text/JSON artifacts under `<album-project>/output/`. Publish by atomic same-volume rename; never treat scratch as published artifacts or redirect one project's output into another project/repository. Future S3/Blob adapter is deferred and must have explicit promotion semantics.
- `JobRepository`: POC local durable JSON state with one active render, job IDs and immutable request snapshots. Future Redis/SQL implementations may replace the adapter, not the domain API.

`render_report.json` is the approved revisioned verified-artifact catalog, not editable publishing text. `youtube_metadata.json` is WU5's materialization of revisioned editor state and is outside the WU3A read/write boundary. `youtube_publish_state.json` is reserved for a future uploader and is absent until actual publishing state exists. Downstream automation joins these contracts by stable target/artifact IDs and project-relative paths; it never infers ownership or target type from a filename alone.

## Error envelope
Every API failure uses a stable machine-readable body; HTTP status is not the error code:
```json
{"error":{"code":"OVERRIDE_REVISION_CONFLICT","message":"Changes were made elsewhere; reload before saving.","request_id":"req-example","details":{"expected_revision":3,"actual_revision":4},"retryable":false}}
```
Stable codes: `INVALID_MANIFEST`, `UNSUPPORTED_SCHEMA_VERSION`, `ASSET_NOT_FOUND`, `INVALID_SHORT_RANGE`, `INVALID_COLOR`, `METADATA_VALIDATION_FAILED`, `UNRESOLVED_PLACEHOLDER`, `OVERRIDE_REVISION_CONFLICT`, `JOB_ALREADY_RUNNING`, `JOB_NOT_FOUND`, `RENDER_FAILED`, `RENDER_CANCELLED`, `OUTPUT_VALIDATION_FAILED`, `STORAGE_IO_ERROR`, `INTERNAL_ERROR`. Add new codes through contract review; do not expose arbitrary exception text or local paths in user-facing errors. Use 400/404/409/422/500/503 appropriately; preserve field-level `details` for validation.

## Error boundaries and recovery
- Validate requests at HTTP boundary (Pydantic), then business invariants in application layer. Map typed domain exceptions to the envelope centrally; no broad `except Exception: pass`.
- Unexpected exceptions: log sanitized stack with request/job correlation ID, return `INTERNAL_ERROR`, never pretend success.
- FFmpeg subprocess: capture exit status, bounded stderr tail, timeout/cancel; terminate process group safely, validate output, clean owned partials, and mark job failed/cancelled. Do not retry automatically without defined policy.
- Frontend: typed API error decoder, accessible error banner with recovery action, retain unsaved edits after 409, and never optimistically mark a render complete.

## Tests and acceptance
- Architecture import-boundary tests; fake storage/render ports; typed error→HTTP mapping tests; 409 stale revision with no lost update; subprocess failure/cancel/timeout; startup scratch reconciliation; no source mutation; request IDs preserved in logs. A failed validation must not create a final artifact.

## v1.7 progress and contract boundaries
Job polling and network-disconnect state are defined in 30; API contract approval and schema generation rules in 28/31. Do not use example JSON as schema. Single local worker only.
