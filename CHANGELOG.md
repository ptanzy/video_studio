## Unreleased — WU3 final remediation
- Reconciles crash-interrupted export attempts before request-digest retry selection and makes synchronous CLI execution claim the exact submitted job/attempt, preserving historical diagnostics while preventing an older queued job from being reported as the requested export.
- Removes the Windows process-start/Job Object assignment race by launching children suspended, assigning the kill-on-close Job Object through the owned process handle, and resuming only after ownership succeeds. Structured internal diagnostics now identify the failing Win32 stage/code without weakening the public `PROCESS_OWNERSHIP_FAILED` contract.
- Tightens v4 result schema/runtime parity, adds deterministic Windows destination/staging preflight, and shortens application-owned staging/diagnostic keys without changing public output names.
- Bounds motion-preview PCM work to intersecting excerpt windows plus finite RMS analysis margin, caps distinct running/queued preview identities at four, preserves same-flight sharing, and adds conservative lock-based abandoned-preview reconciliation.
- Enforces newly approved 4.5:1 ordinary and 3:1 large-text contrast policy against the composited footer; derived colors may be corrected while noncompliant manual overrides are rejected.
- Adds Unicode glyph-coverage validation, observable diagnostic fallback, CLI shutdown error reporting, and Windows/Ubuntu WU3B/Phase D media capability coverage.
- Records October 27, 2026 human acceptance of the reviewed label-free Phase D presentation. WU3A full-album/full-track acceptance remains pending and independent.

## WU3A implementation candidate
- Adds versioned video manifest, export request/result, and render-report schemas plus contract tests.
- Adds secure album-project validation, attempt-owned input snapshots, normalized 48 kHz stereo PCM timelines, deterministic chapters, album/track H.264/AAC rendering, complete decode verification, collision-safe publication, revisioned reports, recovery, and the approved headless CLI.
- Integrates product exports through request-specific handlers on the existing single worker and shared render-admission lane; no second scheduler is introduced.
- Corrects static-image BT.709 conversion by selecting the BT.709 RGB-to-YUV matrix and assigning frame-level space/transfer/primaries while retaining strict encoder/probe checks. A short album and track passed against the approved local Gyan FFmpeg/FFprobe 9.0.2 build; no direct x264 VUI override was needed.
- Adds private versioned failure diagnostics and durable phase progress, plus throttled CLI stderr reporting with machine-readable final JSON preserved on stdout. Progress readers and writers are serialized so Windows file-sharing behavior cannot fail a render.
- Adds generated-media Windows/Ubuntu CI coverage. Real *Echoes of Asia* full-track/full-album rendering and human playback acceptance remain pending; the full album was not rerendered during this repair.
- Records that the current Echoes manifest was manually migrated to `wrld-video-album/1.0` and now passes the implemented schema/source checks. No application workflow rewrites album manifests.

## v2.0 — WU3A video-export roadmap alignment
- Inserts WU3A between completed WU3 and future WU4 without renumbering WU4–WU6.
- Defines WU3A as the first functional album/individual-track MP4 export unit, reusing the existing lifecycle, process ownership, staging, verification, cancellation, recovery, and shared admission infrastructure.
- Requires static-image H.264/AAC export, exact probed timeline, YouTube-compatible chapters, a supported headless PowerShell entry point, real-media CI, and full *Echoes of Asia* automated plus human playback acceptance.
- Moves first product video generation out of WU6 while retaining React Import/Review in WU4, Metadata review/approval in WU5, and integrated Render UX/Shorts/release acceptance in WU6.
- Records approval of all eight WU3A contract decisions: schemas, output profile, image fit, sample-derived chapters, deterministic collision-safe outputs, headless CLI, corrected acceptance artwork, and deferred generated typography. No WU3A implementation is claimed.
- Defines the caller-selected album directory as the WU3A project/security boundary, with portable manifest paths and generated artifacts under `<album-project>/output/`; the current `WORLD_MUSIC\WRLD-FI\Albums` convention is an acceptance default, not a hardcoded dependency.
- Locks the exact `output/{album,tracks,shorts,metadata}` contract, metadata ownership boundaries, versioned manifest/request/result/report contracts, one 1080p30 encoding profile, image-fit/timeline/chapter policies, collision-safe names/reuse, and the headless CLI. WU3A is forbidden from reading or producing `youtube_metadata.json`; no implementation is claimed.

## v1.8 — WU0 findings resolved for WU1
- Authoritative foundation-only WU1 scope and WU1–WU6 dependency graph.
- Clarified read-only legacy boundary and eliminated obsolete Streamlit/legacy WU1 acceptance requirements by explicit supersession.
- Added narrow machine-readable override store and API error schemas; defined identity validation and revision-safe persistence tests.
- Deferred full routes, rich adapter mappings, color/description constants, Short defaults and cross-process locking until their dependent units.
- Added Copilot implementation and acceptance guardrails; no application code added.

# Changelog

## v1.6 — Metadata ingestion and publishing contracts
- Retains all v1.5 documentation, legacy code, UI mockups and HTML prototype.
- Adds root `AGENTS.md` and numbered docs 24–26 covering adapter/identity joins, free-form emotion and deterministic palette resolution, offline YouTube metadata generation, review and approval.
- Includes rich example from the prior metadata-contract discussion under `docs/examples/metadata_contract.example.json`.
- Moves UI reference to `docs/ui/` and minimal JSON schema to `contracts/schemas/`; preserves render/API examples under `examples/`.
- Updates reading instructions, tasks, contracts, testing, UI, color and metadata docs with v1.6 precedence notes.
- Clarifies rich metadata example **does not directly conform** to the minimal manifest schema. No application implementation is included.

## v1.5 and earlier
See numbered `docs/copilot/` specs for earlier scope, architecture and acceptance requirements. v1.6 supersedes contradictory guidance only where explicitly noted.

## v1.7 — anti-invention and executable contract discipline
- Added docs 27–31: comparison/inline validation, idempotent ingestion/type authority, mock UI tests, render heartbeat/reconnection, and authoritative decision register.
- Replaced AGENTS.md with strict no-invention and approval-gated implementation policy.
- Clarified obsolete Streamlit and WU0 execution instructions; reinforced one-worker React/FastAPI scope.
- Expanded UI wireframe, Copilot prompt, architecture and test guidance.
- No app implementation or new schema is claimed; missing contracts are explicit WU0/WU1 decisions.
