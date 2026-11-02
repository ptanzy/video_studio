# 28 — Ingestion identity and contract authority (v1.7 normative)

## Identity, duplicates and fingerprints
Canonical recording ID is the join key between album manifest, audio files and Analyzer sidecars. Do not derive identity from title, file order or WAV hash. Content SHA-256 fingerprints identify exact file bytes for caching/change detection, **not** logical recording identity: two recordings can have identical content, and the same recording can have a revised export. Import key = `(album_id, recording_id)`; duplicate key with conflicting assets is a validation error requiring review, not an automatic merge. Idempotent reimport of unchanged data must not duplicate track records, Shorts, drafts or render jobs. Preserve user overrides unless a documented invalidation condition occurs. Never invent missing recording IDs silently: report blocker or require explicit mapping. All writes use atomic temp-write/rename and revision checking as in docs 03 and 11.

## Source of truth
`contracts/schemas/` holds authoritative JSON Schema for file payloads; FastAPI's OpenAPI schema is authoritative for HTTP payloads. **Examples are fixtures, never type definitions.** Generate frontend TypeScript types from OpenAPI/JSON Schema as appropriate; use Pydantic models for FastAPI/backend with schema conformance tests. No C# runtime or C# models in this POC. Schema and generated code changes must be reviewed together. Unknown creative emotion is valid free text; do not introduce a closed emotion enum.

## CI contract checks
Validate all example JSON against its *matching* schema only after that schema exists. Add schemas for error envelope, metadata draft/override, ingestion result and job status before claiming their contracts are enforced. API contract tests exercise valid, invalid, missing, stale and duplicate requests, and verify structured error codes. CI fails on schema drift or stale generated types. Do not claim `api_error.v1.5.example.json` is a schema.

## Explicitly deferred
No Redis, PostgreSQL, S3, message queues, multiple render workers, C# orchestrator or distributed deduplication. Document extension seams; do not implement them.

## WU3A approved contract addition

Doc 38 Decision 1 approves dedicated `video-manifest-v1.schema.json`, `video-export-request-v1.schema.json`, `video-export-result-v1.schema.json`, and `render-report-v1.schema.json` contracts. They follow this document's authority rule: schemas, not the current `0.1-draft` Echoes example, define accepted fields. Stable album/track IDs remain mandatory join keys; paths stored in manifest/result/report data are `/`-separated album-project-relative references. The absolute album-project path is an interface argument and must not be persisted into portable project documents. No implementation may silently mint IDs or fuzzy-match missing artwork. Source-manifest preparation remains a separate explicit operation.
