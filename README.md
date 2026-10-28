# WRLD Video Studio — Copilot handoff v2.4

**Start here:** `AGENTS.md`, `docs/copilot/00_READ_FIRST.md`, `docs/copilot/31_SPEC_AUTHORITY_AND_DECISION_REGISTER.md`, `docs/copilot/38_WU3A_VIDEO_EXPORT_SPECIFICATION.md`, `docs/copilot/39_WU3B_CORE_MOTION_AND_AUDIO_VISUALIZATION.md`, and `docs/copilot/40_WU3B_VISUAL_REFINEMENT_PHASE_A.md`. WU1–WU3 are implemented historical units. **WU3A — Video Export has an implementation candidate; final acceptance remains pending** until the real *Echoes of Asia* album and one full track pass automated verification and human playback review. WU3B Phases 1–4 and the additive visual-refinement/player generations are implementation candidates. The Phase D label-free player presentation has durable human acceptance; remaining WU3B and repository-closure gates stay distinct from WU3A.

## Current roadmap and capability status

Completed/history sequence: **WU1 → WU2 → WU3 → WU3A implementation candidate**. Approved forward sequence: **WU3B → WU4 → WU5 → WU6 → WU7**.

- Implemented: WU1 foundations; WU2 synthetic media/job infrastructure; WU3 authoritative still preview/color backend.
- Implemented candidate: headless WU3A album/track static-background export, versioned contracts, secure project-relative loading, sample-frame timeline/chapters, strict BT.709 H.264/AAC encoding, full-decode verification, lifecycle integration, durable progress/private diagnostics, recovery, and project-local technical artifacts. Short real-media export passes on the pinned Windows FFmpeg/FFprobe 9.0.2 build; real-album acceptance is still pending.
- Implemented candidate: additive WU3B flat-image pan/zoom, RMS bars, sample-timeline progress, refined motion-v2, player-v1, and private production-path previews. Remediation adds bounded excerpt preprocessing, a four-flight capacity, conservative orphan reconciliation, path/diagnostic hardening, Unicode glyph validation, and composited-footer contrast enforcement.
- Human verification: the October 27, 2026 Phase D label-free player presentation is accepted for the reviewed 30-second three-track artifact. This does not imply acceptance of later visible changes or close WU3A.
- Not yet implemented: the WU4 React Import/Review workflow, the WU5 Metadata workflow, the WU6 integrated Render UX/release gate, or WU7 advanced visual composition.
- WU3A human verification: WU3A will not be complete until the real *Echoes of Asia* album and a full track are rendered, automatically verified/decoded, and manually reviewed in VLC or Windows Media Player. No accepted full-album artifact exists yet.
- Deferred beyond WU3B: full Shorts composition, layered/title-aware/parallax/atmospheric effects and composition UI (WU7), frontend render orchestration, and YouTube upload (which remains outside the POC).

Doc 38 remains the WU3A contract and acceptance authority. Docs 34–37 remain the accurate WU2/WU3 implementation records.

## Historical v1.6 handoff context

The repository began as a design/specification handoff for a local Windows-first POC: React + TypeScript + Vite + Tailwind + WaveSurfer.js, FastAPI + Python domain/application + FFmpeg. WU1–WU3 are now implemented as described above; the React workflow remains future work. The intended UI flow is **Import → Review → Metadata → Render**. No upload service is in the POC.

## Getting started
1. Work in this repository; do not recreate it from the historical handoff package.
2. Read root `AGENTS.md`, `docs/copilot/00_READ_FIRST.md`, every numbered specification through 39, and the actual source/tests before proposing WU3B changes.
3. Browse `docs/ui/index.html` for the interactive design reference and screenshots; inspect `docs/examples/metadata_contract.example.json` for the rich illustrative metadata payload.
4. `contracts/schemas/manifest-v2.schema.json` is the **minimal manifest** validation contract; the rich example is an adapter input, not directly interchangeable with it.

## Documentation layout
- `docs/copilot/` — normative work-unit, UI, backend, test and contract specs (00–39).
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
