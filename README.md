# WRLD Video Studio — Copilot handoff v2.7

**Start here:** `AGENTS.md`, `docs/copilot/00_READ_FIRST.md`, `docs/copilot/31_SPEC_AUTHORITY_AND_DECISION_REGISTER.md`, `docs/copilot/38_WU3A_VIDEO_EXPORT_SPECIFICATION.md`, `docs/copilot/39_WU3B_CORE_MOTION_AND_AUDIO_VISUALIZATION.md`, `docs/copilot/40_WU3B_VISUAL_REFINEMENT_PHASE_A.md`, and Docs 41–51. WU1–WU3 are implemented historical units. **WU3A — Video Export has an implementation candidate; final acceptance remains pending** until the real *Echoes of Asia* album and one full track pass automated verification and human playback review. WU3B and its additive renderer generations retain their separate acceptance gates. Docs 41–50 record the evolving WU4 contracts; Doc 51 is the approved WU5 Metadata authority. The uncommitted implementation candidates remain acceptance-pending.

## Current roadmap and capability status

Completed/history sequence: **WU1 → WU2 → WU3 → WU3A implementation candidate**. Approved forward ownership sequence: **WU3B closure → WU4 Import/Review → WU5 Metadata → WU6 Rendering/batch operations → WU7 advanced layered composition → WU8 imported video sources and clip playlists**.

- Implemented: WU1 foundations; WU2 synthetic media/job infrastructure; WU3 authoritative still preview/color backend.
- Implemented candidate: headless WU3A album/track static-background export, versioned contracts, secure project-relative loading, sample-frame timeline/chapters, strict BT.709 H.264/AAC encoding, full-decode verification, lifecycle integration, durable progress/private diagnostics, recovery, and project-local technical artifacts. Short real-media export passes on the pinned Windows FFmpeg/FFprobe 9.0.2 build; real-album acceptance is still pending.
- Implemented candidate: additive WU3B flat-image pan/zoom, RMS bars, sample-timeline progress, refined motion-v2, additive player presentation generations, and private production-path previews. Remediation adds bounded excerpt preprocessing, a four-flight capacity, conservative orphan reconciliation, path/diagnostic hardening, Unicode glyph validation, and composited-footer contrast enforcement.
- Human verification: the October 27, 2026 Phase D label-free player presentation is accepted for the reviewed 30-second three-track artifact. This does not imply acceptance of later visible changes or close WU3A.
- WU4 implementation candidates in the current working tree include catalog-v2 migration, flexible trusted-root registration, recursive private inventories, restart-safe bounded scan attempts, opaque audio/image resources, thumbnails, persistent exclusions, project-level Import handoff, durable Review/Creation planning, and Creation v4's native composition-owned Editor plus reusable Template Library. V4 makes each Album, Single, and Short own its complete visual configuration while templates remain reusable presets with optional historical provenance. Creation retains explicit revision-safe Save and conflict/indeterminate-save recovery. These changes are uncommitted, are not part of the stated HEAD, and still require manual UI acceptance.
- Implemented as uncommitted candidates but not yet accepted: Phase 2R flexible recursive ingestion, secure media resources, the session-only functional Import handoff, revision-safe WU4 Creation/Editor persistence, and the Doc 51 WU5 Metadata workflow. WU5 keeps source facts, editable publishing metadata, and Creation visuals separate; supports explicit revision-safe initialization/reconciliation/Save and target approval; and exports an explicitly selected valid set atomically. Not yet implemented: authoritative WU3-backed preview execution from the WU4 Editor, the WU6 integrated Render/batch UX, WU7 advanced layered composition, or WU8 imported-video/clip-playlist rendering.
- WU3A human verification: WU3A will not be complete until the real *Echoes of Asia* album and a full track are rendered, automatically verified/decoded, and manually reviewed in VLC or Windows Media Player. No accepted full-album artifact exists yet.
- Deferred beyond WU3B: full Shorts composition; layered/title-aware/parallax/atmospheric effects and composition UI (WU7); imported video sources and clip playlists (WU8); frontend render orchestration; and YouTube upload (which remains outside the POC).

Doc 38 remains the WU3A contract and acceptance authority. Docs 34–37 remain the accurate WU2/WU3 implementation records.

## Historical v1.6 handoff context

The repository began as a design/specification handoff for a local Windows-first POC: React + TypeScript + Vite + Tailwind + WaveSurfer.js, FastAPI + Python domain/application + FFmpeg. WU1–WU3 are now implemented as described above. The current working tree contains an evolving production-intended React candidate, but its backend integration and acceptance remain incomplete. The intended UI flow is **Import → Review → Metadata → Render**. No upload service is in the POC.

## Getting started
1. Work in this repository; do not recreate it from the historical handoff package.
2. Read root `AGENTS.md`, `docs/copilot/00_READ_FIRST.md`, every numbered specification through 51, and the actual source/tests before proposing changes.
3. Browse `docs/ui/index.html` for the interactive design reference and screenshots; inspect `docs/examples/metadata_contract.example.json` for the rich illustrative metadata payload.
4. `contracts/schemas/manifest-v2.schema.json` is the **minimal manifest** validation contract; the rich example is an adapter input, not directly interchangeable with it.

## Run the local Import and Review application

From the repository root, start the backend in one ordinary PowerShell window. Supply one or more explicit trusted music-library roots; no drive, username, channel or album is hardcoded:

```powershell
.\.venv\Scripts\python.exe -m wrld_video_studio serve-import `
  --project-root "C:\path\to\your\music-library" `
  --ffmpeg-path "C:\path\to\ffmpeg.exe" `
  --ffprobe-path "C:\path\to\ffprobe.exe" `
  --port 8000
```

In a second PowerShell window:

```powershell
Set-Location .\frontend
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to the loopback-only backend at `127.0.0.1:8000`. Application state is private per-user state by default; registered source folders and media are never relocated or modified.

## Documentation layout
- `docs/copilot/` — historical/normative work-unit, UI, backend and test specifications plus product-design records. Docs 45–46 govern flexible ingestion, Doc 49 records the historical v2 visual contract, revised Doc 50 governs Creation v4 composition-owned visuals and reusable presets, and Doc 51 governs WU5 Metadata. Acceptance remains separate from implementation.
- `docs/ui/` — HTML prototype and PNG mockups.
- `docs/examples/` — rich metadata contract example.
- `contracts/schemas/` — approved machine-readable contracts, including private WU5 editor state and portable WU5 export schemas.
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

## WU3A video export

WU3A adds the first product album/individual-track MP4 pipeline before further frontend work. It accepts an explicit album-project directory, resolves portable project-relative inputs inside that security boundary, and publishes generated artifacts beneath that album's `output/` directory without depending on the repository location. It reuses the WU2 worker/process/artifact lifecycle and WU3 render admission, adds an immutable product render contract, static-image H.264/AAC export, exact audio-derived timeline and YouTube chapter output, a supported headless PowerShell entry point, real-media tests, and mandatory *Echoes of Asia* album plus full-track acceptance. It does not add React UI, Shorts composition, advanced animation/effects, upload, publishing-metadata processing, or album-folder initialization. Doc 38 Section 15 records the approved schemas/profile/image/timeline/naming/CLI/title choices. The current Echoes manifest is now `wrld-video-album/1.0`, contains approved stable album/track IDs and exact current artwork paths, and passes the implemented WU3A schema and secure source-resolution checks.

### WU3A headless export

From the repository root in ordinary Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m wrld_video_studio video-export --album-project "C:\path\to\album" --target album --profile youtube-1080p30-v1
.\.venv\Scripts\python.exe -m wrld_video_studio video-export --album-project "C:\path\to\album" --target track --track-id "stable-track-id" --profile youtube-1080p30-v1
```

When the verified tools are not on `PATH`, add both absolute overrides:

```powershell
--ffmpeg-path "C:\path\to\ffmpeg.exe" --ffprobe-path "C:\path\to\ffprobe.exe"
```

The command has no output-path or replacement switch. It writes verified media beneath the selected album project's `output/`, writes only `chapters.txt` and `render_report.json` in `output/metadata/`, emits throttled durable phase progress to stderr, reserves stdout for the final JSON result, and returns nonzero on validation, rendering, verification, cancellation, collision, or publication failure. Failed-attempt diagnostics remain in private per-user application state; failed media is cleaned and not retained.
