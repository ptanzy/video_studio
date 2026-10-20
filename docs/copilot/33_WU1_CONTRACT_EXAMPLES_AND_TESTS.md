# 33 — WU1 contract fixtures, tests and implementation guardrails

## Structural manifest
The existing `contracts/schemas/manifest-v2.schema.json` accepts one or more tracks with `id`, `number`, `title`, `file`, plus `schema_version`, `project`, and `album`. The schema intentionally allows extra creative metadata. `music.emotion` may contain **any string**; do not validate against an enum. Semantic checks (duplicate IDs, existence, safe paths) are application validation, not implied by the structural schema.

## Recording identity
`track.id` is the track slot; `recording_id` identifies a particular audio recording. An A/B recording must not be merged on track title or number. Identity is supplied explicitly by canonical input or sidecar. For WU1 tests, validate the `recording_id` value on a candidate join object, but do not invent a canonical adapter mapping.

## Override store v1
See `contracts/schemas/override-store-v1.schema.json`. Example:
```json
{"schema_version":"1.0","album_id":"WRLD-FI-S01-A08","revision":0,"overrides":{}}
```
`overrides` is an opaque mapping in WU1; do not invent UI field structure. An update is a compare-and-swap: expected revision must match stored revision, and resulting revision increases by exactly one. Preserve arbitrary validated JSON overrides. Do not write partial final files.

## API error v1
See `contracts/schemas/api-error-v1.schema.json`. Example:
```json
{"error":{"code":"REVISION_CONFLICT","message":"Stored revision differs from expected revision.","details":{},"correlation_id":"local-request-001"}}
```
Error codes for WU1: `INVALID_MANIFEST`, `IDENTITY_REVIEW_REQUIRED`, `DUPLICATE_RECORDING_ID`, `REVISION_CONFLICT`, `STORAGE_ERROR`, `INTERNAL_ERROR`. Use machine-stable codes, human-readable messages, no raw traceback.

## WU1 tests (required)
- Valid minimal manifest; unknown emotion phrase; unknown creative metadata retained.
- Missing required fields and incorrect version rejected.
- Duplicate track IDs rejected at semantic validation layer.
- Explicit recording ID accepted; missing/duplicate IDs rejected for sidecar joins.
- Override store create, read, update, reload; expected revision mismatch returns conflict.
- Failure injection before replace leaves previous JSON readable and source files unchanged.
- Two sequential updates with same expected revision: one succeeds, next conflicts.
- Domain/application imports exclude HTTP framework and FFmpeg implementation.
- If scaffolded: FastAPI health test and React placeholder route smoke/typecheck.
- CI: no render, network, cloud or GPU needed.

## Exclusions
Do not implement title/description templates, color mappings, job polling, upload, waveforms, audio stream routes, or legacy CLI refactoring in WU1.
