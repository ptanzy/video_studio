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
