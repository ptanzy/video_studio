# 44 — Independent review reconciliation and WU4 contract gates

**Status:** Historical Phase 0 decision record plus current reconciliation. This document is **not** a schema, API, implementation authorization, or evidence of passing acceptance. The reviewed branch remains `feature/wu4-composition-editor` at HEAD `2b25327d14c92e0a11c94c15d0e8f891b0496bb5`, but the working tree now contains uncommitted Phase 1 backend and Phase 2A frontend candidates. Do not describe those files as committed HEAD behavior.

## Accepted design dispositions

| Area | Disposition | Owner / gate |
| --- | --- | --- |
| Navigation | Keep Import, Review, Metadata, Render; no fake WU4 functionality | WU4 shell; WU5/WU6 functional destinations |
| Inheritance | Backend-owned typed effective-value resolver with provenance; reset deletes override | Separate typed contract; WU4 minimal needs gated |
| Shorts | One primary draft, optional alternative ranges, stable identity; exact fallback/approval unresolved | WU4 contract gate |
| Saving | Explicit Save and revision conflicts in WU4; local undo/redo; defer server autosave/history | WU4 baseline / later enhancement |
| Previews | Browser approximation clearly labeled; FFmpeg preview authoritative | WU4 adapter gate |
| Metadata | Automatic drafts only when WU5 implemented; approval independent | WU5 |
| Queue | One existing worker; deduplicated batch planner; verified-only reuse | WU6 |
| Advanced layers | Existing WU7 scope retained | WU7 |
| Imported MP4/playlists | Separately gated media/renderer generation, no WU4 creep | WU8 |
| Interpolation | Standard frame duplication/drop initially; optical flow deferred | WU8 future decision |

## Reconciled implementation-status matrix (working-tree candidates; must be tested)

| Capability | Status at Codex-reviewed HEAD |
| --- | --- |
| React/Vite/Tailwind/WaveSurfer four-screen UI | Phase 2A candidate present; interactive Import/Review and tests, but production persistence/integration incomplete |
| Project catalog | Phase 1 manifest-backed candidate present; flexible manifestless registration not implemented |
| Album read and validation | Phase 1 normalized v1–v4 candidate and HTTP routes present |
| WU4 HTTP routes | Project roots/catalog/register/relink/remove, album, validation, editor state and WAV audio candidates present |
| WAV Range/audio HTTP | Phase 1 candidate present; other audio formats not approved |
| Revisioned editor state | Typed Phase 1 GET/PUT candidate with explicit Save, source fingerprint and conflict semantics; no autosave/history |
| Primary Short initialization | Stable deterministic Phase 1 candidate present; frontend still uses temporary local IDs/defaults |
| Headless static/motion MP4 export | Implemented through services/CLI |
| Motion preview | Application service/CLI exists; HTTP adapter absent |
| Short editor and product Short renderer | Not implemented |
| Metadata generation/approval | Not implemented |
| MP4 visual inputs and playlists | Not supported |
| Batch planner and UI | Not implemented |
| Verified artifact reuse | Exists for current album/track generations |

WU3A/WU3B acceptance remains subject to the live gate; a corrected Phase D presentation must not be treated as accepted without human review of its actual pixels.

## Historical eight Phase 0 blockers and disposition

1. **Catalog/project roots:** approved and implemented as a manifest-backed Phase 1 candidate. Phase 2R registry v2/migration is a new pending gate.
2. **Album read/validation:** approved and implemented candidate for manifest v1–v4 normalization.
3. **WAV Range:** approved and implemented candidate. Additional formats/resources remain pending.
4. **Typed editor state/inheritance:** approved and implemented candidate; Phase 2R asset references require additive review.
5. **Primary Short:** approved deterministic start-zero/30-second rule, whole-short-track rule, under-five-second review block, stable identity and invalidation; implemented candidate. Analyzer alternatives remain optional/unimplemented.
6. **Editor GET/PUT/conflicts:** approved and implemented candidate with explicit Save. Server autosave/history remain deferred.
7. **Motion-preview HTTP:** not implemented; remains Phase 3.
8. **Frontend baseline:** Phase 2A package/tooling/tests candidate present. API type synchronization and E2E policy remain incomplete.

Do **not** infer or invent schema fields, numeric defaults, endpoints, renderer generation names, or accepted work-unit completion from this list.

## Current delivery sequence

1. Phase 2A retained interactive frontend candidate.
2. Phase 2R.0 documentation reconciliation and proposed contracts.
3. Phase 2R.1 registry migration, recursive inventory, optional manifest enrichment and rescan.
4. Phase 2R.2 secure media resources, thumbnails and capability reporting.
5. Phase 2R.3 functional Import UI integration.
6. Phase 2B production Review integration.
7. Phase 3 motion-preview HTTP integration.
8. Phase 4 accessibility, migration/security/regression hardening and acceptance.

## Legacy reference status

`docs/ui/import.png`, `docs/ui/review.png`, `docs/ui/render.png` and the interactive prototype are historical design references. Codex identified a three-entry nav, two default Shorts, film grain and unimplemented render outputs in screenshots. Do not treat these images as current acceptance criteria; refresh them in a dedicated UI-design pass once the approved contracts are reflected.

## Review boundary

The original documentation integration added Docs 41–44 without application changes. Subsequent authorized work produced uncommitted Phase 1 and Phase 2A candidates. Phase 2R.0 reconciled their documentation status and added Docs 45–46 without modifying application source or executable schemas. Doc 46 is now approved; Phase 2R.1 remains blocked only on a separate implementation authorization and exact implementation plan.
