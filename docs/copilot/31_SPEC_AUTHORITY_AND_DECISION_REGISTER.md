**v1.8 update:** `32_WU0_RESOLUTION_AND_WU1_BASELINE.md` approves a narrow WU1 *proposal* and specifies its contracts; `33_WU1_CONTRACT_EXAMPLES_AND_TESTS.md` provides normative fixtures. Earlier open decisions that do not affect WU1 remain deferred, not invitations to invent behavior. Obtain user approval before starting WU1.

# 31 — Specification authority, open decisions and Copilot anti-invention policy

## Authority and conflict handling
1. Explicit user-approved decisions documented in this handoff and current `AGENTS.md` govern scope.
2. Newer *specific* normative specifications (15–30) supersede older conflicting text in 00–14. For equal specificity, STOP and report conflict; do not select an interpretation by intuition.
3. Schemas/OpenAPI govern machine payload shape only when approved and checked in; examples and HTML prototypes are illustrative, not normative schemas.
4. Legacy v2 is a read-only behavior reference, not an implementation template.
5. If a requirement is not defined, classify it as **BLOCKED DECISION**, **SAFE IMPLEMENTATION DETAIL**, or **DEFERRED**. Never present assumptions as decisions.

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

## Required Copilot report before any work unit
1. Documents consulted and applicable requirements (file + section).
2. Exact files to create/change, APIs/data contracts affected, test cases.
3. Known conflicts and open decisions, with proposed options but **no unilateral choice**.
4. Explicit non-goals; no scope expansion.
5. Request approval. Implement only after approval. After implementation: commands actually run, pass/fail/skip evidence, changed files, outstanding risks; wait for next gate.

## Example of proper refusal to invent
`BLOCKED DECISION: The rich album example includes 'mood' text but no numeric energy; spec prohibits fabricating measurements. I will preserve mood text and use documented fallback; I will not synthesize energy=0.5.`
