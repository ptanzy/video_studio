# Contracts, schemas, and backward compatibility — v1.1

## Authority and boundaries
- Canonical WRLD album JSON is **read-only**. `manifest.json` is the Studio input; `render_overrides.json` stores bounded user edits; a frozen `job_snapshot.json` is the effective render input; `render_report.json` is generated output, never configuration.
- Python-only orchestration and FFmpeg subprocess rendering. The UI calls application services, not FFmpeg directly. No .NET, Docker, distributed queue, database, or GPU requirement in POC.
- All new manifests have `schema_version: "2.0"`; overrides have `schema_version: "1.0"`. Reject unknown major versions with actionable errors. Legacy v2 adaptation is **explicit and loss-aware**, never a silent rewrite. Legacy formats need inspection before a complete adapter can be specified.
- Source paths are relative to the manifest directory. Resolved inputs must be existing regular files; forbid output paths aliasing source inputs; do not interpolate paths/titles into shell strings (use subprocess argument arrays).

## Validation contract
- Add versioned JSON Schemas under `schemas/`. `schemas/manifest-v2.schema.json` defines structural validation; typed Python models perform cross-field checks requiring media probes (e.g., end_seconds <= probed duration).
- Stable unique track and Short IDs, track ordering, finite numbers, supported color profiles, nonnegative fades, bounded settings, valid files, safe paths. Do not silently coerce or clamp invalid stored values. UI widgets can constrain user input.
- Validation is a standalone command: `python -m wrld_video validate path/to/manifest.json`; it must emit human-readable errors and nonzero exit on failure. WU1 may implement this CLI without a complete renderer.
- JSON schema and typed models must agree. Unit tests validate the shipped example, reject invalid examples, and round-trip normalized models without losing supported fields. Include contract tests for every consumer.
- The existing canonical WRLD-FI album format is **not** equivalent to the simple v2 video manifest. Implement its adapter only after inspecting representative real examples and agreeing on field mapping; unknown fields must be preserved in canonical source (which is never edited) and missing render-critical values reported.

## Override compatibility and conflict policy
- Store `base_manifest_sha256` (SHA-256 of raw source manifest bytes) and `revision` (nonnegative integer) with overrides. Record editor `updated_at` in UTC for diagnostics, not for conflict resolution.
- On load, mismatched base hash blocks rendering with overrides; show rebase/reset options. No silent application.
- On save, compare the last-read revision/hash with on-disk values; reject stale edits with a conflict message and reload path. Only one authoritative writer per project. A cross-process lock may be needed if two Studio processes target one folder; document platform-safe implementation and test it.
- Write to same-directory temp file, flush and fsync, then `os.replace`; ensure cleanup of temp on exception. Preserve old valid file on serialization/write failure. Platform-specific directory fsync is best-effort, not a guarantee on every Windows filesystem.
- Snapshot effective configuration and input fingerprints before rendering. Workers never write the manifest or overrides.

## Artifact identity
- Output identity is a deterministic digest of effective configuration, source media fingerprints, tool/preset versions, and render-relevant settings. Initial implementation may hash source bytes for correctness; if optimization uses stat-based fingerprints, label them non-cryptographic and invalidate conservatively.
- The job snapshot must record source manifest hash, override revision, media fingerprints, tool versions and expected output IDs. Never treat a matching filename as proof of matching content.

## v1.2 contract separation
Add explicit typed/versioned input manifest, optional analyzer metadata sidecar, immutable render request, and render result. Use stable recording identity and validate portability of relative paths. Contract tests must cover missing optional analysis metadata and legacy adapters. See doc 14.

## v1.6 contract locations and adaptation
Minimal machine-readable schema: `contracts/schemas/manifest-v2.schema.json`. Rich illustrative integration input: `docs/examples/metadata_contract.example.json`. They are **not** declared structurally interchangeable; use an adapter, explicit versions and contract tests. Keep canonical, analysis, overrides, drafts, frozen job snapshots and report separate; see 24.
