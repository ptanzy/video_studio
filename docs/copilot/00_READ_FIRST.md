**Historical v1.8 WU1 authority:** WU1 was governed by `32_WU0_RESOLUTION_AND_WU1_BASELINE.md` and `33_WU1_CONTRACT_EXAMPLES_AND_TESTS.md`. Their narrow scope remains the accurate WU1 history. `legacy_v2` is read-only; WU0 involved no execution.

**v2.7 CURRENT ROADMAP AUTHORITY:** WU1–WU3 are implemented history. WU3A has an implementation candidate but remains **IMPLEMENTED — ACCEPTANCE PENDING** under Doc 38. WU3B and its additive refinement/player generations retain their separate acceptance gates. Read Docs 31, 32, 34–46 and the actual source/tests. The approved forward ownership sequence is **WU3B closure → WU4 Import/Review → WU5 Metadata → WU6 Rendering/batch operations → WU7 advanced layered composition → WU8 imported video sources and clip playlists**. The current working tree contains an uncommitted consolidated WU4 Import/Review/Creation candidate authorized after Docs 45–46. It is not committed HEAD behavior and remains subject to acceptance evidence.

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

## v2.5 product-design integration addendum (documentation only)
Read Docs **41–44** after Doc 40. They record approved UX direction, work-unit ownership, UI mapping, and the WU4 implementation gate. **Do not treat them as authorization to implement new schemas, routes, MP4 support, autosave, or batch orchestration.** Docs 31 and 38–40 continue to govern existing technical contracts and acceptance. The four-screen structure remains Import → Review → Metadata → Render, with WU8 owning imported video sources and clip playlists.

## v2.6 WU4 flexible-ingestion architecture and Phase 2R.0

Read Docs **45–46** after Doc 44. Doc 45 is approved product architecture: one standard trusted-project ingestion path, bounded recursive asset discovery, optional manifest enrichment, and composition assignment downstream from Import. It does not make arbitrary folders valid WU3 render input. Doc 46 is the approved technical contract for registry, inventory, discovery, resources, migration and runtime separation. The planning order is Phase 2A → Phase 2R.0 → Phase 2R.1 → Phase 2R.2 → Phase 2R.3 → Phase 2B → Phase 3 → Phase 4. A later Functional Import authorization satisfied the Phase 2R.1–2R.3 implementation gates; the resulting uncommitted candidates remain acceptance-pending and do not authorize Phase 2B.

## v2.7 consolidated WU4 implementation

A later explicit authorization consolidated Import simplification, Review's Media/Creation/Editor workspaces, durable Creation planning and usability work without adding a fifth top-level screen. The additive `wrld-project-preferences/1.0`, `wrld-import-handoff/2.0` and `wrld-creation-state/1.0` contracts are implementation candidates. V1 handoffs, existing catalog/editor state, WU3 render identities and secure resource contracts remain supported. WU5–WU8 capabilities are still deferred to their owning work units.

## v2.8 WU4 template Editor reading

Read Docs 49–50 after Doc 46. Doc 49 governs `wrld-creation-state/2.0`, visual-template migration, dependencies, sharing and preview boundaries. Doc 50 adds the approved category, warning, explicit background-suggestion and shared-assignment UX. Phase 3 independent copies remain separately gated and WU6 retains Creation-template render admission.
