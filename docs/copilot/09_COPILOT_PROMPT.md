> **v1.3 authoritative override:** React + TypeScript + Vite + Tailwind + WaveSurfer.js frontend; FastAPI backend; docs live in `docs/copilot/`. Any earlier Streamlit or Python-only UI guidance in this document is superseded by `15_FRONTEND_ARCHITECTURE.md`, `16_UI_UX_SPECIFICATION.md`, and `17_UI_WIREFRAMES.md`. Do not implement Streamlit.

# Copy-paste prompt for GitHub Copilot

You are implementing the WRLD Video Studio POC in this repository. **Do not begin coding yet.** First read every document in `docs/` in numerical order and inspect `legacy_v2/wrld_youtube_compiler/` (or the existing root implementation if already integrated).

Report: (1) documents found; (2) architecture and scope; (3) legacy v2 behavior and compatibility risks; (4) the precise next-work-unit files, contracts, dependencies and tests; (5) how source manifests, overrides, and render reports remain distinct; (6) testing setup for Windows and CI; (7) contradictions or blockers. Do not install packages, change files, or execute code until I explicitly authorize the stated work unit.

When authorized, implement **only** the approved work unit from `07_IMPLEMENTATION_TASKS.md`. Use small, testable modules and keep existing CLI behavior working. Add tests with every feature. Run the relevant test suite and report commands/results. Do not modify my music or canonical WRLD-FI album JSON. Do not commit without permission.

The POC must ultimately provide ordered album compilation; portrait Shorts with track-relative timestamps; thumbnails and descriptions; approved visual effects; a React carousel with bounded settings; and a draggable/resizable WaveSurfer Short selector that auditions only the selected track excerpt. It uses Python + FFmpeg locally and produces validated ready-to-upload files. WU3A implements only the static album/track subset in Doc 38; later units retain UI, full Shorts and advanced effects. No direct uploads, DAW, AI-generated video, scene stories, or A/B workflow.

## v1.1 addendum — mandatory
Also read docs `10_CONTRACTS_AND_COMPATIBILITY.md` through `13_ENVIRONMENT_AND_DELIVERY.md` before reporting. Treat them as normative where earlier docs are underspecified. Explicitly assess schema-version compatibility, override concurrency, immutable job snapshots, idempotent output promotion, restart reconciliation, cancellation, structured logs, FFprobe/audio/visual regression tests, and reproducible Windows setup. Do not add Docker, .NET or a distributed queue. During WU0 inspect only; do not install, execute, edit, or commit. Stop for user authorization after each work unit.

## v1.2 addendum — microservice-ready, not microservices
Read `docs/14_MICROSERVICE_READY_ARCHITECTURE.md`. Treat its dependency direction and contract requirements as normative. The POC lives in its own repo and must not import or modify Music Analyzer. Implement a modular domain/application/infrastructure/interface architecture with ports and adapters; approved CLI, HTTP and React adapters call shared use cases. Maintain versioned file/JSON boundaries and metadata sidecars. Do **not** add a public/remote API, distributed queues, Docker, .NET, TypeScript media orchestration, or other deployment infrastructure without explicit approval.


## v1.3 explicit instruction
Implement a React/TypeScript frontend and FastAPI backend, NOT Streamlit. Treat `15`, `16`, `17` and `docs/ui/` as authoritative for later UI work, subject to the v2.0 work-unit allocation below.


## v1.4 Copilot instruction (latest authority)
Read docs/copilot/00–20 in order and `docs/ui/index.html`, plus the checked-in reference screenshots. The target product uses a four-screen React + TypeScript frontend, custom color picker/HEX input, metadata editor with generated defaults and persistent overrides, a thin FastAPI adapter, and standalone Python render engine. Follow documents 18–20 for contracts and test gates. Implement only the currently approved unit; the v2.0 allocation below controls sequencing.


## v1.5 authoritative constraints — read LAST
Read `21_ARCHITECTURE_AND_ERROR_CONTRACTS.md`, `22_PREVIEW_AND_COLOR_REGRESSION.md`, and `23_BATCH_METADATA_EDITOR.md`. Do not import/call/copy the legacy v2 monolithic builder, do not implement Streamlit, do not introduce Redis/PostgreSQL/S3/Docker/distributed workers for this POC, and do not let frontend components call FFmpeg. Implement a typed error envelope and storage boundaries. The UI must provide approximate immediate color feedback and authoritative server previews, plus a Table/Detail batch metadata review. Prototype buttons may simulate transitions but must never claim a real render, upload, or save. For WU0: inspect only; propose work-unit changes and test commands; STOP before edits or execution.

## v1.6 Copilot instruction (takes precedence)
Read `AGENTS.md`, `docs/copilot/00_READ_FIRST.md` and all docs 01–26. Inspect `docs/ui/`, `docs/examples/metadata_contract.example.json`, `contracts/schemas/manifest-v2.schema.json`, and read-only `legacy_v2/`. **Do not implement or execute anything in WU0.** Report contradictions and a phased plan. Do not copy/import legacy v2 procedural code, require enum moods, guess audio measurements, overwrite canonical JSON, require a live LLM, or overwrite approved descriptions. Treat the rich example as an adapter input, not an already-valid minimal manifest.

## v1.7 strict anti-invention instruction
Follow `AGENTS.md` and document 31. Do not implement Streamlit or copy legacy monolith. No undocumented defaults, invented API fields, emotion enums, placeholder approvals, color rules, upload functionality or distributed services. If ambiguous, return `BLOCKED DECISION` with source references and options; wait for approval. Treat examples as examples, not validation schemas.

## v2.0 next-work-unit instruction
WU1–WU3 are implemented history. Read Docs 32–38 and actual source/tests; implement no code until an exact WU3A plan and Doc 38 Section 15 decisions are approved. WU3A is a headless static-image album/track MP4 slice reusing the existing worker/process/admission/artifact lifecycle. It must finish with real *Echoes of Asia* automated verification and human playback review. Do not start WU4, add frontend code, copy legacy v2, construct an independent FFmpeg path, or invent schemas/settings/rounding/names/CLI syntax.
