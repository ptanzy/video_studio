> **v1.3 authoritative override:** React + TypeScript + Vite + Tailwind + WaveSurfer.js frontend; FastAPI backend; docs live in `docs/copilot/`. Any earlier Streamlit or Python-only UI guidance in this document is superseded by `15_FRONTEND_ARCHITECTURE.md`, `16_UI_UX_SPECIFICATION.md`, and `17_UI_WIREFRAMES.md`. Do not implement Streamlit.

# Copy-paste prompt for GitHub Copilot

You are implementing the WRLD Video Studio POC in this repository. **Do not begin coding yet.** First read every document in `docs/` in numerical order and inspect `legacy_v2/wrld_youtube_compiler/` (or the existing root implementation if already integrated).

Report: (1) documents found; (2) architecture and scope; (3) legacy v2 behavior and compatibility risks; (4) the precise WU1 files, contracts, dependencies and tests; (5) how source manifests, overrides, and render reports remain distinct; (6) testing setup for Windows and CI; (7) contradictions or blockers. Do not install packages, change files, or execute code until I explicitly authorize WU1.

When authorized, implement **only** the approved work unit from `07_IMPLEMENTATION_TASKS.md`. Use small, testable modules and keep existing CLI behavior working. Add tests with every feature. Run the relevant test suite and report commands/results. Do not modify my music or canonical WRLD-FI album JSON. Do not commit without permission.

The POC must ultimately provide: ordered album compilation; portrait Shorts with track-relative timestamps; thumbnails and descriptions; subtle mood color, blurred portrait fill, continuous slow zoom, optional grain, progress, compact reactive bars immediately left of title; Streamlit carousel with bounded settings; and a draggable/resizable Wavesurfer Short selector that auditions only the selected track excerpt. It must use Python + FFmpeg locally and produce validated ready-to-upload files. No direct uploads, no DAW, no AI-generated video, no scene stories, no A/B workflow.

## v1.1 addendum — mandatory
Also read docs `10_CONTRACTS_AND_COMPATIBILITY.md` through `13_ENVIRONMENT_AND_DELIVERY.md` before reporting. Treat them as normative where earlier docs are underspecified. Explicitly assess schema-version compatibility, override concurrency, immutable job snapshots, idempotent output promotion, restart reconciliation, cancellation, structured logs, FFprobe/audio/visual regression tests, and reproducible Windows setup. Do not add Docker, .NET or a distributed queue. During WU0 inspect only; do not install, execute, edit, or commit. Stop for user authorization after each work unit.

## v1.2 addendum — microservice-ready, not microservices
Read `docs/14_MICROSERVICE_READY_ARCHITECTURE.md`. Treat its dependency direction and contract requirements as normative. The POC lives in its own repo and must not import or modify Music Analyzer. Implement a modular domain/application/infrastructure/interface architecture with ports and adapters; CLI and Streamlit call shared use cases. Maintain versioned file/JSON boundaries and metadata sidecars. Do **not** add HTTP APIs, distributed queues, Docker, .NET, TypeScript orchestration, or other deployment infrastructure without explicit approval. In WU0 report architecture and tests only; do not execute or edit.


## v1.3 explicit instruction
Implement a React/TypeScript frontend and FastAPI backend, NOT Streamlit. Treat `15`, `16`, `17` and `ui-reference/` as authoritative for UI. For WU0 only: inspect, report discrepancies, propose revised work units and test commands; do not edit/install/execute until approved.


## v1.4 Copilot instruction (latest authority)
Read docs/copilot/00–20 in order and `ui-reference/index.html`, plus all four mockup screenshots. Implement React + TypeScript frontend with four screens, custom color picker/HEX input, metadata editor with generated defaults and persistent overrides, FastAPI adapter, and standalone Python render engine. Follow documents 18–20 for contracts and test gates. Earlier instructions that forbid TypeScript/HTTP or require Streamlit are superseded. **WU0 inspection only until explicitly authorized**.


## v1.5 authoritative constraints — read LAST
Read `21_ARCHITECTURE_AND_ERROR_CONTRACTS.md`, `22_PREVIEW_AND_COLOR_REGRESSION.md`, and `23_BATCH_METADATA_EDITOR.md`. Do not import/call/copy the legacy v2 monolithic builder, do not implement Streamlit, do not introduce Redis/PostgreSQL/S3/Docker/distributed workers for this POC, and do not let frontend components call FFmpeg. Implement a typed error envelope and storage boundaries. The UI must provide approximate immediate color feedback and authoritative server previews, plus a Table/Detail batch metadata review. Prototype buttons may simulate transitions but must never claim a real render, upload, or save. For WU0: inspect only; propose work-unit changes and test commands; STOP before edits or execution.

## v1.6 Copilot instruction (takes precedence)
Read `AGENTS.md`, `docs/copilot/00_READ_FIRST.md` and all docs 01–26. Inspect `docs/ui/`, `docs/examples/metadata_contract.example.json`, `contracts/schemas/manifest-v2.schema.json`, and read-only `legacy_v2/`. **Do not implement or execute anything in WU0.** Report contradictions and a phased plan. Do not copy/import legacy v2 procedural code, require enum moods, guess audio measurements, overwrite canonical JSON, require a live LLM, or overwrite approved descriptions. Treat the rich example as an adapter input, not an already-valid minimal manifest.

## v1.7 strict anti-invention instruction
Follow `AGENTS.md` and document 31. Do not implement Streamlit or copy legacy monolith. No undocumented defaults, invented API fields, emotion enums, placeholder approvals, color rules, upload functionality or distributed services. If ambiguous, return `BLOCKED DECISION` with source references and options; wait for approval. Treat examples as examples, not validation schemas.
