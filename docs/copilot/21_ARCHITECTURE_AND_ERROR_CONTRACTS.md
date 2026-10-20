# 21 — v1.5 Architecture, Anti-Patterns, and Error Contracts (normative)

## POC boundaries
- React/TypeScript/Vite UI → typed HTTP client → FastAPI adapter → Python application use cases → infrastructure ports for FFmpeg, FFprobe, filesystem and job state.
- Domain/application modules must not import FastAPI, React, Streamlit, HTTP clients, or the Music Analyzer. A CLI adapter invokes the same use cases.
- `legacy_v2/` is **reference material only**. Do not copy the monolithic `build_video.py`, import it, call it as a subprocess, preserve its global mutable state, or let it determine module boundaries. Extract requirements and prove behavior with tests; implement modular ports/adapters anew. No hidden fallbacks to legacy paths.
- No Redis, PostgreSQL, cloud object store, distributed queue, container orchestration, or multiworker scheduler in the POC. Future ports may permit them, but adding infrastructure requires explicit authorization.

## Storage boundary and ownership
- `SourceAssetStore`: read-only WAV, artwork, and canonical album metadata. Never mutate inputs.
- `EditorStateStore`: versioned overrides and optimistic revision check; atomic same-filesystem replacement. Only application service writes.
- `ScratchStore`: job-scoped transient files under a configurable local scratch root, e.g. `<workspace>/.wrld-scratch/<job_id>/`; never assume `/tmp` exists on Windows. Clean only known job-owned scratch after validation/cancellation; record abandoned job IDs for startup reconciliation.
- `ArtifactStore`: validated final MP4/JPG/text/JSON artifacts under configured output root. Publish by atomic same-volume rename; never treat scratch as published artifacts. Future S3/Blob adapter is deferred and must have explicit promotion semantics.
- `JobRepository`: POC local durable JSON state with one active render, job IDs and immutable request snapshots. Future Redis/SQL implementations may replace the adapter, not the domain API.

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
