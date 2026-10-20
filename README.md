# WRLD Video Studio — Copilot handoff v1.8

**Start here:** `AGENTS.md`, `docs/copilot/00_READ_FIRST.md`, then `docs/copilot/32_WU0_RESOLUTION_AND_WU1_BASELINE.md`. WU1 is foundation-only. See `33_WU1_CONTRACT_EXAMPLES_AND_TESTS.md` for fixtures and tests. The remaining numbered specifications document later units and historical decisions.

# WRLD Video Studio — Copilot Handoff v1.6

**Design/specification handoff; not an implemented application.** Local Windows-first POC: React + TypeScript + Vite + Tailwind + WaveSurfer.js, FastAPI + Python domain/application + FFmpeg. Workflow: **Import → Review → Metadata → Render**. No upload service in the POC.

## Getting started
1. Copy the **contents** of this handoff directory into the root of a new `wrld-video-studio` Git repository (do not nest the outer folder).
2. Give Copilot the root `AGENTS.md` and ask for **Work Unit 0 only**. It must read `docs/copilot/00_READ_FIRST.md` and every numbered specification through 26 before implementation.
3. Browse `docs/ui/index.html` for the interactive design reference and screenshots; inspect `docs/examples/metadata_contract.example.json` for the rich illustrative metadata payload.
4. `contracts/schemas/manifest-v2.schema.json` is the **minimal manifest** validation contract; the rich example is an adapter input, not directly interchangeable with it.

## Documentation layout
- `docs/copilot/` — normative work-unit, UI, backend, test and contract specs (00–26).
- `docs/ui/` — HTML prototype and PNG mockups.
- `docs/examples/` — rich metadata contract example.
- `contracts/schemas/` — machine-readable minimal manifest schema.
- `examples/` — render overrides and API error examples.
- `legacy_v2/` — read-only historical CLI reference; **do not copy architecture**.
- `docs/architecture/` — reserved for durable ADRs and architecture diagrams.

## New in v1.6
Separate creative/analysis/editor/generated records; explicit adapter and identity joins; arbitrary mood text; deterministic album-palette color resolution with explainable fallback; offline YouTube draft generation with approval and manual override preservation. See docs 24–26 and `CHANGELOG.md`.

**Important:** Existing v1.5 documents contain historical statements (e.g., Streamlit, three screens, enum mood profiles, old paths). Later versioned addenda and documents 24–26 take precedence. WU0 must report remaining contradictions rather than silently assume them away.

## v1.7 implementation guardrails
Read root `AGENTS.md` and `docs/copilot/31_SPEC_AUTHORITY_AND_DECISION_REGISTER.md` first. New docs 27–30 define UI validation/comparison, ingestion identity/schema authority, mocks/tests and heartbeat behavior. The POC is local, single worker, React/FastAPI; never invent undefined product decisions.
