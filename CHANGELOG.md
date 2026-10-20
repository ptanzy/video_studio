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
