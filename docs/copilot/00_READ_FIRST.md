**v1.8 WU1 AUTHORITY:** Before implementing WU1, read `32_WU0_RESOLUTION_AND_WU1_BASELINE.md` and `33_WU1_CONTRACT_EXAMPLES_AND_TESTS.md`. Their narrow WU1 scope overrides conflicting earlier unit definitions. `legacy_v2` is read-only; WU0 involves no execution.

> **v1.3 authoritative override:** React + TypeScript + Vite + Tailwind + WaveSurfer.js frontend; FastAPI backend; docs live in `docs/copilot/`. Any earlier Streamlit or Python-only UI guidance in this document is superseded by `15_FRONTEND_ARCHITECTURE.md`, `16_UI_UX_SPECIFICATION.md`, and `17_UI_WIREFRAMES.md`. Do not implement Streamlit.

# WRLD Video Studio — Copilot documentation index

**Status:** design/specification handoff, not an implemented Studio. The bundled `legacy_v2/` is a historical CLI baseline and does not implement the UI, mood grading, waveform, progress, or animation.

## Reading order
1. `01_PRODUCT_SCOPE.md` — purpose, non-goals, acceptance criteria
2. `02_ARCHITECTURE.md` — modules, contracts, data flow
3. `03_MANIFEST_AND_STATE.md` — schema and migrations
4. `04_UI_AND_PREVIEW.md` — three-screen editor, carousel, waveform region selection
5. `05_RENDERING_AND_MEDIA.md` — FFmpeg, video effects, timings, packaging
6. `06_TEST_STRATEGY.md` — installation, test tiers, fixtures, CI and coverage
7. `07_IMPLEMENTATION_TASKS.md` — staged work units and completion gates
8. `08_RISKS_AND_DECISIONS.md` — important decisions and edge cases
9. `09_COPILOT_PROMPT.md` — ready-to-paste instruction

## Copilot operating rule
Read all nine docs and the legacy v2 source before coding. Report contradictions, architecture, dependencies, and Work Unit 1 plan. Do not implement until the user authorizes a work unit. Preserve working CLI behavior; develop UI as a thin client of shared services. Never overwrite source WAV/artwork or canonical WRLD-FI album JSON.

## Deliverable intent
A Windows-first local app that ingests an album, reviews track and Short previews, lets the user audition and drag/rescale excerpt regions, and renders a YouTube-ready compilation + Shorts + artwork + metadata. No YouTube uploads in POC.

## v1.2 required reading
Read `14_MICROSERVICE_READY_ARCHITECTURE.md` after document 13. It is normative for repository separation, ports/adapters, contract boundaries, and explicit POC deferments. Do not treat microservice-ready as permission to deploy microservices.


## Mandatory v1.3 reading order
Read **all** `docs/copilot/00_READ_FIRST.md` through `17_UI_WIREFRAMES.md` in numeric order. Inspect `ui-reference/index.html` and screenshots. During WU0 identify outdated Streamlit references and plan their removal. Do not implement until WU0 review is approved.


## Mandatory v1.4 addendum
Read **18_CUSTOM_COLOR_TREATMENTS.md**, **19_YOUTUBE_METADATA_REVIEW.md**, and **20_V14_ACCEPTANCE_AND_TEST_MATRIX.md** after 17. Four screens now: Import, Review, Metadata, Render. The custom color picker and editable YouTube text are required POC features. The v1.4 documents supersede conflicting earlier guidance. During WU0 list all outdated references and proposed corrections; do not modify files without approval.

## Mandatory v1.6 addendum — latest authority
Read **all** numbered files `00`–`26` in order, including `24_METADATA_INGESTION.md`, `25_COLOR_RESOLUTION.md`, and `26_DESCRIPTION_GENERATION.md`. See root `AGENTS.md`. Repository assets are now under `docs/ui/`, rich sample under `docs/examples/`, and machine schema under `contracts/schemas/`. Earlier `ui-reference/`, `schemas/`, or 3-screen references are historical. **Four screens**: Import → Review → Metadata → Render. Rich metadata is optional and must be adapted, not directly assumed to satisfy the minimal manifest schema. WU0 remains inspect/report only; do not implement without approval.

## v1.7 mandatory reading
Read `AGENTS.md` and 27–31 as normative supplements. Conflicts in earlier Streamlit guidance and WU0 execution wording are explicitly superseded by 07 v1.7 and 31. No unapproved invention; report blocked decisions.
