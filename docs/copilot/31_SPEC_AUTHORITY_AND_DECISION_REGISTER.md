**v1.8 update:** `32_WU0_RESOLUTION_AND_WU1_BASELINE.md` approves a narrow WU1 *proposal* and specifies its contracts; `33_WU1_CONTRACT_EXAMPLES_AND_TESTS.md` provides normative fixtures. Earlier open decisions that do not affect WU1 remain deferred, not invitations to invent behavior. Obtain user approval before starting WU1.

**v2.1 update:** `38_WU3A_VIDEO_EXPORT_SPECIFICATION.md` is the specific authority for WU3A and for responsibilities transferred from WU4–WU6. WU1–WU3 implementation records remain historically accurate. WU3A's album-project boundary, project-local `output/` root, and all eight Section 15 decisions are approved, and an implementation candidate is present. The current *Echoes of Asia* artwork and manually migrated manifest pass the implemented structural/source checks. Final WU3A acceptance still requires real album/track automated evidence and human playback review.

# 31 — Specification authority, open decisions and Copilot anti-invention policy

## Authority and conflict handling
1. Explicit user-approved decisions documented in this handoff and current `AGENTS.md` govern scope.
2. Newer *specific* normative specifications (15–30) supersede older conflicting text in 00–14. For equal specificity, STOP and report conflict; do not select an interpretation by intuition.
3. Schemas/OpenAPI govern machine payload shape only when approved and checked in; examples and HTML prototypes are illustrative, not normative schemas.
4. Legacy v2 is a read-only behavior reference, not an implementation template.
5. If a requirement is not defined, classify it as **BLOCKED DECISION**, **SAFE IMPLEMENTATION DETAIL**, or **DEFERRED**. Never present assumptions as decisions.
6. For WU3A video export, Doc 38 supersedes older work-unit allocation but not the established lifecycle, media-integrity, preview, metadata, or UI contracts it explicitly retains.
7. WU3A receives an explicit album-project directory, treats it as the filesystem/security boundary, and publishes beneath its `output/`. The current `WORLD_MUSIC\WRLD-FI\Albums` hierarchy is a default convention for acceptance, not a locked drive/user/library/channel path. Future library-root selection and album initialization are later-workflow concerns.
8. For WU3B, Doc 39 supersedes older allocation of simple pan/zoom, audio-reactive bars, and rendered track progress. It does not supersede WU3A's static v1 contract or acceptance gate, and it does not authorize WU7's advanced composition scope.
9. Doc 40 is the specific Phase A proposal for WU3B visual refinement. It is not implementation authority and cannot mutate motion-v1 contracts. Any accepted refinement must be additive unless a separately approved migration explicitly changes a project generation.
10. The approved refinement sequence is Phase A design, Phase B motion-v2 implementation, Phase C real-artwork validation/architecture review, Phase D visual refinement and player overlay, then WU4 React. Phase D authorizes compact informational player typography, backend-owned reference geometry, metadata transitions, and artwork-derived themes only through the additive player generation recorded below. This does not authorize WU4 React or WU7 creative title/composition work.

## Decisions locked
- Local single-user POC; React + TS + Vite + Tailwind + WaveSurfer.js; thin FastAPI; Python domain/application; FFmpeg/FFprobe; one worker; filesystem scratch and final output separation.
- Screens: Import, Review, Metadata, Render. Batch metadata grid, per-output editor, color picker and authoritative before/after comparison.
- Canonical creative JSON and optional Analyzer sidecar read-only; stable recording ID; unrestricted emotion text; deterministic color resolution; no guessed numeric audio measurements.
- Draft publishing text may be generated offline from approved source material; manual overrides preserved; user approval before publishing export; no YouTube API/upload in POC.
- No cloud infrastructure, AI API dependency, distributed workers, new C# service, or Streamlit UI.

## Decisions that MUST be surfaced in WU0/WU1 before implementation
- Exact normalized manifest and overrides schema field names, versions and compatibility mapping (rich example is NOT schema).
- Exact HTTP route names, response envelopes and job schema; OpenAPI is generated only after route contract approval.
- Default palette selection and color mapping constants if not already explicit in doc 25; do not invent aesthetic mappings.
- Exact metadata template wording, default hashtags and link placeholders; show draft template for approval before hardcoding.
- Short count policy, naming and initial excerpt defaults when missing; do not fabricate approved selections.
- Cross-platform path/locking behavior and Windows test coverage; document unsupported cases.

## WU3A approval register

The user approved all eight Doc 38 Section 15 decisions: `wrld-video-album/1.0` plus video request/result/report schemas; the single `youtube-1080p30-v1` profile; contain-and-black-pad image fitting; sample-count timeline with floored UTF-8/LF YouTube chapters and no MP4 chapter embedding; the exact output tree/names/collision rejection and verified reuse policy; the `python -m wrld_video_studio video-export` interface; validation of the corrected *Echoes of Asia* artwork; and deferral of generated title typography/creative transforms. WU3A has no force-replace operation; a future work unit may propose an explicit controlled replacement contract.

WU3A exclusively generates and verifies MP4s plus `chapters.txt` and `render_report.json`. It must not read, validate, migrate, modify, or generate either the existing root-level or future output `youtube_metadata.json`, and it must not create `youtube_publish_state.json`. Publishing metadata remains WU5/future-publisher scope.

**Source-preparation gate resolved:** the user manually migrated the current Echoes manifest to `wrld-video-album/1.0`, supplied stable album/track IDs, corrected the exact artwork references, and removed the obsolete `output` block. Read-only validation confirms the current file passes the implemented WU3A schema and secure project-relative source checks. WU3A still never invents IDs, fuzzy-matches paths, or rewrites source manifests. Real-album rendering and human playback acceptance remain required before WU3A completion.

## WU3B decision register

**Approved:** WU3B follows WU3A and precedes WU4; WU3A acceptance remains independent. WU3B is limited to one flat image with independently optional bounded pan/zoom (maximum 1.05×), amplitude/RMS bars, and per-track progress. Camera motion is continuous across album track boundaries; analysis/progress reset on normalized-sample boundaries. Existing v1 static behavior is preserved through additive v2 contracts and a distinct profile. Motion outputs are profile-qualified. The existing worker, shared admission, timeline, lifecycle, verification, reporting, cancellation, recovery, and project boundary are reused. WU7 owns title layers, layered/parallax/atmospheric composition, effect depth, and its dedicated editor.

**Implemented candidate:** the Doc 39 v2 manifest/request/result/effects contracts, motion profile, camera, symmetrical RMS bars, sample-timeline track progress, and private lease-owned preview are present in the working tree. Automated evidence does not close WU3A's separate acceptance gate. WU3B still requires human visual review of real artwork before final acceptance.

## WU3B visual-refinement Phase A register

**User-directed design goals:** refined vertical RMS bars; organic amplitude variation while retaining symmetrical behavior; six-digit HEX colors; derived adjustable glow; a full unfilled progress rail with automatically derived contrast, independent fill/rail opacity, and optional rail override; and a future WU4 approximate composition preview distinct from the authoritative rendered preview.

**Phase B approved and implemented candidate:** the additive effects-v2/manifest-v3/request-v3/result-v3/preview-v2/profile-v2 generation, organic RMS mode, glow, configurable colors, contrasting rail, isolated output namespace, and rendered-preview integration are present in the working tree. Motion-v1 and WU3A static contracts remain literal compatibility authorities. Human visual acceptance remains pending.

**Phase D approved implementation contract:** compact player-overlay typography is an explicit WU3B exception to the earlier blanket typography deferral. Its purpose is technical playback context only: elapsed/total time, one-line album/track/BPM/key metadata, parent channel, genre channel, and an optional track announcement. It does not include generated title art, independent title PNGs, title-aware camera behavior, layered/parallax/atmospheric composition, or a composition editor; those remain WU7.

Phase D is a fully additive generation. The approved identifiers are `player-overlay/1.0`, `video-effects-v3.schema.json`, `wrld-video-album/4.0`, `video-export-request/4.0`, `video-export-result/4.0`, `motion-preview-request/3.0`, render profile `youtube-1080p30-player-v1`, renderer identity `wu3b-player-export-1`, reference layout `wrld-player-layout/1.0`, and palette algorithm `wrld-artwork-palette/1.0`. Player artifacts use `output/profiles/youtube-1080p30-player-v1/<resolved-config-sha256>/...`. Existing manifests are never migrated automatically.

**Approved label-free presentation:** player footer values render without `Album:`, `Track:`, `Parent:`, `Genre:`, `BPM:`, or `Key:` prefixes and without decorative separators. Typed metadata and provenance remain in the request. The explicit presentation identity `wrld-player-presentation/1.0` is included in the resolved-config digest so these pixels cannot reuse the earlier labeled output identity.

**Phase D visual-correction generation (October 28, 2026):** the user authorized additive renderer/presentation versioning after the first full-album render exposed three defects that media-constraint verification could not detect. Corrected exports use renderer identity `wu3b-player-export-2` and presentation identity `wrld-player-presentation/2.0`. The profile, manifest/request/result schemas, player settings, layout, palette algorithm, and effect configuration remain unchanged. Presentation 2.0 reconstructs compact `gray16le` controls as explicit full-range alpha, attaches progress commands once to the live base chain independently of bars, and uses a 2× working canvas for subpixel-capable player camera motion before stationary overlays. Because presentation identity participates in the resolved-config digest, presentation-1.0 artifacts remain intact and cannot be reused or overwritten by corrected exports. Human visual acceptance of presentation 2.0 remains required.

The player identity includes every pixel-affecting effect/player setting, resolved layout, resolved colors and provenance, artwork SHA-256, palette algorithm version, font SHA-256, display metadata/provenance, and timeline policy. Parent-channel and genre-channel values are distinct manifest inputs. BPM/key are never inferred: reliable analyzed values take precedence, otherwise explicitly intended values may be shown under the approved policy, otherwise the field is omitted.

**Phase D human acceptance recorded:** on October 27, 2026, the user approved the label-free Phase D presentation after reviewing the retained 30-second, three-track acceptance MP4 and the bounded 15-second preview. The reviewed evidence included metadata transitions and continuous album progress; the 15-second lease was then released cleanly. This approval applies only to those reviewed pixels. A later material visual change requires renewed review, and this evidence does not close WU3A acceptance.

## WU3 final-remediation policy decisions

**Approved text contrast policy (October 27, 2026):** ordinary footer text must meet WCAG AA 4.5:1 and qualifying large text must meet 3:1. Contrast is evaluated against the footer after its configured opacity is composited over the sampled artwork. Automatic and hybrid-derived text colors may be corrected deterministically while retaining derived provenance. A noncompliant manual or hybrid-manual text override is rejected; it is never silently replaced. These numeric thresholds are a new remediation decision and are not attributed retroactively to Docs 39 or 40.

**Approved bounded preview policy:** private motion previews normalize only the requested normalized-sample interval plus a finite RMS analysis margin. The current margin is ten release time constants before the excerpt and half an RMS window after it, clamped to each intersecting track. Full production exports remain unchanged. One service admits at most four distinct running/queued preview identities; identical identities share a flight and do not consume another slot. A fifth distinct identity fails with `PREVIEW_CAPACITY_EXHAUSTED`; cancelled queued work cannot later render.

**Approved private-state policy:** application-owned staging and diagnostic components use bounded hashed names while final user-visible destinations remain unchanged and are preflighted. Diagnostics use an application-state fallback and never replace a different attempt record. Preview directories carry a versioned owner marker plus a held process lock. Startup reconciliation is bounded and removes only old, unlocked, nonpersistent, marker-valid directories; active, unmarked, malformed, linked, or reparse-point entries are preserved and reported.

## Required Copilot report before any work unit
1. Documents consulted and applicable requirements (file + section).
2. Exact files to create/change, APIs/data contracts affected, test cases.
3. Known conflicts and open decisions, with proposed options but **no unilateral choice**.
4. Explicit non-goals; no scope expansion.
5. Request approval. Implement only after approval. After implementation: commands actually run, pass/fail/skip evidence, changed files, outstanding risks; wait for next gate.

## Example of proper refusal to invent
`BLOCKED DECISION: The rich album example includes 'mood' text but no numeric energy; spec prohibits fabricating measurements. I will preserve mood text and use documented fallback; I will not synthesize energy=0.5.`

## v2.5 design authority boundary
Docs 41–44 are approved **UX direction and work-unit ownership**, not authority to invent exact schemas, routes or renderer generations. The eight historical Phase 0 blockers in Doc 44 were subsequently resolved sufficiently for the uncommitted Phase 1 backend candidate; their current disposition must be read from the revised Doc 44 and verified against source. The reconciled later ownership is WU4 Import/Review, WU5 Metadata, WU6 Rendering/batch operations, WU7 advanced layered composition, and WU8 imported video sources/clip playlists. Existing WU3A/WU3B generation and acceptance decisions in this document remain controlling.

## v2.6 WU4 Phase 2R authority boundary

Doc 45 is approved product architecture for unified flexible ingestion and the Phase 2R sequence. It supersedes album-manifest-required **WU4 registration UX** only; it does not supersede WU3 render schemas, output identities, verification or acceptance.

Doc 46 is the approved Phase 2R technical contract. Approved decisions include: `wrld-project-catalog/2.0`, `wrld-project-inventory/1.0`, `wrld-project-scan/1.0` and session-only `wrld-import-handoff/1.0`; stable opaque identities; optional manifest enrichment; atomic recoverable v1→v2 migration; transactional inventories; two-stage observations plus mandatory strong SHA-256 at dependency/relink/render boundaries; user-confirmed relinking; initial overlap prohibition; asynchronous cancellable scans with typed budget diagnostics and administrator retry ceilings; the initial media/MIME/image-safety matrix; opaque audio/image/thumbnail routes; inventory/dependency fingerprint separation; independent Import runtime; generated TypeScript transport types plus shared fixtures; and WU6 ownership of the first solid-color renderer generation.

Approval of Doc 46 closed the Phase 2R.0 contract-decision gate but did not by itself authorize implementation. A later Functional Import authorization satisfied the Phase 2R.1–2R.3 implementation gates; their uncommitted implementation candidates still require acceptance evidence. Phase 2B's durable composition schema and WU6's solid-color renderer profile remain later contract gates. Existing WU3 render behavior and Phase 1 public contracts remain controlling compatibility requirements.

## v2.7 consolidated WU4 decision register

The consolidated WU4 authorization approves a project-level Import model: discovered safe assets are included by default; stable-identity exclusions are reversible, persistent and separate from technical inventories; Import does not select a workflow or order tracks. `wrld-import-handoff/2.0` identifies the project plus inventory and preference revisions. Existing v1 handoffs remain readable compatibility input.

Review retains the top-level four-screen architecture and adds **Media | Creation | Editor** subworkspaces. The additive `wrld-creation-state/1.0` document owns stable album plans, duplicate-permitted album assignments, independent Single drafts, independent Short drafts, archival/restoration and strong source dependencies. Duplicate assignments warn but do not block. Existing manifest-backed primary Short identities/ranges/settings/approval are carried forward when the Creation document is first initialized. Explicit Save, optimistic revision checks, changed/missing-source diagnostics and local unsaved undo/redo apply.

The preferred Short duration is 45 seconds and may be configured from 20 through 120 seconds. A future evidence-backed analyzer may recommend within ±15 seconds; five seconds is the absolute minimum unless the entire source is shorter, in which case review is required and approval is forbidden. Analyzer actions remain disabled until an approved observation contract exists. These decisions do not authorize final Short rendering, metadata, advanced layers or imported-video composition.

## v2.8 WU4 Editor UX refinement register

Doc 50 is the specific authority for active-output Editor category availability, collapsed/grouped Creation warnings, the explicit one-click sole-image suggestion for newly created templates, and bulk shared-template reference assignment. It does not amend the Creation v2 payload, deterministic migration, null template default, explicit Save/revision protocol, or WU3 rendering. Independent-copy assignment is specified but separately gated. Creation-template render admission, including the pending treatment of excluded images, remains WU6 scope.

## v2.9 WU4 composition-owned visual-settings supersession

The revised Doc 50 is the specific authority for Creation v4 and deliberately supersedes the active shared-template editing semantics implemented in WU4 Phases 1–3. The governing rule is **Templates supply settings; compositions own settings.** Every v4 Album, Single, and Short stores required authoritative `visual_configuration`; nullable `source_visual_template_id` is historical provenance only and never a live dependency. Exact template matching is derived rather than persisted.

The explicit v3→v4 migration copies each resolvable concrete template configuration into every active and archived composition while preserving identities, ordering, approvals, customization, templates, and families. Non-null dangling references reject atomically. A null v3 reference may migrate only when another complete authoritative configuration is present; otherwise lossless migration is blocked and no defaults are synthesized. Migration, cleanup, and production-data mutation never occur automatically.

V4 retains the three-member Album/Single/Short family registry as reusable library presets. Conservative legacy cleanup removes only verified generated artifacts after a previewable plan, explicit authorization, and exact revision/fingerprint revalidation. Phase 4A supplies the contract, migration, validation, persistence, cleanup foundation, frontend compatibility block, and documentation. Phase 4B owns composition/template-library UI. WU6 still owns renderer admission and v4-to-renderer mapping; no WU3 contract changes.

## v3.0 approved WU5 metadata contract

Doc 51 and `contracts/schemas/youtube-metadata-editor-v1.schema.json` plus `youtube-metadata-v1.schema.json` are the approved WU5 authority. They define separate `wrld-youtube-metadata-editor/1.0` private project state and `wrld-youtube-metadata/1.0` portable export contracts, stable Creation v4 Album/Single/Short target keys, deterministic minimal drafts, target-level approval fingerprints, WU3A-owned chapter timing, project-scoped routes, explicit reconciliation, and compare-and-swap export replacement.

The user approved every identifier, field, template, hashtag, route, diagnostic, validation rule, initialization behavior, chapter dependency, and collision rule in Doc 51 on November 2, 2026. This approval authorizes WU5 implementation and verification only. It does not authorize automatic legacy import, production-project mutation during development, WU6 rendering, or changes to Creation visual contracts.

Current WU3A chapters describe the normalized manifest Album, while Creation v4 may contain arbitrary Album plans. WU5 may reuse WU3A timing only for a plan proven equivalent to that track sequence. Noncanonical Album plans remain editable and saveable, but their chapter-dependent approval/export remains blocked until WU6 supplies a verified timeline mapping.

The working tree now contains an uncommitted WU5 implementation candidate: promoted production schemas and generated transports, project-local revisioned editor state, deterministic all-target initialization, explicit validation/approval/reconciliation, atomic compare-and-swap portable export, project-scoped FastAPI routes, and a guarded React Table/Detail Metadata workspace. This records implementation status only; it does not imply manual acceptance, mutate production project data, or begin WU6.
