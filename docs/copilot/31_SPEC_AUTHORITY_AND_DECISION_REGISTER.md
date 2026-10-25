**v1.8 update:** `32_WU0_RESOLUTION_AND_WU1_BASELINE.md` approves a narrow WU1 *proposal* and specifies its contracts; `33_WU1_CONTRACT_EXAMPLES_AND_TESTS.md` provides normative fixtures. Earlier open decisions that do not affect WU1 remain deferred, not invitations to invent behavior. Obtain user approval before starting WU1.

**v2.0 update:** `38_WU3A_VIDEO_EXPORT_SPECIFICATION.md` is the specific forward authority for WU3A and for responsibilities transferred from WU4–WU6. WU1–WU3 implementation records remain historically accurate. WU3A is next. Its album-project boundary, project-local `output/` root, and all eight Section 15 contract decisions are approved. The corrected current *Echoes of Asia* artwork resolves the historical visible-title mismatch subject to normal file validation. WU3A implementation is authorized for a subsequent implementation pass under the normal plan/report gate; this approval-record pass changes no application code.

# 31 — Specification authority, open decisions and Copilot anti-invention policy

## Authority and conflict handling
1. Explicit user-approved decisions documented in this handoff and current `AGENTS.md` govern scope.
2. Newer *specific* normative specifications (15–30) supersede older conflicting text in 00–14. For equal specificity, STOP and report conflict; do not select an interpretation by intuition.
3. Schemas/OpenAPI govern machine payload shape only when approved and checked in; examples and HTML prototypes are illustrative, not normative schemas.
4. Legacy v2 is a read-only behavior reference, not an implementation template.
5. If a requirement is not defined, classify it as **BLOCKED DECISION**, **SAFE IMPLEMENTATION DETAIL**, or **DEFERRED**. Never present assumptions as decisions.
6. For WU3A video export, Doc 38 supersedes older work-unit allocation but not the established lifecycle, media-integrity, preview, metadata, or UI contracts it explicitly retains.
7. WU3A receives an explicit album-project directory, treats it as the filesystem/security boundary, and publishes beneath its `output/`. The current `WORLD_MUSIC\WRLD-FI\Albums` hierarchy is a default convention for acceptance, not a locked drive/user/library/channel path. Future library-root selection and album initialization are later-workflow concerns.

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

**Remaining source-preparation gate:** approval of these product contracts does not convert the current `wrld-video-album/0.1-draft` file into valid `wrld-video-album/1.0`. The inspected Echoes draft still lacks stable album/track IDs and references nonexistent unprefixed artwork names. Generic WU3A implementation may proceed, but real-album rendering must wait for a separately approved, reviewable manifest preparation/migration with explicit stable IDs and exact paths; WU3A may not invent or silently write them.

## Required Copilot report before any work unit
1. Documents consulted and applicable requirements (file + section).
2. Exact files to create/change, APIs/data contracts affected, test cases.
3. Known conflicts and open decisions, with proposed options but **no unilateral choice**.
4. Explicit non-goals; no scope expansion.
5. Request approval. Implement only after approval. After implementation: commands actually run, pass/fail/skip evidence, changed files, outstanding risks; wait for next gate.

## Example of proper refusal to invent
`BLOCKED DECISION: The rich album example includes 'mood' text but no numeric energy; spec prohibits fabricating measurements. I will preserve mood text and use documented fallback; I will not synthesize energy=0.5.`
