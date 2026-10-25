**CURRENT v2.0 AUTHORITY:** The active sequence is WU1 → WU2 → WU3 → WU3A → WU4 → WU5 → WU6. Docs 32 and 38 control the current graph; Docs 34–37 record completed WU2/WU3 implementation. Historical Streamlit, legacy-adapter, legacy-CLI, and claims that WU2/WU3 implemented final video are obsolete. Do not renumber WU4–WU6.

> **v1.3 authoritative override:** React + TypeScript + Vite + Tailwind + WaveSurfer.js frontend; FastAPI backend; docs live in `docs/copilot/`. Any earlier Streamlit or Python-only UI guidance in this document is superseded by `15_FRONTEND_ARCHITECTURE.md`, `16_UI_UX_SPECIFICATION.md`, and `17_UI_WIREFRAMES.md`. Do not implement Streamlit.

# Implementation plan — gated work units

**Copilot: complete one work unit at a time.** Before edits, report files read, exact intended changes, dependencies and tests. After each unit, show changed files, commands run, test results, unresolved risks; wait for authorization before next unit. Do not commit unless user asks.

## WU0 — inspect and baseline (no code edits)
Read all docs and `legacy_v2/wrld_youtube_compiler/{build_video.py,README.md,manifest.example.json}`. Inspect the repository without execution, identify compatibility issues, and report the plan and blockers. **Historical gate:** user approval was required before WU1.

## WU1 — foundations (completed history)
Typed domain/application skeleton, minimal structural manifest validation, stable identity validation, revisioned atomic override storage, typed errors, fake ports, tool reporting, and tests. No legacy adapter or product renderer was implemented; Docs 32–33 are authoritative.

## WU2 — media infrastructure and synthetic proof (completed history)
Implemented FFprobe/FFmpeg process infrastructure, immutable jobs, one-worker lifecycle, staging/promotion, verification, cancellation, recovery, and synthetic-media proof only. It did not implement album/track/Short product export. Docs 34–36 control its historical scope.

## WU3 — authoritative still preview and color (completed history)
Implemented deterministic color resolution, secure artwork snapshots/cache, authoritative FFmpeg stills, shared admission, and backend preview HTTP. It did not implement MP4 export, React UI, motion effects, or final album/Short rendering. Doc 37 is the historical implementation record.

## WU3A — Video Export (next)
Implement the approved Doc 38 phases: accept an explicit album-project directory; securely resolve portable relative inputs within it; publish only beneath its `output/`; implement the locked product render contracts; derive exact album/track timelines and chapters; render static-image album and individual-track H.264/AAC MP4s through the existing lifecycle; add the approved headless PowerShell entry point; run unit/contract/fault/real-media tests; then, after separately approved source-manifest preparation, render, decode, and manually review the real *Echoes of Asia* album. Do not hardcode the current drive/user/library/channel/album, create or relocate the primary album folder, or depend on the repository location. Do not read, validate, migrate, modify, or generate `youtube_metadata.json`. No frontend, Shorts composition, advanced effects, metadata authoring, or upload. **Gate:** every Doc 38 acceptance criterion, including human playback, passes.

## WU4 — React Import and Review
Implement React Import/Review, album ingestion/adaptation, WAV access, WaveSurfer region selection/audition, WU3 Original/Split/Treated previews, and revisioned overrides. Add the future album-initialization/selection workflow beneath configurable music-library roots, without treating the current `WORLD_MUSIC`, `WRLD-FI`, drive, or user path as fixed; selectable libraries and multiple channels must remain possible. Consume WU3A project-boundary validation/timeline services; do not rebuild album/track encoding. Motion preview and deferred effects require their own approved contracts. Tests cover project selection/containment, import identity, preview ownership, region behavior, conflicts, and save/reload.

## WU5 — Metadata review and export
Implement Metadata Table/Detail, deterministic description drafts, approved override preservation, batch validation, explicit approval, and the revisioned `output/metadata/youtube_metadata.json` publishing-content export. Explicitly import legacy/root draft metadata with provenance when approved; never overwrite it in place. Consume WU3A `chapters.txt`/render timeline; do not re-probe audio or maintain a second timeline. Persist portable album-project-relative references where paths are needed; do not leak machine-specific library roots into publishing metadata. No YouTube upload or `youtube_publish_state.json` creation.

## WU6 — Integrated Render UX and release readiness
Implement approved render-job HTTP contracts and React Render screen, preflight/confirmation, polling/heartbeat/reconnection/cancel UX, output presentation, full Shorts under `output/shorts/`, thumbnails/metadata integration, packaging, profiling, and final POC end-to-end acceptance. Pass the selected album-project identity/boundary through trusted backend composition, consume the WU3A artifact catalog/output layout, and never accept arbitrary browser-supplied server paths or reverse-engineer artifacts from filenames. Revalidate WU3A album/track export through the integrated path; do not postpone first real video export to WU6. Upload automation and ownership of `youtube_publish_state.json` remain future work. **Gate:** complete POC acceptance checklist.

## Explicit deferments
Music Analyzer integration, Suno download automation, publishing APIs, music DSP mastering, generative visuals, custom video editor, A/B versions, story-scene system, multi-album batch jobs, cloud services.

## Historical v1.1 hardening gates (reconciled by the current unit definitions above)
- **WU0:** explicitly reconcile proposed schema with legacy v2 and existing canonical album data. Identify what cannot be inferred. No code edits.
- **WU1:** ship versioned JSON schema, model/adapter contract tests, revision-safe atomic overrides, Python packaging/lock strategy, `scripts/doctor.py`, and test markers/CI. Do not claim full canonical WRLD-FI adapter support until mapped from actual files.
- **WU2:** immutable job snapshot, deterministic artifact fingerprint, one-worker scheduler, `.partial.mp4` staging, post-render validation before atomic promotion, safe retries/reconciliation, cancellation and JSONL logs; include failure injection and real FFmpeg integration tests.
- **WU3:** approved golden visual frames with controlled baseline, audio content regression for excerpts, preview/final parity and effect bounds.
- **WU3A:** product render contract; exact audio timeline; static album/track MP4; chapter output; lifecycle reuse; Windows/Ubuntu media tests; real-album automated and human acceptance.
- **WU4:** conflict-safe override persistence, stale manifest handling, preview cache invalidation, bounded preview generation, and Playwright waveform/import/review tests.
- **WU5:** chapter/description consumption, Table/Detail metadata editing, batch validation, approval and export tests.
- **WU6:** interrupted/restarted integrated jobs, full Shorts and artifact set, Windows manual checks, resource profiling, packaging, docs and explicit final evidence.

For every unit, stop after reporting changed files, commands actually run, pass/fail/skip counts, known gaps and request authorization. See `10`–`13` for normative contracts. No unit may advance solely on an unverified claim of success.

## Historical v1.2 boundary gates (retain architecture intent; current allocation controls)
- **WU0:** report a proposed ports-and-adapters layout and current boundary violations; no edits.
- **WU1:** create domain/application boundaries, ports and fakes, typed versioned request/result models, and contract tests. Do not build HTTP, queues, Docker, or Analyzer imports.
- **WU2–WU5, including WU3A:** keep all media and UI logic behind the defined ports/use cases. Test equivalent interfaces against shared application contracts where both exist.
- **WU6:** prove one complete local vertical slice and document, but do not implement, future service adapters.
The POC remains a separate repository; never modify Music Analyzer as part of these work units.


## v1.4 task update
Treat metadata review as a distinct implementation slice **after** waveform selection and **before** final end-to-end acceptance. Add custom picker and HEX validation to visual settings work; do not implement only preset swatches. Add draft generation/override merge, title/description validation, chapter derivation, metadata export and Playwright tests to the metadata slice. Add C01–E01 from document 20 to completion gates. WU0 must reconcile earlier seven-unit numbering before implementing; no silent skipping of new scope.


## v1.5 work-unit requirements
WU0 must report legacy anti-pattern risks, error envelope, local scratch vs final artifact stores, proxy/authoritative preview split, batch metadata UX, and test coverage. WU1 must add typed errors and contract fixtures. Visual work unit must implement the two-tier preview. Metadata work unit must implement Table/Detail and batch validation. Keep one FFmpeg worker; defer distributed infrastructure.

## v1.6 WU0 and sequencing update
WU0 MUST inspect documents 00–26, `AGENTS.md`, moved assets and schema, rich sample and original legacy v2; report the adapter gap between rich and minimal manifests and reconcile the older auto-color enum guidance. WU1 SHOULD first define tested input adapters/validation, provenance, recording-ID join rules, generated-draft vs approved-override persistence contracts, and deterministic color/description resolver interfaces **before** frontend-dependent features. Do not silently broaden an approved work unit; present implementation plan and request authorization. No Redis, PostgreSQL, S3, or distributed worker requirements in local POC.

## v1.7 authoritative implementation sequencing correction
Older WU4/WU5 references to Streamlit are **obsolete and must not be implemented**. Use React + FastAPI as locked in 15/31. WU0 was no-execution inspection only. The active approved graph is now WU1 → WU2 → WU3 → WU3A → WU4 → WU5 → WU6; Doc 38 controls the inserted unit and preserves the later numbering. Include 27–31 gates in their reconciled later units. Missing schemas or exact route contracts remain blocked decisions, not license to improvise.
