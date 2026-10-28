**Historical v1.8 WU1 authority:** WU1 was governed by `32_WU0_RESOLUTION_AND_WU1_BASELINE.md` and `33_WU1_CONTRACT_EXAMPLES_AND_TESTS.md`. Their narrow scope remains the accurate WU1 history. `legacy_v2` is read-only; WU0 involved no execution.

**v2.4 CURRENT ROADMAP AUTHORITY:** WU1–WU3 are implemented history. WU3A has an implementation candidate but remains **IMPLEMENTED — ACCEPTANCE PENDING** under Doc 38. WU3B Phases 1–4 and the additive refinement/player generations are implementation candidates. The October 27, 2026 human review accepted the reviewed label-free Phase D player presentation; remaining WU3B gates and all WU3A full-album/full-track gates remain independent. Read Docs 31, 32, 34–40 and the actual source/tests. The approved forward sequence remains **WU3B closure → WU4 → WU5 → WU6 → WU7**. WU3B does not close or replace WU3A's real *Echoes of Asia* automated and human-playback acceptance.

> **v1.3 authoritative override:** React + TypeScript + Vite + Tailwind + WaveSurfer.js frontend; FastAPI backend; docs live in `docs/copilot/`. Any earlier Streamlit or Python-only UI guidance in this document is superseded by `15_FRONTEND_ARCHITECTURE.md`, `16_UI_UX_SPECIFICATION.md`, and `17_UI_WIREFRAMES.md`. Do not implement Streamlit.

# WRLD Video Studio — Copilot documentation index

**Status:** implementation repository plus specification handoff. WU1–WU3 are implemented; WU3A and WU3B have implementation candidates with their distinct acceptance gates pending; later units are not implemented. The bundled `legacy_v2/` remains a historical CLI baseline and does not define current architecture or acceptance.

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


## Historical v1.3 reading order
Read **all** `docs/copilot/00_READ_FIRST.md` through `17_UI_WIREFRAMES.md` in numeric order. The referenced prototype now lives at `docs/ui/index.html`. WU0 identified obsolete Streamlit references and involved no implementation.


## Mandatory v1.4 addendum
Read **18_CUSTOM_COLOR_TREATMENTS.md**, **19_YOUTUBE_METADATA_REVIEW.md**, and **20_V14_ACCEPTANCE_AND_TEST_MATRIX.md** after 17. Four screens now: Import, Review, Metadata, Render. The custom color picker and editable YouTube text are required POC features. The v1.4 documents supersede conflicting earlier guidance. During WU0 list all outdated references and proposed corrections; do not modify files without approval.

## Mandatory v1.6 addendum — latest authority
Read **all** numbered files `00`–`26` in order, including `24_METADATA_INGESTION.md`, `25_COLOR_RESOLUTION.md`, and `26_DESCRIPTION_GENERATION.md`. See root `AGENTS.md`. Repository assets are now under `docs/ui/`, rich sample under `docs/examples/`, and machine schema under `contracts/schemas/`. Earlier `ui-reference/`, `schemas/`, or 3-screen references are historical. **Four screens**: Import → Review → Metadata → Render. Rich metadata is optional and must be adapted, not directly assumed to satisfy the minimal manifest schema. WU0 remains inspect/report only; do not implement without approval.

## v1.7 mandatory reading
Read `AGENTS.md` and 27–31 as normative supplements. Conflicts in earlier Streamlit guidance and WU0 execution wording are explicitly superseded by 07 v1.7 and 31. No unapproved invention; report blocked decisions.

## Historical v2.0 reading and sequence
Read numbered Docs 32–38 after Docs 00–31. Docs 34–37 are historical WU2/WU3 implementation records; do not edit their claims to imply product video export. Doc 38 is the WU3A authority. The v2.0 sequence was WU1 → WU2 → WU3 → WU3A → WU4 → WU5 → WU6; the v2.2 section below supersedes only its successor ordering.

## v2.2 mandatory reading and sequence

Read Doc 39 after Doc 38. Doc 39 is the WU3B authority and supersedes the earlier post-WU3A sequence only where it explicitly does so. Forward sequence: WU3B → WU4 → WU5 → WU6 → WU7. Preserve all WU1–WU3A contracts and history; track WU3A acceptance independently. WU7 is planned advanced composition, not an implemented capability.

## v2.3 visual-refinement reading and gate

Read Doc 40 after Doc 39. It records an additive effects/profile-generation proposal and the Phase B–E plan. Existing `video-effects-v1`, motion-v1 profile/output/preview identities, WU3A static behavior, and WU7 ownership remain unchanged. Doc 40's exact identifiers, fields, numeric defaults, algorithms, and composition-descriptor architecture require explicit approval before implementation.
