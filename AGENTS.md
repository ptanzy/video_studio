# WRLD Video Studio — agent operating contract (v1.8)

**STOP: Read `docs/copilot/00_READ_FIRST.md`, all numbered specs `00`–`33`, `docs/copilot/31_SPEC_AUTHORITY_AND_DECISION_REGISTER.md`, `README.md`, `CHANGELOG.md`, schemas, examples, UI reference and legacy v2 before proposing changes.**

## No invented requirements
Never invent data fields, enum values, route paths, palette mapping, output naming, thresholds, metadata copy, render settings or acceptance criteria. Distinguish **approved requirement**, **safe implementation detail**, **deferred feature**, and **blocked decision** in reports. If specs conflict or a product choice is missing, STOP, cite both sources, offer options, ask user. Do not quietly choose. Examples are not schemas; `docs/ui/index.html` is a reference prototype, not app source. Never infer measurements from a Suno prompt. Never treat free-form emotion as an enum. Do not fabricate Short selections or user approvals.

## Scope and stack
Local standalone single-user POC. React + TypeScript + Vite + Tailwind + WaveSurfer.js frontend; thin FastAPI HTTP adapter; Python application/domain with FFmpeg/FFprobe infrastructure; filesystem storage and one worker. No Streamlit, Express production server, C# backend, Redis, Postgres, S3, Docker requirement, AI dependency, cloud service, YouTube upload or distributed workers. Legacy v2 read-only reference; do not import/copy its architecture.

## Gate
WU0 is inspect/report ONLY: no edits, installs or implementation execution. For each later work unit: cite exact requirements, list planned files/contracts/tests and open decisions, obtain user approval before editing; implement only approved scope; show actual test evidence and stop. Do not commit unless asked. Use `docs/copilot/31_SPEC_AUTHORITY_AND_DECISION_REGISTER.md` for precedence and required report.


## v1.8 WU1 override
Read `docs/copilot/32_WU0_RESOLUTION_AND_WU1_BASELINE.md` and `33_WU1_CONTRACT_EXAMPLES_AND_TESTS.md` as the authoritative WU1 scope. They supersede contradictory older WU1 instructions (including Streamlit, legacy adapter, legacy CLI regression renders, and a full API/UI implementation). Do not implement later-unit features in WU1.
