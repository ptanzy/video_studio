**IMPORTANT v1.8:** The historical WU0–WU6 plan below is preserved as design history ONLY where it conflicts with `32_WU0_RESOLUTION_AND_WU1_BASELINE.md`. Do not implement its Streamlit, legacy adapter, legacy CLI regression, or legacy modularization steps. The v1.8 work-unit graph and WU1 acceptance gate are authoritative.

> **v1.3 authoritative override:** React + TypeScript + Vite + Tailwind + WaveSurfer.js frontend; FastAPI backend; docs live in `docs/copilot/`. Any earlier Streamlit or Python-only UI guidance in this document is superseded by `15_FRONTEND_ARCHITECTURE.md`, `16_UI_UX_SPECIFICATION.md`, and `17_UI_WIREFRAMES.md`. Do not implement Streamlit.

# Implementation plan — gated work units

**Copilot: complete one work unit at a time.** Before edits, report files read, exact intended changes, dependencies and tests. After each unit, show changed files, commands run, test results, unresolved risks; wait for authorization before next unit. Do not commit unless user asks.

## WU0 — inspect and baseline (no code edits)
Read all docs and `legacy_v2/wrld_youtube_compiler/{build_video.py,README.md,manifest.example.json}`. Inspect current repository, run baseline CLI tests if feasible, identify compatibility issues. Report plan and blockers. **Gate:** user approves WU1.

## WU1 — package, contracts, tests foundation
Create package skeleton, `pyproject.toml` or requirements, pytest config, lint config, Windows/Ubuntu CI, synthetic media fixtures, typed manifest models, legacy v2 adapter, timeline + path validation, explicit FFmpeg capability check. CLI legacy output remains functional. Unit tests for T01/T02/T03 logic/T04/T05 and smoke integration. No UI, waveform, filters, or new effects yet. **Gate:** all unit tests green and CLI regression render passes.

## WU2 — renderer modularization + verification
Move existing compilation/Short/artwork/metadata functions into shared modules; preserve v2 behavior. Add FFprobe verification, per-Short descriptions/CSV, dry-run, deterministic output paths and render report. Integration tests T03/T09/T10/T11/T12/T15.

## WU3 — visual profiles and motion
Implement named color profiles + auto mood fallback, blurred portrait fill, safe zoom/pan, subtle grain, progress bar, compact audio-reactive bars left of title. Shared filter graph for previews and final. Unit/integration and frame-diff/screenshot tests T07/T13/T14. Avoid gratuitous particles/fog in this POC.

## WU4 — Streamlit Import/Review/Render UI
Build 3-screen app; carousel and per-track/Short controls; static previews, on-demand 3–5 s motion previews; overrides saved atomically; apply-to-track/reset; render confirmation, progress and failures. Tests T08 and UI state smoke.

## WU5 — draggable waveform and audio audition
Integrate Wavesurfer Regions plugin (or equivalent) with Streamlit. Implement region drag, resize, multiple regions, accurate selected-audio playback stop, keyboard/numeric precision, save round-trip, fade audition and export settings. Component/browser tests T04/T05/T06 plus manual Windows test.

## WU6 — release readiness
Full end-to-end tests on synthetic 12-track album and small real local test set supplied by user; docs, packaging, safe overwrite behavior, output verification, Windows install instructions. No YouTube API/upload integration. **Gate:** POC acceptance checklist complete.

## Explicit deferments
Music Analyzer integration, Suno download automation, publishing APIs, music DSP mastering, generative visuals, custom video editor, A/B versions, story-scene system, multi-album batch jobs, cloud services.

## v1.1 mandatory hardening gates (supersede less-specific requirements above)
- **WU0:** explicitly reconcile proposed schema with legacy v2 and existing canonical album data. Identify what cannot be inferred. No code edits.
- **WU1:** ship versioned JSON schema, model/adapter contract tests, revision-safe atomic overrides, Python packaging/lock strategy, `scripts/doctor.py`, and test markers/CI. Do not claim full canonical WRLD-FI adapter support until mapped from actual files.
- **WU2:** immutable job snapshot, deterministic artifact fingerprint, one-worker scheduler, `.partial.mp4` staging, post-render validation before atomic promotion, safe retries/reconciliation, cancellation and JSONL logs; include failure injection and real FFmpeg integration tests.
- **WU3:** approved golden visual frames with controlled baseline, audio content regression for excerpts, preview/final parity and effect bounds.
- **WU4:** conflict-safe override persistence, stale manifest handling, preview cache invalidation, bounded preview generation.
- **WU5:** required Playwright tests for region dragging, resize, selected-only playback, track switch and save/reload.
- **WU6:** interrupted/restarted 12-track job, Windows manual checks, resource profiling, docs and explicit test evidence.

For every unit, stop after reporting changed files, commands actually run, pass/fail/skip counts, known gaps and request authorization. See `10`–`13` for normative contracts. No unit may advance solely on an unverified claim of success.

## v1.2 boundary gates (mandatory)
- **WU0:** report a proposed ports-and-adapters layout and current boundary violations; no edits.
- **WU1:** create domain/application boundaries, ports and fakes, typed versioned request/result models, and contract tests. Do not build HTTP, queues, Docker, or Analyzer imports.
- **WU2–WU5:** keep all media and UI logic behind the defined ports/use cases. Test UI/CLI parity.
- **WU6:** prove one complete local vertical slice and document, but do not implement, future service adapters.
The POC remains a separate repository; never modify Music Analyzer as part of these work units.


## v1.4 task update
Treat metadata review as a distinct implementation slice **after** waveform selection and **before** final end-to-end acceptance. Add custom picker and HEX validation to visual settings work; do not implement only preset swatches. Add draft generation/override merge, title/description validation, chapter derivation, metadata export and Playwright tests to the metadata slice. Add C01–E01 from document 20 to completion gates. WU0 must reconcile earlier seven-unit numbering before implementing; no silent skipping of new scope.


## v1.5 work-unit requirements
WU0 must report legacy anti-pattern risks, error envelope, local scratch vs final artifact stores, proxy/authoritative preview split, batch metadata UX, and test coverage. WU1 must add typed errors and contract fixtures. Visual work unit must implement the two-tier preview. Metadata work unit must implement Table/Detail and batch validation. Keep one FFmpeg worker; defer distributed infrastructure.

## v1.6 WU0 and sequencing update
WU0 MUST inspect documents 00–26, `AGENTS.md`, moved assets and schema, rich sample and original legacy v2; report the adapter gap between rich and minimal manifests and reconcile the older auto-color enum guidance. WU1 SHOULD first define tested input adapters/validation, provenance, recording-ID join rules, generated-draft vs approved-override persistence contracts, and deterministic color/description resolver interfaces **before** frontend-dependent features. Do not silently broaden an approved work unit; present implementation plan and request authorization. No Redis, PostgreSQL, S3, or distributed worker requirements in local POC.

## v1.7 authoritative implementation sequencing correction
Older WU4/WU5 references to Streamlit are **obsolete and must not be implemented**. Use React + FastAPI as locked in 15/31. WU0 is no-execution inspection only; earlier wording allowing baseline test execution is superseded. Before WU1, produce an updated WU1–WU6(+ metadata slice) dependency graph and acceptance checklist for user approval. Do not silently reorder or add scope. Include 27–31 gates: UI comparison and batch validation; recording identity/fingerprints and schema authority; mocked HTTP and Playwright; polling/heartbeat and reconnection. Missing schemas or exact route contracts are blocked decisions, not license to improvise.
