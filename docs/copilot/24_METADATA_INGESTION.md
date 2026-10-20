# 24 — Metadata ingestion and enrichment (v1.6 normative)

## Purpose and ownership
The Video Studio MUST accept a minimal Video Studio manifest and SHOULD ingest richer WRLD creative album JSON and optional Music Analyzer observations. The example at `docs/examples/metadata_contract.example.json` is an **illustrative superset**, not a mandatory input schema. The machine-validated minimal manifest remains `contracts/schemas/manifest-v2.schema.json` (migrated from the v1.5 `schemas/` location). The rich example MUST NOT be validated as if it were the minimal manifest without explicit adaptation.

Do not make Video Studio depend on the Analyzer, a live LLM, or a fixed emotion vocabulary. Preserve source data and trace provenance. Original Suno prompt/negative prompt and lyrics are creative intent, **not** acoustic measurements. Do not infer exact file metadata from prompts.

## Four independent inputs / records
1. **Canonical creative album JSON**: album/track identity, titles, scenes, story, visual palette, Suno prompts, optional authored publishing text. Immutable input.
2. **Analyzer sidecar** (optional): observations and excerpt candidates keyed by stable `recording_id`, with analysis version/confidence. Immutable input.
3. **Video Studio editor overrides**: user-edited Short regions, color choices, approved titles/descriptions; atomic, revisioned, editable. Never write into canonical or Analyzer inputs.
4. **Generated drafts / immutable job snapshot / render report**: separate versioned artifacts. Generated defaults are replaceable; approved edits are not.

## Import pipeline
- Read and schema-validate supported input format; detect format via `schema_version` and explicit adapter, not by guessing individual fields.
- Normalize to internal Album/Track models. Preserve stable album, track, Short and recording identities; never use array index as recording identity.
- Resolve paths relative to the source manifest, with safe filesystem access; verify WAV and artwork; FFprobe exact duration/sample rate/channels; never trust a declared duration as measured truth.
- Merge Analyzer data **only** by verified recording ID. Unknown IDs, duplicate IDs, conflicting identity or stale analysis => warning and quarantine rather than silent association.
- Preserve nullable unknown fields. `mood_text` and scene prose are unrestricted UTF-8 strings. Missing numeric energy/tension/brightness/valence/arousal remain null. Validate supplied numbers finite and within [0,1]; do not invent values.
- Normalize source `track_number`/`number`, `file`/`audio.path`, `artwork`/`assets.artwork_path` through explicit adapter rules. Reject unresolved required identity, audio or artwork.
- Expose an import review: original value, normalized value, source, validation severity, and any fallback. Let the user correct missing required fields before proceeding; don't silently fabricate them.
- Store provenance for every generated/normalized value (`source`, `algorithm_version`, `confidence` if meaningful, `reason`). Deterministic output for identical input/configuration.

## Precedence and staleness
- Audio properties: actual probed file > any asserted source metadata.
- Creative text: explicit user-authored album JSON > generated default; Analyzer observations must not overwrite creative intent.
- Presentation: approved editor override > explicit presentation preference > derived default > safe fallback.
- Publishing text: approved override > supplied publishing source > template-generated draft. Distinguish *supplied* from *approved*: supplied text is editable and review still required.
- When input fingerprint changes, flag potentially stale overrides and require explicit rebase/reset, preserving previous versions; never silently discard user edits.

## Example and test fixtures
Use `docs/examples/metadata_contract.example.json` as a rich example. Also test the actual `WRLD_FI_S01_A08_THE_CASTLE_ABOVE_THE_FOG.json` as a **separate adapter fixture when supplied to the repository**; do not embed proprietary/personal source files into tests without consent. Unit fixtures must cover missing Analyzer sidecar, free-form emotions, partial tracks, absent numeric fields, mismatched recording IDs, duplicate IDs, invalid paths, and supplied description overrides.

## Scope
This document specifies a future ingestion adapter; it does not claim v1.5 code already supports the rich example. WU0 should reconcile contracts; implementation only after authorization.
