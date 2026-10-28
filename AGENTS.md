# WRLD Video Studio — agent operating contract (v2.4)

**STOP: Read `docs/copilot/00_READ_FIRST.md`, all numbered specs `00`–`40`, `docs/copilot/31_SPEC_AUTHORITY_AND_DECISION_REGISTER.md`, `docs/copilot/38_WU3A_VIDEO_EXPORT_SPECIFICATION.md`, `docs/copilot/39_WU3B_CORE_MOTION_AND_AUDIO_VISUALIZATION.md`, `docs/copilot/40_WU3B_VISUAL_REFINEMENT_PHASE_A.md`, `README.md`, `CHANGELOG.md`, schemas, examples, UI reference and legacy v2 before proposing changes.**

## No invented requirements
Never invent data fields, enum values, route paths, palette mapping, output naming, thresholds, metadata copy, render settings or acceptance criteria. Distinguish **approved requirement**, **safe implementation detail**, **deferred feature**, and **blocked decision** in reports. If specs conflict or a product choice is missing, STOP, cite both sources, offer options, ask user. Do not quietly choose. Examples are not schemas; `docs/ui/index.html` is a reference prototype, not app source. Never infer measurements from a Suno prompt. Never treat free-form emotion as an enum. Do not fabricate Short selections or user approvals.

## Scope and stack
Local standalone single-user POC. React + TypeScript + Vite + Tailwind + WaveSurfer.js frontend; thin FastAPI HTTP adapter; Python application/domain with FFmpeg/FFprobe infrastructure; filesystem storage and one worker. No Streamlit, Express production server, C# backend, Redis, Postgres, S3, Docker requirement, AI dependency, cloud service, YouTube upload or distributed workers. Legacy v2 read-only reference; do not import/copy its architecture.

## Gate
WU0 is inspect/report ONLY: no edits, installs or implementation execution. For each later work unit: cite exact requirements, list planned files/contracts/tests and open decisions, obtain user approval before editing; implement only approved scope; show actual test evidence and stop. Do not commit unless asked. Use `docs/copilot/31_SPEC_AUTHORITY_AND_DECISION_REGISTER.md` for precedence and required report.


## v1.8 WU1 override
Read `docs/copilot/32_WU0_RESOLUTION_AND_WU1_BASELINE.md` and `33_WU1_CONTRACT_EXAMPLES_AND_TESTS.md` as the authoritative WU1 scope. They supersede contradictory older WU1 instructions (including Streamlit, legacy adapter, legacy CLI regression renders, and a full API/UI implementation). Do not implement later-unit features in WU1.

## Historical WU3A work-unit override
WU1–WU3 are historical completed implementation units. WU3A — Video Export is governed by `docs/copilot/38_WU3A_VIDEO_EXPORT_SPECIFICATION.md`; it was inserted after WU3 and before the later UI units. The eight WU3A contract decisions are approved. WU3A accepts an explicit album-project directory and publishes only beneath that project's `output/`; never hardcode a development-repository path, drive, username, library root, channel, or album. Follow the approved schemas, output profile, chapter rounding, image-fit policy, output naming, and CLI syntax in Doc 38. WU3A must not read, validate, migrate, modify, or generate any `youtube_metadata.json`. The v2.2 section below controls the current next unit.

## v2.2 WU3B roadmap override

WU3A now has an implementation candidate but remains **IMPLEMENTED — ACCEPTANCE PENDING** under Doc 38. The approved forward sequence is **WU3B → WU4 → WU5 → WU6 → WU7**. Doc 39 controls WU3B's approved small scope: one flat image, optional bounded pan/zoom, amplitude/RMS bars, sample-timeline track progress, and private rendered motion previews. WU3B Phases 1–4 are implemented candidates; acceptance remains separate from WU3A and still requires human visual review. WU7 owns layered/title-aware/atmospheric composition and its dedicated editor.

## v2.3 visual-refinement gate

Doc 40 records the Phase A proposal for organic RMS variation, bar/glow/color controls, an automatically contrasting progress rail, additive versioning, and WU4's approximate composition descriptor. It does not change motion-v1 authority. Do not add or modify schemas, domain models, FFmpeg behavior, preview execution, or React UI for this refinement until the user explicitly approves the applicable Doc 40 decisions and Phase B or later phase.

## v2.4 Phase D override

The approved sequence is Phase A design → Phase B motion-v2 implementation → Phase C real-artwork validation/architecture review → Phase D visual refinement and player overlay → WU4 React composition editor. Phase B and the additive Phase D backend implementation are candidates in the working tree. Phase D authorizes only the player contracts/rendering recorded in Docs 31, 39, and 40, including label-free compact metadata through `wrld-player-presentation/1.0`; human visual acceptance remains pending. Do not begin WU4, publishing, or WU7 composition work without a separate gate.
