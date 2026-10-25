# WRLD Video Studio — Copilot handoff v2.0

**Start here:** `AGENTS.md`, `docs/copilot/00_READ_FIRST.md`, `docs/copilot/31_SPEC_AUTHORITY_AND_DECISION_REGISTER.md`, and `docs/copilot/38_WU3A_VIDEO_EXPORT_SPECIFICATION.md`. WU1–WU3 are implemented historical units. **WU3A — Video Export is the next work unit**; its contract decisions are approved and implementation is authorized for a subsequent implementation pass under the normal plan/report gate.

## Current roadmap and capability status

Sequence: **WU1 → WU2 → WU3 → WU3A → WU4 → WU5 → WU6**.

- Implemented: WU1 foundations; WU2 synthetic media/job infrastructure; WU3 authoritative still preview/color backend.
- Not yet implemented: product album/track MP4 export, the WU4 React Import/Review workflow, the WU5 Metadata workflow, and the WU6 integrated Render UX/release gate.
- Human verification: WU3A will not be complete until the real *Echoes of Asia* album is rendered, automatically verified/decoded, and manually reviewed in VLC or Windows Media Player. No such accepted album artifact exists yet.
- Deferred beyond WU3A: full Shorts composition, advanced motion/effects, frontend render orchestration, and YouTube upload (which remains outside the POC).

Doc 38 is the complete forward WU3A scope and dependency handoff. Docs 34–37 remain the accurate WU2/WU3 implementation records.

## Historical v1.6 handoff context

The repository began as a design/specification handoff for a local Windows-first POC: React + TypeScript + Vite + Tailwind + WaveSurfer.js, FastAPI + Python domain/application + FFmpeg. WU1–WU3 are now implemented as described above; the React workflow remains future work. The intended UI flow is **Import → Review → Metadata → Render**. No upload service is in the POC.

## Getting started
1. Work in this repository; do not recreate it from the historical handoff package.
2. Read root `AGENTS.md`, `docs/copilot/00_READ_FIRST.md`, every numbered specification through 38, and the actual source/tests before proposing WU3A changes.
3. Browse `docs/ui/index.html` for the interactive design reference and screenshots; inspect `docs/examples/metadata_contract.example.json` for the rich illustrative metadata payload.
4. `contracts/schemas/manifest-v2.schema.json` is the **minimal manifest** validation contract; the rich example is an adapter input, not directly interchangeable with it.

## Documentation layout
- `docs/copilot/` — normative work-unit, UI, backend, test and contract specs (00–38).
- `docs/ui/` — HTML prototype and PNG mockups.
- `docs/examples/` — rich metadata contract example.
- `contracts/schemas/` — machine-readable minimal manifest schema.
- `examples/` — render overrides and API error examples.
- `legacy_v2/` — read-only historical CLI reference; **do not copy architecture**.
- `docs/architecture/` — reserved for durable ADRs and architecture diagrams.

## New in v1.6
Separate creative/analysis/editor/generated records; explicit adapter and identity joins; arbitrary mood text; deterministic album-palette color resolution with explainable fallback; offline YouTube draft generation with approval and manual override preservation. See docs 24–26 and `CHANGELOG.md`.

**Historical note:** Earlier revisions contained Streamlit, three-screen, enum-mood, and old-path language. The current authority and sequence are stated at the top of this file and in Docs 31, 32, and 38; do not implement those obsolete alternatives.

## v1.7 implementation guardrails
Read root `AGENTS.md` and `docs/copilot/31_SPEC_AUTHORITY_AND_DECISION_REGISTER.md` first. New docs 27–30 define UI validation/comparison, ingestion identity/schema authority, mocks/tests and heartbeat behavior. The POC is local, single worker, React/FastAPI; never invent undefined product decisions.

## WU3 backend preview API

WU3 provides the programmatic FastAPI composition boundary for
`POST /api/v1/previews/still`. The endpoint accepts the strict
`preview-request-v1` JSON contract and returns `multipart/related` containing
the exact `preview-result-v1` JSON followed by the authoritative `image/png`.
It never accepts or returns local source, snapshot, cache, or executable paths.

Construct `PreviewApplicationConfig` with absolute server-owned artwork,
snapshot, cache, FFmpeg, and FFprobe locations; immutable artwork and Auto-color
registrations; and explicit preview/render/shutdown timeouts. Pass it to
`wrld_video_studio.interfaces.http.create_app`. The provided `serve(config,
port=...)` entry point always binds to `127.0.0.1`; there is no public bind,
CORS, authentication, or administration endpoint in WU3.

The runtime must be application-scoped so its source registry, secure cache,
single-flight coordinator, and process-local render admission have one lifespan.
Create WU2 workers through `PreviewApplicationRuntime.build_render_worker()` to
inject that same admission instance. The React Original/Split/Treated review
interface remains a WU4 deliverable; WU3 completion is backend-only.

## Next: WU3A video export

WU3A adds the first product album/individual-track MP4 pipeline before further frontend work. It accepts an explicit album-project directory, resolves portable project-relative inputs inside that security boundary, and publishes generated artifacts beneath that album's `output/` directory without depending on the repository location. It reuses the WU2 worker/process/artifact lifecycle and WU3 render admission, adds an immutable product render contract, static-image H.264/AAC export, exact audio-derived timeline and YouTube chapter output, a supported headless PowerShell entry point, real-media tests, and mandatory *Echoes of Asia* album plus full-track acceptance. It does not add React UI, Shorts composition, advanced animation/effects, upload, publishing-metadata processing, or album-folder initialization. Doc 38 Section 15 records the approved schemas/profile/image/timeline/naming/CLI/title choices. The corrected current artwork resolves the historical visible-title mismatch; the draft Echoes manifest still requires separately approved source preparation because it lacks stable IDs and references nonexistent unprefixed artwork names.
