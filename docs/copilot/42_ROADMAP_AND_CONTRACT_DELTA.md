# 42 — Integration roadmap and contract delta register

**Status:** Approved product-level ownership, WU4 architecture and Phase 2R technical contracts; **no Phase 2R code implementation authorized**. Existing Phase 1 and Phase 2A working-tree candidates must be preserved and verified. Doc 46 is the technical authority for Phase 2R implementation planning. Existing WU3A/WU3B acceptance gates and Docs 31, 38–40 take precedence for render behavior.

## Existing foundation versus planned additions

| Capability | Existing documented/implemented candidate | New design requirement | Earliest proposed owner / gate |
| --- | --- | --- | --- |
| Secure manifest-backed album project, immutable sources, timeline, render jobs | WU1–WU3B; Docs 32–40 | flexible project registry and inventory | WU4 Phase 2R; renderer input remains strict |
| Four-screen React UI | Phase 2A working-tree candidate | functional Import and production Review integration | WU4 Phase 2R/2B |
| Waveform and primary Short region | Phase 2A UI plus Phase 1 deterministic backend candidate | backend persistence and optional validated alternates | WU4 Phase 2B; analyzer suggestions only when available |
| Revisioned overrides and explicit Save | Existing foundation and WU4 spec | autosave, undo/redo, history, approval separation | WU4 baseline; autosave/history separate approval |
| Static/motion FFmpeg previews | WU3/WU3B candidate | approximate instant composition preview | WU4 approximate descriptor contract; authoritative preview remains backend |
| Image-based video composition | WU3A/WU3B candidate | MP4, playlists, independent visual timing, transitions | separately gated WU8 renderer generation (approved roadmap allocation; contract pending) |
| Metadata drafts and approval | WU5 specification | automatic generation on import, preserve edits | WU5 backend; WU4 pending indicator only |
| Render UI and Shorts | WU6 planned | batch selections, profiles, incremental reuse | WU6 baseline; extended batch/profile contracts later |
| Advanced layered visual editing | WU7 planned | independent MP4 effect toggles, future full timeline | WU8 for MP4 source effects; WU7 remains layered composition |
| Publishing | deferred | eventual upload/distribution | future separate unit |

## WU4: unified Import and Review scope

Build one trusted project registry and inventory pipeline with optional manifest enrichment; do not expose “legacy” and “flexible” modes. Preserve Phase 1 manifest-backed normalization as an enrichment/renderer adapter and preserve Phase 2A components. Phase 2R delivers registration, bounded secure discovery, rescanning, capability-aware resources and a functional Import handoff. Phase 2B completes Review, WaveSurfer, backend-owned stable Short state, explicit Save/conflicts and existing WU3/WU3B preview integration. Do **not** implement new MP4 encoding, video playlists, arbitrary batch scheduling, WU5 metadata, WU6 final Shorts/render planning, WU7 layered editing, or procedural rendering as a side effect.

## WU5: metadata

Extend Docs 19/23/24/26 generation and approval flows so import can trigger draft creation once the WU5 service is available. Canonical vs platform-specific metadata must remain distinct; no silent overwrite of edited/approved fields. Use WU3A timeline/chapters. Review template wording and defaults before implementation.

## WU6: render and queue

Complete baseline integrated render/Short UX against the existing lifecycle. Propose an additive multi-select/batch planner with deduplication and verified-only incremental artifact reuse; preserve output namespace, exact profile/renderer identity and one-worker initial concurrency. Any new output profile or Short rendering path requires explicit contract review and tests.

## WU8: visual-source extensions (separate future gate)

Plan a versioned source abstraction for still images, MP4 and ordered clips; per-clip media reference, trim, playback speed, loop/freeze policy, transitions, effect chain, audio/visual timeline relationship, and inherited settings. Existing WU3A/WU3B generations remain immutable. An MP4 source or optical-flow mode must never be represented as already supported. MP4/playlists are assigned to WU8 to keep WU7's existing layered composition scope manageable. Optical-flow interpolation is deferred.

## Contract status and remaining approvals

Already approved for the Phase 1/2A candidates, subject to test evidence: trusted roots and manifest-backed catalog; normalized album read/validation; WAV Range lifecycle; deterministic primary Short identity/fallback/short-track rule; typed editor state with explicit Save/revision conflicts; and the React toolchain baseline.

Approved for Phase 2R in Doc 46: registry v2 and migration; asset identity/fingerprint/relink; overlap policy; recursive scan exclusions/budgets/cancellation; format capability allowlist; secure audio/image/thumbnail resources; inventory/editor concurrency; session-only workflow handoff; Import runtime separation; generated frontend transport types/shared fixtures; and WU6 solid-background renderer ownership. Application implementation remains separately gated.

Still pending in later work units: genre-preset mappings; motion-preview HTTP lease lifecycle; authoritative 9:16 Shorts; metadata schemas/generation; batch planning/queue control; advanced layered/procedural rendering; imported-video timelines/playlists; and final WU3A/WU3B acceptance evidence.

## Gate discipline

For each contract, Codex must: cite the relevant source document and repository code; classify as already implemented, specified only, newly design-approved, or blocked; propose minimal additive contract and tests; identify impacted files; request human approval before implementation. Do not silently turn examples into normative schemas. No dependencies installed, code executed, or repo edits in a documentation-only review.

## Accepted review refinements and non-goals

- **WU4 explicit Save is mandatory baseline**; local unsaved undo/redo may be implemented with a reducer. Autosave and durable version history require separate approved contracts.
- **WU7** retains advanced still-image layered/title-aware/parallax composition. **WU8** owns imported video media, trusted snapshots, probing, frame/timing semantics, playlists, transitions, MP4 effects and new renderer/output identities. WU8 must not mutate historical WU3A/WU3B generations.
- **WU6** owns batch planning over the existing single worker, deduplication, collision review, and verified-only reuse; not a parallel scheduler.
- **WU5** owns metadata generation on import once its backend exists; WU4 may only show a truthful pending/unavailable indicator.
- **Historical Phase 0 blockers:** trusted catalog; album read/validation HTTP; WAV Range resource; typed editor state/inheritance; primary Short identity/fallback/approval; editor GET/PUT conflict behavior; motion-preview HTTP; frontend toolchain/test policy. Phase 0 approved the first six plus the frontend baseline sufficiently for the Phase 1/2A candidates; motion-preview HTTP remains Phase 3. Doc 44 records exact disposition. Phase 2R adds a new contract gate described in Doc 46.
- Current implemented-state observations and screenshot staleness are recorded in Doc 44. No tests or source changes are authorized by these documentation updates.

## Approved Phase 2R sequence

Phase 2A retained UI → Phase 2R.0 documentation/contracts → Phase 2R.1 registry migration, inventory, enrichment and rescan → Phase 2R.2 secure media resources/capabilities → Phase 2R.3 functional Import UI → Phase 2B production Review → Phase 3 motion-preview HTTP → Phase 4 hardening/acceptance. Each implementation phase requires its own approval and executable evidence.
