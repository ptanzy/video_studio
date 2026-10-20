# 32 — WU0 resolution and WU1 implementation baseline (v1.8, authoritative)

## Status and authority
This document resolves the *WU1 implementation boundary* identified by Copilot's WU0 inspection. It supersedes conflicting WU1/WU0 directions in 00, 07, 14, 20 and earlier addenda. `legacy_v2/` is **read-only**: do not edit, import, copy, invoke or use its monolithic architecture. The current POC stack is React/TypeScript/Vite/Tailwind/WaveSurfer, FastAPI, Python domain/application, FFmpeg/FFprobe infrastructure. No Streamlit.

This handoff contains **proposed defaults for approval**. User authorization of WU1 accepts only the WU1 scope below, not future WU2+ product decisions. Do not treat unapproved illustration/example fields as contracts.

## Work-unit dependency graph
- WU0 — read-only inspection and blockers report. COMPLETE as inspection, no code.
- **WU1 — foundations:** typed domain/application skeleton, minimal manifest validation, stable identity validation, revisioned atomic override storage, typed error model, fake ports, toolchain and tests. Minimal FastAPI health endpoint and React shell are permitted **only** as non-functional scaffolding; no media APIs, no UI feature behavior.
- WU2 — media infrastructure and single-worker job lifecycle: FFprobe, FFmpeg, immutable snapshots, staging, verification, recovery and real synthetic-media tests.
- WU3 — image rendering and color treatment: presets, custom HEX, deterministic resolution, browser proxy vs authoritative still, comparison UI, visual regression.
- WU4 — Import and Review React workflow, WAV access, waveform Short selection, previews and override persistence.
- WU5 — Metadata screen, batch grid, deterministic description drafts, chapters, validation and approval/export.
- WU6 — integrated render UX, full local end-to-end, Windows/manual checks, resource bounds, docs and acceptance.
No unit proceeds without test evidence and user approval.

## WU1 exact implementation contract
1. Create `backend/src/wrld_video_studio/{domain,application/ports,infrastructure,interfaces/http}` and `backend/tests/{unit,contracts,integration}` with import-boundary tests. Domain/application must not import FastAPI, FFmpeg, or React.
2. Validate existing `contracts/schemas/manifest-v2.schema.json` as a **structural input subset** (`schema_version = "2.0"`). Preserve unknown source metadata; do not silently normalize the rich creative example into a complete render manifest. Invalid inputs return typed errors. `tracks[].id` is **not** automatically `recording_id`.
3. Recording identity: when joining Analyzer observations, require explicit non-empty `recording_id` in the join input; missing or duplicate IDs yield `IDENTITY_REVIEW_REQUIRED` / `DUPLICATE_RECORDING_ID`. Do not derive from filename, title, track order, hashes or prompt. In WU1 validate identity only; full join adapter is WU4 or an explicitly approved later slice.
4. Implement a revisioned override *store*, not a complete editor-state format: `contracts/schemas/override-store-v1.schema.json`. `revision` begins at 0; writes supply expected revision; mismatches fail with `REVISION_CONFLICT`; successful write increments revision once. Persist via same-directory temp file + fsync + atomic replace, never mutate input media; serialize writes per album in one process. Multi-process concurrent writers are **unsupported in POC**, must fail/avoid simultaneous writers; do not claim cross-platform guarantees without tests.
5. Implement `contracts/schemas/api-error-v1.schema.json` and Python error types with stable `code`, `message`, `details` and `correlation_id`. Never leak stack traces to UI.
6. Use `pytest` and JSON Schema validator; add fixtures for invalid manifest, unknown emotion text, missing recording identity, duplicate identity, revision conflicts, atomic-write failure, source-file immutability, and domain import boundaries. No FFmpeg renders in WU1.
7. Minimal backend `GET /api/v1/health` may return `{"status":"ok"}`. No other endpoint is authorized in WU1. Frontend may scaffold a four-route placeholder shell with no invented workflows or API payloads; `npm` toolchain/typecheck/Vitest smoke test if scaffolded.
8. CI checks: Python unit/contract tests, frontend typecheck/smoke if present, schema example checks and source immutability. A doctor capability checker can *report* FFmpeg availability but WU1 tests must not require FFmpeg.

## Contract governance
- `manifest-v2.schema.json` is the minimal input subset, not a normalized output schema.
- `override-store-v1.schema.json` and `api-error-v1.schema.json` are authoritative for their narrow WU1 use.
- API routes for import, previews, audio, render jobs, metadata and status remain **proposals** in doc 15 and 30; no implementation until their request/response schemas are approved in the corresponding work unit. Do not infer them from examples.
- JSON Schema is authoritative for persisted JSON. OpenAPI is generated from approved FastAPI routes. TS client types are derived from approved OpenAPI/JSON Schema, not sample JSON.
- Color mapping constants, description prose, hashtags, Short counts/names/default excerpts, render quality and output naming remain **deferred decisions**; no fabricated defaults in WU1.
- Single-user, one-process local storage only; no database, distributed locks, cloud services or background queues.

## WU1 acceptance gate
- All WU1 schemas parse and positive/negative fixtures pass.
- Typed validation and errors covered; no fabricated recording IDs or audio observations.
- Atomic store passes stale-revision, failure-injection, reload and source-preservation tests.
- Domain import boundaries verified.
- Optional health and frontend shell smoke/typecheck pass if scaffolded.
- Exact commands, pass/fail/skip counts, changed files, platform and known limitations reported.
- No modifications to `legacy_v2`; no render/media feature implementation; stop for approval before WU2.

## Decisions deliberately NOT claimed resolved
Cross-process locking/Windows atomicity; normalized rich-album adapter field mapping; full API contracts; specific color/description/Short defaults. These are NOT blockers for the narrowly scoped WU1 and must be resolved before their dependent units.
