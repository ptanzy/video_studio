# 37 — WU3 Visual Rendering Implementation Baseline

**Status: Phase 1 implemented; all aesthetic/product proposals remain pending explicit approval.** Sections describing contracts and behavior below include the actual provisional Phase 1 implementation. Proposed Phase 2+ decisions are not approved requirements. This document does not authorize work beyond the explicitly approved Phase 1 scope.

## 1. Objective and authority

WU3 adds still-image rendering and color treatment: deterministic resolution, Auto/preset/custom HEX choices, an approximate browser proxy, an authoritative FFmpeg-rendered still, Original/Split/Treated comparison of the same source frame, and decoded-pixel visual regression. It is a reusable visual-rendering capability, not the complete Review workflow.

Controlling specifications:

- [18 — Custom Color Treatments](18_CUSTOM_COLOR_TREATMENTS.md): modes, validation, canonical-transform ownership, and color editor requirements. Its v1.6 addendum defers Auto precedence and unknown-mood behavior to Doc 25.
- [22 — Preview Pipeline and Color Regression](22_PREVIEW_AND_COLOR_REGRESSION.md): approximate/authoritative preview distinction, cache identity requirements, invalidation, and decoded-frame testing.
- [25 — Deterministic Color Resolution](25_COLOR_RESOLUTION.md): Auto precedence, unrestricted mood text, unknown-text handling, and deterministic resolution.
- [27 — UI Validation and Color Comparison](27_UI_VALIDATION_AND_COMPARISON.md): same-frame comparison, accessible split behavior, stale-preview invalidation, and error behavior.
- [31 — Specification Authority](31_SPEC_AUTHORITY_AND_DECISION_REGISTER.md): authority ordering, approved-schema rule, and anti-invention policy.
- [32 — WU0 Resolution and WU1 Baseline](32_WU0_RESOLUTION_AND_WU1_BASELINE.md): controlling narrow WU3 boundary and work-unit dependency graph.
- [34 — WU2 Media Infrastructure Baseline](34_WU2_MEDIA_INFRASTRUCTURE_BASELINE.md) and [35 — WU2 Test Matrix and Failure Semantics](35_WU2_TEST_MATRIX_AND_FAILURE_SEMANTICS.md): existing media-process, artifact, worker, cancellation, and test boundaries.
- [AGENTS.md](../../AGENTS.md): no invented requirements, explicit approval gates, and read-only legacy-v2 rule.

Under Doc 31, specific newer requirements control older conflicting requirements; examples and prototypes are illustrative, not schemas. Where the specs do not define a product choice, this document labels it **PROPOSED — PENDING APPROVAL** or **BLOCKED DECISION**. This document does not rewrite or silently supersede existing specs.

## 2. Scope boundaries

### In scope

- Still-image input validation and authoritative still rendering.
- Deterministic color/palette resolution and versioned preset/custom treatment contracts.
- `auto`, `preset`, and `custom` HEX modes.
- Immediate approximate browser preview and debounced authoritative FFmpeg still.
- Reusable Original/Split/Treated comparison of the same input frame.
- Decoded-pixel visual regression and parity checks against a reference implementation.

### Out of scope for WU3

- The full WU4 Import/Review workflow and integrated render experience.
- Override persistence, save/reload editing workflows, and waveform editing.
- Full album compilation, complete Shorts rendering, or YouTube metadata/upload.
- Motion effects: zoom/pan, grain, audio-reactive bars, progress indicators, portrait motion, and encoded motion preview unless the user explicitly approves a WU3 scope change.

Zoom/pan, grain, audio-reactive bars, progress indicators, and portrait motion remain future roadmap capabilities. This plan does not assign them to a work unit. Doc 18's requirement to tint foreground and blurred background applies when portrait composition is implemented; WU3's still-only contract does not authorize building that composition.

## 3. Current architecture and WU2 integration

WU1/WU2 implementation is present in the repository. Relevant WU2 anchors include:

- `backend/src/wrld_video_studio/domain/jobs.py`: immutable render snapshots, plans, probes, and job states.
- `backend/src/wrld_video_studio/application/ports/media.py`: injectable process, probe, verification, event, repository, and artifact-store interfaces.
- `backend/src/wrld_video_studio/application/media_jobs.py`: synthetic proof submission and the single-worker job lifecycle.
- `backend/src/wrld_video_studio/infrastructure/process_runner.py`: argument-array subprocess invocation, bounded output, cancellation, timeout, and owned-process cleanup.
- `backend/src/wrld_video_studio/infrastructure/media_tools.py` and `ffprobe_adapter.py`: tool discovery and probing.
- `backend/src/wrld_video_studio/infrastructure/ffmpeg_adapter.py`: `SyntheticMediaEncoder`, explicitly restricted to `synthetic-proof` requests.
- `backend/src/wrld_video_studio/infrastructure/artifact_store.py` and `artifact_verifier.py`: staging/promotion and MP4-oriented verification.
- Existing tests under `backend/tests/unit`, `backend/tests/contracts`, and `backend/tests/integration`, especially `test_wu2_worker.py`, `test_wu2_adapters.py`, and `test_wu2_synthetic_render.py`.

**Required boundary:** WU3 may reuse compatible process/tool discovery, safe filesystem staging, diagnostics, validation patterns, and test fakes. It must add a still-image application/adapter path; do not route image rendering through the audio/MP4-specific WU2 worker or weaken/change its synthetic proof contract. The current artifact verifier is MP4-specific and should not be presumed to verify PNG stills.

The workspace inventory at planning time contains no frontend source/package. Confirm the actual frontend state before Phase 4; do not scaffold or add dependencies as part of Phase 1. `docs/ui/index.html` remains a design reference, not application source. `legacy_v2/` is read-only.

## 4. Color treatment and resolution contract

### Existing authoritative behavior

- Modes are `auto`, `preset`, and `custom` (Doc 18).
- Custom HEX syntax is six-digit `#RRGGBB`, accepts either input case, and normalizes uppercase. Intensity must be finite and in inclusive `[0.0, 0.6]` (Doc 18).
- `original` is a valid preset meaning no tint. Invalid backend payloads must not partially save; Doc 18 specifies 422 for invalid payloads. Legacy `color_profile`/`color_intensity` may only be adapted explicitly; simultaneous legacy and new fields must not be silently reconciled (Doc 18).
- Mood/emotion is unrestricted text, not an enum. Unknown text must not fail import or trigger arbitrary saturated color. Missing numeric observations must not be fabricated (Doc 25).
- Doc 25 precedence is: approved exact-Short/track `color_treatment` override; explicit valid per-track visual preference; album visual palette, optionally weighted only by supplied numeric brightness/energy/tension and recognized mood concepts; explicit album-level default preset; original artwork at intensity zero.
- In Auto, supplied album palette is considered before weak mood text. Unusable palette data preserves original artwork. Numeric features, if supplied, are finite `[0,1]`; energy is not automatically color temperature (Doc 25).
- The resolved object is computed render data, not a mutation of canonical input (Doc 25).

### Pending resolution decisions

**Implemented as provisional Phase 1 choices, pending product approval:** stable preset identifiers/mappings, palette ordering, and the resolver input/output schema were required to implement the approved pure resolver. Existing manifest enums and example palettes did not approve those mappings; the choices below are explicitly provisional and do not amend existing contracts.

**PROPOSED — PENDING APPROVAL:** mapping version `provisional-1` currently uses `original` = untreated/no tint (`resolved_hex: null`), `cool` = `#71869A`, `warm` = `#B47B55`, `lavender` = `#887A9B`, `teal` = `#5F817B`, and `dark` = `#48525A`. The cool/warm samples were present in illustrative palette examples; all values, including those, remain provisional and require approval. Constants are centralized in `backend/src/wrld_video_studio/domain/color_resolution.py`.

**PROPOSED — PENDING APPROVAL, implemented in resolver v1:** validate every supplied palette entry, reject any malformed HEX, then choose the first entry from the non-empty valid array; do not weight optional features. Ignore absent/unknown mood and do not infer numeric values. If the palette is absent or empty, resolve a supported explicit album default preset; otherwise resolve `original` at intensity 0. Track preference HEX precedes the album palette. This implements Doc 25's explicit precedence but does not model persistent approved per-Short overrides in Phase 1; callers must supply a treatment already selected by their boundary. Palette ordering and the per-track preference shape still need approval.

Malformed palette HEX and malformed nested preference/default/feature structures are rejected with stable typed errors. Missing optional context metadata is tolerated; present null values are accepted only where the schema allows them (`track_preference`, `mood`). An empty or absent palette falls through. Runtime validation and schema validation use the same nested field/type constraints.

**PROPOSED — PENDING APPROVAL:** reset should be labelled `Reset to Auto`, clear the item-specific treatment override, and re-resolve from current metadata; stale preset/custom payload values must not remain effective. Doc 18 says `Reset to Mood`, while Doc 25 says `Reset to Auto`; both produce Auto, but UI wording and override clearing need approval. Persistence itself remains outside WU3.

### Validation and determinism proposal

**PROPOSED — PENDING APPROVAL:** accept only `^#[0-9A-Fa-f]{6}$`, normalize to uppercase, reject shorthand/alpha/named colors, and reject non-finite or out-of-range intensity. Preserve intensity range `[0,0.6]`; do not reinterpret it as a literal percentage until the transform is approved. Intensity zero must mean the unchanged source; `original` must resolve to no tint and intensity zero. Do not silently clamp invalid values.

**Implemented, provisional contract:** the input/output contract versions are `color-resolution-input-v1` and `color-resolution-output-v1`; resolver version is `1.0.0-provisional.1`; mapping version is `provisional-1`. Output carries mode, resolved HEX or null, preset ID or null, effective intensity, source, stable reason, resolver/mapping versions, and SHA-256 input fingerprint. The fingerprint is SHA-256 over canonical compact UTF-8 JSON with sorted keys, normalized custom/palette/preference HEX, and resolver/mapping versions. Contract fields and version labels are proposals pending approval; they do not change WU1 schemas.

## 5. Candidate color mathematics

No transform formula is authoritative yet. Doc 18 requires one canonical backend transform for authoritative still and eventual final rendering; Doc 22 requires a deterministic FFmpeg graph and decoded-frame tolerance tests. The following is a candidate for evaluation, not a selected implementation.

### Preferred candidate: luminance-preserving chroma adjustment

Inputs are source RGB in sRGB and target tint HEX in sRGB. Decode each sRGB component to normalized linear light using the IEC 61966-2-1 transfer function:

$$
c_{lin}=\begin{cases}
c_{srgb}/12.92, & c_{srgb}\le 0.04045 \\
((c_{srgb}+0.055)/1.055)^{2.4}, & c_{srgb}>0.04045
\end{cases}
$$

Let source linear RGB be $S=(R,G,B)$, with luminance $Y=0.2126R+0.7152G+0.0722B$. Decode tint HEX to linear $T$ and calculate $Y_t$ with the same coefficients. For $Y_t>0$, define target chromaticity $C=T/Y_t$; for a black target or undefined chromaticity, treat the target as no tint unless a different approved rule is chosen. With treatment intensity $a\in[0,0.6]$:

$$
Q=(1-a)S+aYC
$$

Both terms have source luminance $Y$, so $Q$ retains it before gamut mapping. To keep channels in gamut while retaining that luminance, let $d=Q-(Y,Y,Y)$ and choose:

$$
k=\min\left(1,\min_{d_i>0}\frac{1-Y}{d_i},\min_{d_i<0}\frac{Y}{-d_i}\right),\qquad O=(Y,Y,Y)+kd
$$

An empty inner minimum is omitted; bound $k$ to `[0,1]` for numerical safety. This moves the candidate toward neutral luminance only as much as required to fit the RGB gamut. Apply the inverse sRGB transfer function:

$$
c_{srgb}=\begin{cases}
12.92c_{lin}, & c_{lin}\le 0.0031308 \\
1.055c_{lin}^{1/2.4}-0.055, & c_{lin}>0.0031308
\end{cases}
$$

Then quantize to 8-bit using one explicitly selected and tested rounding rule, and preserve source alpha unchanged. Define a small numerical epsilon and prohibit extra contrast, gamma, saturation, or clipping operations unless approved.

At $a=0$, output must equal source after the declared decode/encode and quantization path. The $0.6$ limit is a permitted input maximum, not a claim that the image reaches a perceptual endpoint. The black-target case and rounding rule must be decided. Exact parity requires controlling FFmpeg's pixel formats, transfer characteristics, scaling, and rounding.

### Alternatives to compare

- **Channel interpolation:** $(1-a)S+aT$. Simple and reproducible, but it changes luminance, can lift/dim shadows and highlights, and may flatten source tonal character.
- **Multiplicative tint:** multiply source channels by tint channels or a normalized tint. It naturally retains black but changes luminance, may clip, and needs a precise normalization rule.
- **Overlay/soft-light blending:** familiar photographic appearance, but nonlinear variants differ across tools and are less straightforward to implement consistently and test against FFmpeg.

**PROPOSED — PENDING APPROVAL:** prefer the luminance-preserving candidate for photographic treatment because it is designed to retain source luminance/detail, subject to proof. Do not choose or ship it based on the equation alone. Before selecting the final transform, build a small reference-image and FFmpeg-filter proof covering neutral ramp, shadows/highlights, saturated colors, alpha, endpoints, gamut bounds, and numerical differences. Document any FFmpeg approximation and select decoded-pixel tolerances only after observing that proof.

The browser CSS/canvas treatment may be visually approximate and need not be pixel-identical. It must not be treated as the authoritative formula or used as a substitute for the reference/FFmpeg proof.

## 6. Proposed image and FFmpeg still contract

Every value in this section is **PROPOSED — PENDING APPROVAL** unless explicitly identified as a Doc 18/22 requirement. No image byte/dimension limit, output dimension, or accepted image format is currently authoritative in the controlling WU3 docs.

### Candidate validation defaults

- Inputs: JPEG/JPG, PNG, and WebP stills. Initially reject animated images and unsupported formats such as SVG, HEIC, and AVIF unless explicitly added.
- Limits: 40 MiB per input, 40 megapixels, and 10,000 pixels on either side. Enforce limits before expensive decode where feasible; distinguish malformed, unsupported, and over-limit inputs.
- Normalize EXIF orientation before rendering. Do not mutate source bytes.
- Preserve alpha through treatment. Proposed authoritative PNG output preserves alpha; the UI displays transparency over a checkerboard or neutral comparison background. The comparison background itself needs approval and must be identical in Original and Treated views.
- Normalize color-managed input to sRGB when supported and tested. Define behavior for malformed/unsupported ICC profiles before accepting them; do not silently mislabel an unknown profile as sRGB.
- Output: PNG, no upscale, longest side at most 1024 pixels, aspect preserved. Specify deterministic dimension rounding and minimum 1-pixel dimension in the approved contract. Tag output as sRGB when the toolchain supports it.

### Candidate pipeline and verification

**PROPOSED — PENDING APPROVAL:** use FFmpeg as the authoritative still renderer, invoked with the WU2 argument-array process runner (`shell=False`), `-nostdin`, bounded stderr, explicit timeout/cancellation, and a single-frame output. Candidate order: decode and apply orientation; normalize color space; fit/scale with a specified filter without cropping/upscaling; apply the canonical color transform; encode one PNG. There are no WU3 overlays or motion effects. Any graph and order must be shared by the authoritative still and any later product render path that uses the same treatment.

Verify more than process exit status: PNG signature, bounded output size, successful independent decode, dimensions, alpha behavior, expected color metadata, input identity, and transform/version identity. Keep temporary output in request-owned staging; promote only when a durable artifact is explicitly required by a later approved contract. Preview output remains disposable.

Require locally available FFmpeg and FFprobe capabilities; never download/install automatically. The exact required filters/encoders and behavior when absent must be probed and reported. Avoid requiring optional filters/libraries unless approved. Use the configured tool-discovery pattern from WU2. Do not assert byte-identical output across operating systems or FFmpeg builds; record tool version/build, pixel format, and color metadata in test evidence.

**PROPOSED — PENDING APPROVAL:** image-specific timeout 15 seconds, two active still-preview processes maximum, and a bounded queue of eight. Windows/Linux process ownership and descendant termination must use and test the existing WU2 runner behavior. On cancellation/timeout, terminate only request-owned work, reap the process, preserve diagnostics, and clean only request-owned scratch. Do not leak absolute private paths in UI-safe errors.

## 7. Preview and comparison contract

### Two preview tiers

- **Approximate preview:** local browser CSS/canvas response to user input, labelled exactly and visibly `Approximate preview`. It is a responsive proxy only; it cannot imply FFmpeg equivalence (Doc 22).
- **Authoritative still:** debounced server-generated image using the canonical FFmpeg transform builder also intended for eventual rendering. Doc 22 gives 250–400 ms as an example debounce. Label it `Rendered preview`; show loading/error state. Cache is disposable, not a final artifact. Superseded work is cancelled where possible and stale responses ignored.

### Same-frame Original/Split/Treated

Doc 27 requires Original, Split, and Treated views of the same frame. For this WU3 still slice, “same frame” means the same source image, orientation normalization, dimensions, and fit/crop geometry; Original shows the un-treated normalized source and Treated shows the authoritative rendered still. No independently sampled time or source image may be compared. Invalidate the treated result when input content, resolved treatment/settings, transform version, or output geometry changes. On failure, retain Original and the last confirmed still with a clear stale/error explanation; a failed request never changes approved treatment settings.

Split uses a draggable divider with visible Original/Treated labels, keyboard arrow movement, focus visibility, and accessible slider semantics. Provide labelled mode controls for Original, Split, and Treated. A frontend implementation must support loading, empty, error, and stale states. These are reusable controls, not a full Review page.

### Request, response, cache, and concurrency boundaries

No WU3 route or request/response schema is approved. Do not invent or implement one before approval. An approved contract must identify source input, requested geometry, treatment/resolution parameters, versioning, response media type/dimensions, and typed errors without leaking internal paths. It must be bounded and disposable.

**PROPOSED — PENDING APPROVAL:** cache identity is a stable digest over source content SHA-256, canonical resolved settings, transform version, and requested output geometry. Do not key by path alone. Use bounded in-memory or temporary cache with eviction/TTL and no override persistence; proposed cap 32 entries and 10-minute TTL. The algorithm for canonical serialization and digest version must be approved. A cache hit is valid only if every identity component matches.

**PROPOSED — PENDING APPROVAL:** cap image-preview rendering at two active requests and eight waiting requests, separately from WU2's single synthetic worker. Return an approved typed busy/error response rather than starving or mutating WU2 job state. Request cancellation must cancel queued work and signal the owned FFmpeg process; a per-request token prevents late completion from replacing current UI state. Exact queue policy, timeout, error status, and API surface are approval decisions.

## 8. Specification conflicts and gaps

| Conflict or gap | Authority and status | Recommended handling |
|---|---|---|
| Older Doc 07 work-unit descriptions include visual effects such as zoom, grain, bars, or progress; Doc 32 defines narrow WU3. | Doc 32 controls WU3 scope under Doc 31. | Defer those effects as roadmap capabilities without work-unit assignment. No implementation blocker if this boundary is honored. |
| Doc 18 initially describes Auto as mood-derived; its v1.6 addendum delegates to Doc 25, where supplied palette is considered first and mood is weak/optional. | Doc 25 is the specific normative resolution and Doc 18 explicitly defers to it. | Use Doc 25 precedence; unknown mood is ignored. Palette tie-break remains a blocked decision. |
| Doc 18 says `Reset to Mood`; Doc 25 says `Reset to Auto`. | Both name Auto behavior; exact UI wording and clearing semantics are not reconciled. | Approve wording and specify that reset clears stale per-item treatment so Auto re-resolves. Persistence remains deferred. |
| Doc 22 includes on-demand motion confirmation; Doc 32 names still preview in WU3. | Doc 32's work-unit boundary is narrower; motion preview is not necessary for still acceptance. | Exclude encoded motion preview from WU3 unless explicitly added. |
| Doc 18 requires legacy `color_profile`/`color_intensity` adaptation and 422 validation; Doc 21 has a broader error model while checked-in API error schema is WU1-specific. | Doc 31 requires approved schemas/contracts; WU1 schema governs only its narrow contract. | Before an endpoint, approve WU3 request/response/error contract and decide legacy adapter behavior. This blocks API work, not a pure-domain Phase 1 if adapter/API are excluded. |
| Doc 25 gives resolution precedence but not palette ordering, weights, exact preset constants, output enums, or resolver serialization. | Doc 31 explicitly says not to invent palette mapping. Examples are not schemas. | Phase 1 has provisional behavior and a versioned schema; approval is still required before adopting those choices as stable product contracts. Invalid palette HEX is rejected per Doc 25. |
| Docs 18/22/25/27 require a shared transform and tolerance-based tests but do not select blend math, color math, filter order, rounding, or thresholds. | No current normative choice. | Approve math after reference/FFmpeg proof; blocks Phase 2 and visual golden thresholds, not contract discussion. |
| `manifest-v2.schema.json` has legacy color fields; newer Docs 18/25 specify a discriminated editor treatment/resolved model. | Doc 31 gives authority to newer specific specs; Doc 32 does not authorize schema migration/persistence in WU3. | Leave manifest/WU1 schemas unchanged. Approve a WU3 color contract and explicit legacy adapter only if needed. |
| `override-store-v1.schema.json` is intentionally generic and the v1.4 example has different structure. | Neither is a WU3 treatment schema; examples cannot establish payload shape. | Do not change or extend either in this round. Approve a new WU3 contract only if required by the chosen phase. Override persistence remains excluded. |
| Doc 27 defines a Review screen, while Doc 32 schedules only WU3 preview/comparison capabilities before WU4. | Doc 32 controls work-unit boundary. | Build reusable preview/comparison controls only; wire them into Review in WU4. |

## 9. Phased implementation plan

Each phase requires explicit user approval before implementation. The file lists below are anticipated ownership areas, not an authorization or a claim that every file must change. Add only contracts actually needed by the approved phase. Preserve Python 3.11/3.12 and Windows/Linux behavior. The frontend source must be confirmed before Phase 4.

### Phase 1 — Contracts and deterministic color resolver — implemented provisionally

**Purpose:** pure domain validation/resolution and JSON Schema contract tests only. Phase 1 was explicitly authorized by the user and is implemented. This implementation does not itself approve provisional mappings or contract choices as permanent product requirements.

- **Files added:** `backend/src/wrld_video_studio/domain/color_resolution.py`; `contracts/schemas/color-resolution-v1.schema.json`; `backend/tests/unit/test_color_resolution.py`; `backend/tests/contracts/test_color_resolution_contract.py`.
- **Input contract:** `color-resolution-input-v1` object with `contract_version`, discriminated `treatment`, and optional `context`. Treatment shapes are Auto `{mode,intensity}`, preset `{mode,preset,intensity}`, and custom `{mode,hex,intensity}`. Context supports nullable/absent track-preference HEX, absent or empty/non-empty ordered album palette, album default preset, nullable/absent unrestricted mood text, and optional numeric `brightness`, `energy`, and `tension` features. Malformed present metadata, unsupported nested fields, and invalid HEX reject with typed errors.
- **Output contract:** immutable `ColorResolution` (`frozen=True`) serialized with `to_dict()` as `color-resolution-output-v1`; fields are `contract_version`, `mode`, `resolved_hex`, `preset_id`, effective `intensity`, `source`, `reason`, `resolver_version`, `preset_mapping_version`, and `input_fingerprint`. Mutually exclusive schema branches tie mode, HEX, preset ID/mapping, intensity, source, and reason together; output HEX must be uppercase.
- **Versions:** resolver `1.0.0-provisional.1`; preset mapping `provisional-1`. Both are pending approval and must change when the corresponding resolution/mapping behavior changes.
- **Provisional preset mappings — pending approval:** `original` = `null`/untreated; `cool` = `#71869A`; `warm` = `#B47B55`; `lavender` = `#887A9B`; `teal` = `#5F817B`; `dark` = `#48525A`. The table is centralized in `color_resolution.py`. No value is claimed as an approved aesthetic mapping.
- **Auto precedence:** supplied track preference HEX, first palette entry after complete palette validation, supported album default preset, then original/no tint at intensity `0.0`. Unknown/missing mood is ignored. Numeric features are validated as finite `[0,1]` when present but do not weight selection; values are never inferred. Invalid palette HEX rejects even if later entries are valid. First-entry ordering and no weighting are provisional pending approval. Phase 1 accepts an already-selected treatment; it does not implement stored per-Short override lookup.
- **Validation:** strict six-digit sRGB HEX, normalized uppercase; finite exact numeric intensity in inclusive `[0.0,0.6]`; bool/string/NaN/infinity and out-of-range values rejected. Negative zero normalizes to positive `0.0` before resolution and fingerprinting. `original` always resolves to `resolved_hex=null` and effective intensity `0.0`. No clamping or image transformation occurs.
- **Errors:** `ColorResolutionError` with stable `code`, `message`, recursively immutable `details`: `COLOR_INVALID_INPUT`, `COLOR_UNSUPPORTED_CONTRACT`, `COLOR_INVALID_MODE`, `COLOR_INVALID_PRESET`, `COLOR_INVALID_HEX`, `COLOR_INVALID_INTENSITY`. Malformed Unicode, unsupported Python objects, non-finite context values, and canonical-serialization failures are mapped to typed errors. These are pure-domain identifiers, not an HTTP envelope or a modification to the WU1 API error schema.
- **Fingerprint:** SHA-256 over canonical compact UTF-8 JSON with sorted keys, normalized custom/palette/preference HEX and zero intensity, and resolver/mapping versions. Caller input is detached before normalization; resolution does not mutate supplied metadata. Identical normalized inputs/version produce identical fingerprints.
- **Output schema:** mutually exclusive JSON Schema branches enforce mode/result HEX/preset/source/reason/intensity relationships. Preset HEX must match the versioned provisional table; `original`/untreated outputs have null HEX and zero intensity.
- **Tests:** modes/presets with independent expected values; Auto source/reason for each precedence/fallback branch; explicit mode precedence; strict nested context and HEX/intensity; original semantics; recursively immutable errors; malformed JSON-like input; metadata immutability; negative-zero normalization; fingerprint stability/sensitivity/separate-process determinism; schema/runtime agreement and contradictory-output rejection; validity of existing WU1/WU2 schemas.
- **Exclusions preserved:** no FFmpeg, transform mathematics, image decoding, HTTP, frontend, cache, persistence, legacy adapter, album/Short rendering, or WU2 production changes.
- **Validation status:** corrected focused/full validation results are recorded in Section 12.2.
- **Still pending approval:** preset HEX mappings, input/output schema fields and version labels, Auto palette ordering, fallback reason/source vocabulary, and feature-weighting policy. No pending proposal should be treated as a permanent product requirement without approval.

### Phase 2 — Authoritative still rendering

- **Prerequisites / approval:** Phase 1 accepted; approve transform formula after reference/FFmpeg proof, color/gamut/rounding/alpha/ICC policy, accepted formats and limits, output format/geometry, FFmpeg capabilities, filter order, timeout/cancellation semantics, and still-verification contract.
- **Anticipated files/modules:** additive still-render application service/port near `application/` and `application/ports/`; image-specific FFmpeg adapter and verifier under `infrastructure/`; image contract/tests. Reuse compatible `ProcessRunner`, `MediaToolchain`, path-safety and artifact patterns. Do not change `SyntheticMediaEncoder`, `MediaJobs` product behavior, WU2 schemas, or MP4 verifier assumptions.
- **Tasks:** validate bounded image input; orient and color-normalize; scale without crop/upscale; apply approved transform; encode PNG; verify output signature/decode/dimensions/alpha/color metadata; handle invalid input, capability absence, timeout, cancellation and cleanup.
- **Tests:** no-FFmpeg unit tests with fakes; FFmpeg integration tests with generated small JPEG/PNG/WebP fixtures where supported; EXIF rotations, alpha, profiles, invalid/oversized files, path safety, output decode, dimensions, source immutability, missing filter/tool, timeout/cancel/reap, failure cleanup, Windows Unicode paths.
- **Acceptance:** generated stills render within approved limits; output independently decodes and verifies; failures never claim success or alter sources; request-owned scratch is cleaned on all paths; Windows/Linux behavior matches declared contract.
- **Exclusions:** video/album/Short render, portrait composition/motion, preview API/cache, frontend, persistence, changes to WU2 synthetic contract.
- **Approval before start:** Phase 2-specific image and transform decisions.

### Phase 3 — Preview service and disposable caching

- **Prerequisites / approval:** Phase 2 authoritative still service; approved minimal API request/response/error schema and route; cache canonicalization/versioning; limits, queue and cancellation policy. No route is approved by existing docs.
- **Anticipated files/modules:** thin application preview use case/port and FastAPI adapter only after contract approval; cache implementation using bounded disposable storage; contract/API tests. Keep endpoints out of WU2 worker/job contract unless separately approved.
- **Tasks:** validate request identity; execute authoritative still render; calculate versioned content-derived cache identity; bound cache and worker concurrency; cancel queued/in-flight superseded work; return typed busy/validation/render errors; avoid leaking filesystem paths.
- **Tests:** API positive/negative contract; cache hit/miss/invalidation by each key component; version bump invalidation; eviction/TTL/bounds; concurrent requests and bounded queue; cancellation before/after process start; timeout/error mapping; no persistent override data; no WU2 worker starvation.
- **Acceptance:** same content/settings/geometry/version reuses only a verified disposable result; any identity change invalidates; concurrency and cancellation obey approved limits; errors are typed and path-safe.
- **Exclusions:** durable final-artifact publication, override persistence, full job UI, motion preview, full Review.
- **Approval before start:** API, error, cache, and concurrency contracts.

### Phase 4 — Minimal preview/comparison UI

- **Prerequisites / approval:** confirm/establish frontend project in a separately approved scope if absent; Phase 3 contract and exact error/loading semantics; accessibility behavior. Do not implement the full Review workflow.
- **Anticipated files/modules:** reusable React preview/treatment/comparison components in the actual approved frontend source; derived client types from approved schema/OpenAPI; unit/component and browser tests. No frontend path is currently established by the workspace inventory.
- **Tasks:** immediate labelled approximate proxy; display authoritative rendered still; Original/Split/Treated views; same-source comparison; split keyboard and pointer interaction; stale response suppression; loading/empty/error/stale display; retain last confirmed result.
- **Tests:** picker/HEX synchronization and invalid drafts if included in approved slice; mode-specific behavior; same-frame identity; accessibility labels/slider semantics/focus; keyboard split movement; stale response races; error retains original/last confirmed; loading/empty states; browser smoke/Playwright.
- **Acceptance:** approximate rendering is never represented as authoritative; rendered result corresponds to current content/settings/version; Original and Treated share geometry/source; stale results cannot replace current; UI remains usable with errors and keyboard.
- **Exclusions:** full Review workflow, waveform editing, persistence, batch metadata, integrated render UX, motion/effects.
- **Approval before start:** frontend availability, UI scope, API client and accessibility details.

### Phase 5 — Visual regression and integration hardening

- **Prerequisites / approval:** stable transform and still service; approved comparison color space and numeric/perceptual tolerances; controlled supported FFmpeg builds; deterministic fixtures.
- **Anticipated files/modules:** generated reference artwork/fixtures and visual integration tests in backend tests; CI workflow changes only after separate approval and only if needed. This documentation does not authorize workflow edits.
- **Tasks:** compare independent reference transform and FFmpeg output on decoded pixels; report FFmpeg/FFprobe versions, pixel format, color metadata; test repeated output and cross-platform behavior; run existing WU1/WU2 suites unchanged.
- **Tests:** neutral ramps, shadows/highlights, saturated target/source colors, intensity endpoints, alpha, dimensions, filter order, repeated render; decoded-image/per-channel MAE and a perceptual check under approved thresholds; Windows and Linux; Python 3.11/3.12; existing WU1/WU2 contracts and synthetic FFmpeg integration.
- **Acceptance:** decoded pixels meet documented tolerances on supported matrix; no comparison uses encoded-file byte equality; no nondeterministic effects are present; all prior WU1/WU2 tests continue to pass without weakening, skips, or altered expectations.
- **Exclusions:** ProRes/cross-codec requirement, motion regression, full end-to-end Review/render workflow, deferred effects.
- **Approval before start:** threshold values, comparison space, CI matrix changes, and accepted FFmpeg build variation.

## 10. Testing and CI principles

- Preserve all WU1/WU2 tests and contracts. Do not weaken assertions, change synthetic-render behavior, or add unapproved skips.
- Separate pure resolver/contract tests from FFmpeg-dependent integration tests. Tool-required tests must report explicit skips locally when binaries are absent; CI media jobs must install/use approved tools without auto-downloading from application code.
- For image regression, compare decoded pixels after a declared conversion to a declared comparison space. Use fixed artwork and settings, per-channel/MAE tolerance and a perceptual check. Never compare encoded MP4/PNG file hashes as a visual equivalence criterion.
- Record FFmpeg and FFprobe versions/build, filter capability, output pixel/color metadata, platform, Python version, test commands, pass/fail/skip counts, and known limitations.
- Maintain Python 3.11 and 3.12 compatibility, Windows and Linux behavior, source-file immutability, bounded CPU/memory/time, and safe cleanup.
- Existing WU2 CI baseline in Doc 34 includes Ubuntu Python 3.11/3.12 and a Windows Python 3.12 FFmpeg smoke test. WU3 should extend rather than replace it, subject to approved CI changes.

## 11. Overall acceptance criteria

WU3 is complete only after all approved phases satisfy their phase-specific criteria and user-approved contracts, while:

1. Auto resolution follows Doc 25 precedence and has deterministic, explainable fallback; no mood enum, inferred numeric feature, LLM, or random selection is introduced.
2. Presets and custom HEX are validated against an approved versioned contract; intensity behavior and endpoints are explicitly tested.
3. Authoritative still rendering and any later product renderer use the same approved transform specification; browser proxy remains explicitly approximate.
4. Original/Split/Treated compare the same source frame and geometry; stale results are invalidated and failures retain the last confirmed/original view.
5. Image boundaries, output, verification, cancellation, cache, concurrency, and error behavior meet approved cross-platform contracts.
6. Decoded-pixel regression tests use documented tolerances and do not compare encoded bytes.
7. WU1/WU2 tests and WU2 synthetic-media behavior remain intact and pass.
8. No full WU4 workflow, persistence, waveform, full album/Short rendering, metadata/upload, or deferred motion effect has entered WU3.

These criteria are planning targets until the user approves the individual contracts and phase gates.

## 12. Risks and unresolved decisions

### Phase 1 choices awaiting product approval

- Exact stable preset HEX mappings; implemented table is provisional and reported above.
- Palette order/tie-break and whether optional feature weighting will ever be supported; Phase 1 validates every entry, chooses the first entry in a valid non-empty palette, and applies no weighting.
- Input/output contract shape and version identifiers, required/default intensity semantics, source/reason values.
- Pure-domain error identifiers and whether they need a later API mapping; no HTTP endpoint or API envelope is implemented in Phase 1.
- Whether the track-preference input shape should remain `hex`-only and how the Doc 18 legacy fields are adapted in a later approved boundary. Existing canonical manifest and WU1 schemas remain unchanged.

These are product-approval items for treating Phase 1 proposals as stable, not blockers to the Phase 1 implementation authorized by the user.

### Can wait until Phase 2 or later

- Final color-transform choice, FFmpeg graph/filter availability, rounding and numerical tolerances; prove candidate before selecting.
- Accepted formats/size/dimensions, EXIF/ICC and alpha policy, PNG output geometry, output verification, timeout and cancellation limits.
- Preview route, request/response/error schema, cache serialization, concurrency and busy response.
- Frontend project location/availability, exact UI copy, and component-level interaction details.
- Visual comparison space/tolerance and CI job matrix changes.
- Override persistence and legacy migration; out of WU3 unless the user separately changes scope.

### Documentation/implementation risks

- Doc 32 assumes a later-unit UI but the current workspace inventory has no frontend application. Phase 4 cannot be scoped to files until confirmed.
- The color examples contain sample HEX values, but Doc 31 forbids treating them as approved mappings.
- WU2 reuses filesystem/job ideas but its worker/verifier are synthetic MP4-specific; accidental coupling can change WU2 production behavior.
- Cross-platform FFmpeg color conversion and rounding may differ by build; tests need a proven comparison contract, not an assumed bit-exact result.
- Preview limits and cache policy are resource-affecting product decisions and need approval before service implementation.

## 12.1 Previous Phase 1 validation evidence

The following is historical evidence from before the independent review corrections. The earlier 47 focused passes and 178 backend passes are superseded by Section 12.2.

Executed on Windows (PowerShell) with CPython 3.12.3, on 2026-10-21:

- `python -m pytest backend/tests/unit/test_color_resolution.py backend/tests/contracts/test_color_resolution_contract.py -q` — **47 passed**.
- `python -m pytest backend/tests -q` — **178 passed, 3 skipped** in 30.32 seconds.
- `python -m compileall -q backend/src backend/tests` — passed (no output/errors).
- `git diff --check` — passed (no whitespace errors).

The three skips are existing platform-conditional WU2 tests: one POSIX process-group descendant-semantics test on Windows, and two directory-symlink tests skipped because this Windows user context lacks the required symlink privilege. No FFmpeg-dependent test was skipped in the reported full run; no Phase 1 FFmpeg tests were added or required. Only Windows/Python 3.12.3 was executed; Python 3.11 and Linux were not tested in this session.

The active Python environment initially lacked `pytest` and `jsonschema`, and the local package was not installed. To run the requested checks, installed the declared test/runtime dependencies (`pytest==8.4.2`, `jsonschema>=4.21,<5`, `portalocker>=3.1,<4`, and Windows-marked `pywin32>=306`) and installed the repository editable with `--no-deps`. No repository dependency files were changed.

## 12.2 Review-correction validation evidence

Executed on Windows 11 (PowerShell), CPython 3.12.3, on 2026-10-21. `pytest` and `jsonschema` were already installed for this pass; no packages were installed. Coverage tooling was not installed. The Windows Python launcher lists Python 3.12.3 and Python 2.7 only; Python 3.11 was unavailable. Linux was not tested.

- `python -m pytest backend/tests/unit/test_color_resolution.py backend/tests/contracts/test_color_resolution_contract.py -q` — **111 passed**.
- `python -m pytest backend/tests/contracts -q` — **70 passed**.
- `python -m pytest backend/tests -q` — **242 passed, 3 skipped** in 44.84 seconds (final rerun).
- `python -m compileall -q backend/src backend/tests` — passed; standalone post-documentation rerun pending.
- Skips are existing platform limits: one POSIX process-group descendant-semantics test and two directory-symlink tests skipped because this Windows context lacks symlink privileges. No FFmpeg-dependent test was skipped.
- Schema tests validated positive and negative fixtures, all generated resolver mode/precedence outputs, nested context agreement, and contradictory output rejection.

## 13. Phase 1 implementation record and approval status

Phase 1 has been implemented within the authorized pure-domain boundary. The following records authoritative requirements, provisional choices, and the remaining approval boundary; it does not authorize additional work.

### Authoritative requirements to carry into Phase 1

- Modes: `auto`, `preset`, `custom` (Doc 18).
- Custom HEX is six-digit sRGB notation; normalize to uppercase; intensity is finite and inclusive `[0.0,0.6]` (Doc 18).
- `original` means no tint; invalid backend color payloads are rejected and cannot partially persist (Doc 18).
- Auto precedence and unknown/missing mood behavior follow Doc 25; unknown mood is unrestricted text, ignored safely, and missing numeric observations are never invented.
- Equal normalized inputs and resolver version must resolve deterministically (Doc 25).
- Domain/application layering has no FastAPI/FFmpeg/React dependency (Docs 32 and 34).
- Existing manifest, override-store, API-error, and WU2 snapshot schemas remain unchanged in this phase.

### Decisions that remained pending after Phase 1

The 2026-10-21 Phase 2 recovery authorization recorded in Section 15 approves the implemented resolver and preset mapping **for provisional Phase 2 v1 compatibility only**. It does not make these permanent project-wide requirements. The following historical list remains relevant to any later stabilization or incompatible revision.

1. Approve, revise, or replace the preset IDs and complete provisional HEX mapping.
2. Approve the exact Auto palette tie-break. Proposed first entry after validating every palette entry, no numeric weighting initially; otherwise state deterministic rule and whether supplied features affect selection.
3. Approve, revise, or replace the implemented input/output contract fields, source/reason vocabulary, resolver version and schema name/version. No route or persistence schema is part of this phase.
4. Approve intensity semantics when omitted, behavior for preset `original`, and whether invalid mode-specific extra fields are rejected.
5. Approve pure-domain validation error categories (not an HTTP envelope) and compatibility boundary for legacy fields. The resolver accepts only its versioned treatment envelope; Doc 18's legacy-field adapter and explicit conflict behavior remain required at a future boundary that accepts legacy fields.
6. Treat the implementation as provisional until the above choices receive product approval; the Phase 1 implementation itself was explicitly authorized in this request.

### Phase 1 implemented change/test list

- Added pure domain color validation and deterministic resolver under `backend/src/wrld_video_studio/domain/color_resolution.py`.
- Added provisional versioned color-resolution schema under `contracts/schemas/color-resolution-v1.schema.json`.
- Added focused unit and contract tests under `backend/tests/unit/` and `backend/tests/contracts/`.
- Do not edit `AGENTS.md`, existing specifications/schemas, WU1/WU2 source/tests, frontend, HTTP routes, or dependency files.
- Test mode validation; exact preset mapping; precedence; palette tie-break; unknown/missing mood; absent numeric values; empty/invalid palette; custom HEX normalization; invalid HEX/intensity/preset; endpoint behavior; deterministic output/version; input immutability; and import boundaries.

### Phase 1 acceptance result

- The only implementation additions are the pure resolver, isolated new schema, and focused tests; Doc 37 was updated. Existing WU1/WU2 production source and contracts were not modified.
- Doc 25 precedence and the provisional first-entry tie-break with strict malformed-palette rejection have explicit tests.
- Same normalized inputs/version produce stable output and fingerprint; input metadata is not mutated.
- Invalid values are rejected deterministically and never silently clamped.
- Focused and full validation results, including the actual Python/OS and skips, are recorded in Section 12.2.
- No FFmpeg, image decoding, frontend, route, persistence, WU2 behavior, or production render changes were included.

## 14. Codex/Copilot implementation handoff

This handoff is self-contained; do not rely on prior chat or session memory.

1. Start by reading `AGENTS.md`, Docs 18, 22, 25, 27, 31, 32, 34, 35, this document, and inspect actual WU1/WU2 source/tests. Doc 32 controls WU3 scope; Doc 31 controls conflicts and approval.
2. Verify branch, HEAD, clean/dirty status, and master relationship before edits. Do not assume the baseline in this document remains current.
3. Section 15 is the approval record for provisional Phase 2 v1. It supersedes the earlier pending-approval labels only for the exact Phase 2 choices listed there; those choices are not permanent project-wide requirements. Obtain approval for any incompatible change.
4. Phase 2 recovery is authorized only through the tested boundary in Section 15. Do not proceed to Phase 3 while FFmpeg integration and decoded-pixel tolerances remain unverified.
5. Reuse WU2 process/tool/filesystem patterns only in later approved phases. Keep the still renderer separate from `SyntheticMediaEncoder` and do not change synthetic WU2 schemas, worker semantics, or tests.
6. Do not implement routes, frontend, persistence, full Review, waveform, full album/Short rendering, upload, motion preview/effects, or CI changes without their phase-specific contracts and approval.
7. Never edit `legacy_v2/`. Never compare encoded file bytes as visual output equivalence. Preserve all prior tests and source files.

### AGENTS.md compatibility note

Current `AGENTS.md` is compatible with this plan: it requires read-before-change, no invented requirements, user approval, and no legacy-v2 changes. A future, separately authorized update could add a pointer to this Doc 37 and state that its proposals are non-normative until approved. Do not modify `AGENTS.md` as part of this task.

## 15. WU3 Phase 2 recovery implementation record (2026-10-21)

### 15.1 Approval scope and status

The user approved the following choices for **provisional Phase 2 v1 implementation**, not as permanent project-wide requirements:

- transform `linear-luma-chroma-v1`, using the existing linear-light, source-luminance-preserving chroma algorithm;
- resolver `1.0.0-provisional.1` and preset mapping `provisional-1`, including their existing preset table, as the only Phase 1 versions accepted by this renderer;
- PNG, JPEG, and WebP still input; one PNG output; 40 MiB, 40 megapixel, and 10,000-pixel-side input limits; longest output side 1024 pixels with aspect preservation and no upscale;
- EXIF orientations 1 through 8, independent alpha handling, ordinary sRGB/untagged-sRGB inputs, and explicit rejection of embedded ICC or unsupported profile metadata;
- WU2 process-runner/tool-discovery reuse, explicit FFmpeg capability checks, configurable render timeout defaulting to 30 seconds, cancellation, owned staging cleanup, no-replace publication, source immutability checks, and typed failures;
- decoded-pixel comparison rather than encoded PNG byte identity.

The implementation status is **PARTIALLY COMPLETE**. Contracts, domain mathematics, Python/runtime validation, fake-runner orchestration, and unit coverage are verified. Authoritative FFmpeg rendering, supported-build decoded-pixel tolerance measurement, and the full real-media matrix are unverified because no FFmpeg or FFprobe executable is available in the current environment. No tool was downloaded or installed.

### 15.2 Final provisional contracts and versions

- `still-render-request-v1`
- `still-render-result-v1`
- renderer `ffmpeg-still-v1`
- transform `linear-luma-chroma-v1`
- nested Phase 1 output `color-resolution-output-v1`
- resolver `1.0.0-provisional.1`
- preset mapping `provisional-1`

`contracts/schemas/still-render-v1.schema.json` is Draft 2020-12 and references `color-resolution-v1.schema.json#/$defs/output` rather than copying its branch table. The Phase 1 schema now pins the exact supported resolver and preset-mapping versions. Consequently the nested still contract and the Python adapter reject fabricated versions and contradictory mode/HEX/intensity/preset/source/reason combinations under the same Phase 1 rules. Still requests also pin renderer/transform versions and a lowercase relative `.png` destination with no absolute, drive-qualified, or parent-traversal path. Results pin PNG/RGBA metadata, dimensions in `[1,1024]`, normalized EXIF orientation text, hashes, treatment, tool version, and a non-empty sanitized command.

Positive and negative JSON fixtures cover valid request/result envelopes, contradictory Phase 1 output, and unsupported version identifiers. Contract tests also nest every generated Phase 1 resolver branch in a still request.

### 15.3 Exact `linear-luma-chroma-v1` mathematics

For each source RGB channel `s` represented in sRGB `[0,1]`, decode to linear light:

```text
decode(s) = s / 12.92                                  when s <= 0.04045
          = ((s + 0.055) / 1.055) ^ 2.4               otherwise
```

Let decoded source be `S = (Sr,Sg,Sb)` and decoded target HEX be `T`. Rec.709 linear luminance is:

```text
Y(V) = 0.2126 Vr + 0.7152 Vg + 0.0722 Vb
```

For target luminance `Yt > 0`, target chromaticity is `C = T / Yt`. At intensity `a` in inclusive `[0,0.6]`, form:

```text
Q = (1 - a) S + a Y(S) C
N = (Y(S), Y(S), Y(S))
D = Q - N
```

Gamut handling desaturates toward the same-luminance neutral point. Starting from `k = 1`, include `(1-Y)/Di` for every `Di > 0` and `Y/(-Di)` for every `Di < 0`, then set `k` to the minimum of those values clamped to `[0,1]`. The output linear channel is `Oi = clamp(Ni + k Di, 0, 1)`. This preserves source luminance before final 8-bit quantization while keeping channels in gamut.

Encode each channel back to sRGB:

```text
encode(o) = 12.92 o                                    when o <= 0.0031308
          = 1.055 o ^ (1 / 2.4) - 0.055               otherwise
```

The Python reference quantizes with `floor(clamp(channel,0,1) * 255 + 0.5)`, meaning round-to-nearest with exact ties upward. `original`, intensity zero, a zero-luminance source, and target `#000000` are defined untreated/no-op cases after that declared 8-bit quantization. Black is not an error. Alpha never participates in RGB math and is carried on a separate FFmpeg path.

The candidate FFmpeg graph explicitly requests full-range RGB, Rec.709 primaries, sRGB/linear transfer conversion, no dithering, explicit `[0,1]` clamps, and an RGB24 quantization boundary before alpha merge. Its exact supported-build rounding difference has not been measured in this environment and is therefore not yet an accepted tolerance claim.

### 15.4 Image, execution, cancellation, and artifact policy

- Source validation first checks regular-file existence, non-empty size, the 40 MiB limit, supported suffix, container signature, and profile metadata. It then validates FFmpeg capabilities and performs a bounded metadata probe.
- Container codec must match `.png`, `.jpg`/`.jpeg`, or `.webp`. Positive dimensions are checked against 10,000 pixels per side and 40 megapixels before the more expensive frame-count pass. Frame count must be exactly one.
- EXIF orientation is parsed and normalized explicitly; oriented dimensions drive aspect-preserving, no-upscale sizing to a maximum side of 1024.
- Required FFmpeg filters are `alphaextract`, `alphamerge`, `format`, `geq`, `hflip`, `scale`, `split`, `transpose`, `vflip`, and `zscale`; required encoder is `png`. Missing, failed, timed-out, and cancelled capability probes have typed failures.
- Render timeout is constructor-configurable and defaults to 30 seconds. The caller's cancellation event is passed through capability, probe, render, and verification process calls where the WU2 runner supports it; cancellation before tool access is also honored.
- Output is created in an owned sibling staging file, flushed, and atomically hard-linked to the final path without replacement. Case-insensitive `.wrld-staging` and `.wrld-promotions` path variants are reserved. Staging is removed on success, failure, timeout, or cancellation. A cleanup failure is retained in typed diagnostics; a post-publication cleanup failure is marked `commit_state: committed`.
- The source SHA-256 is computed before rendering and checked again before publication. The renderer never intentionally writes source artwork.
- Stable error categories now distinguish invalid/unsupported contracts, versions, resolution data and paths; missing capabilities; corrupt, oversized, animated, profile-bearing, or extension-mismatched images; timeout/cancellation; invalid output; collision; source change; and storage failure.

These choices do not modify or route through the WU2 `SyntheticMediaEncoder`, job worker, MP4 verifier, schemas, or production behavior.

### 15.5 Independent reference and current test evidence

The FFmpeg integration test no longer calls the production transform to compute expected pixels. It has a separate test-side implementation of sRGB transfer, Rec.709 luminance, chromaticity interpolation, gamut scaling, clamping, and ties-up quantization. Pure unit tests add reviewed fixed 8-bit vectors for neutral gray, near-black, near-white, saturated red/green/blue, a neutral target, black no-op, transfer boundaries, gamut bounds, and quantization ties. Integration cases cover custom/preset treatment, intensity `0.6`, original/zero/black, alpha, repeat rendering, collision, source immutability, invalid input, and resizing logic; real media cases are currently skipped at tool discovery.

Final recovery validation on Windows 11, CPython 3.12.3, using the existing `.venv`:

- `python -m pytest backend/tests/contracts -q` — **87 passed**.
- `python -m pytest backend/tests/unit -q` — **230 passed, 3 skipped**; the skips are the existing Windows POSIX/symlink limitations.
- `python -m pytest backend/tests/unit/test_still_image_renderer.py backend/tests/unit/test_color_transform.py -q` — **64 passed**.
- `python -m pytest backend/tests/integration/test_wu3_still_renderer.py -q -rs` — **1 passed, 5 skipped**; all five media cases report `MEDIA_TOOL_MISSING` for FFmpeg.
- `python -m pytest backend/tests -q` — **319 passed, 13 skipped**. Five WU2 and five WU3 integration skips are due to missing FFmpeg; three are the existing Windows POSIX/symlink limitations.

No cross-version or cross-platform PNG byte-identity claim is made. The current integration assertion contains an explicitly named, unverified analytical two-code-value ceiling only to retain a future executable comparison; it is not a measured acceptance threshold and cannot satisfy Phase 2 completion.

### 15.6 Unverified behavior, remaining Phase 2 work, and Phase 3 dependency

The following work requires a compatible existing or separately provisioned FFmpeg/FFprobe environment:

1. Validate reported filters/encoder and the full graph syntax on the supported FFmpeg build.
2. Decode PNG/JPEG/WebP fixtures and cover animated input, EXIF orientations 1–8, alpha, resize/no-upscale boundaries, profile rejection, Unicode paths, corrupt output, real timeout/cancellation/reaping, repeat determinism, and source immutability end to end.
3. Measure per-channel/aggregate decoded-pixel error against the independent reference over neutral ramps, near-black/highlights, saturated sources/targets, presets/custom colors, black, and intensity endpoints. Replace the unverified analytical ceiling with the measured and approved tolerance.
4. Repeat on the supported Windows/Linux and Python/FFmpeg matrix and record tool builds and color/pixel metadata. Compare decoded pixels, not encoded PNG bytes.

Phase 3 preview service/caching remains out of scope and must not begin until the authoritative still path and its measured decoded-pixel contract are verified and accepted. Phase 4 UI, Phase 5 broader visual regression, motion, album/Short rendering, and WU4-WU6 remain excluded.

## 16. WU3 Phase 2 Windows FFmpeg verification (2026-10-21)

This section supersedes Section 15's statements that FFmpeg was unavailable and that the graph/tolerance were unverified. It does not authorize Phase 3 and does not make one Windows build a cross-platform guarantee.

### 16.1 Approved installation and integrity evidence

The user approved a user-local Gyan FFmpeg release-essentials installation. No repository dependency, global/system setting, or existing installation was modified.

- Publisher archive: `ffmpeg-release-essentials.zip`, 114,768,076 bytes.
- Publisher SHA-256: `60F467265B1E312373DBCD92200C2618A74850F98D3D078E94296BB3FA2047BA`.
- Downloaded SHA-256: `60F467265B1E312373DBCD92200C2618A74850F98D3D078E94296BB3FA2047BA`.
- Extraction occurred only after the hashes matched.
- Install root: `C:\Users\ptanz\AppData\Local\Programs\FFmpeg`.
- Extracted content: 45 files, 329,221,735 bytes.
- Temporary archive and checksum files were removed after successful extraction.
- Tests set `WRLD_FFMPEG_PATH` and `WRLD_FFPROBE_PATH` only in their command processes. No persistent WRLD variable or PATH change was made. A separate pre-existing WinGet Gyan 9.0.1 installation remains on the user PATH and was not used or modified; every recorded verification command used the explicit 9.0.2 paths below.

Executable evidence:

- FFmpeg: `C:\Users\ptanz\AppData\Local\Programs\FFmpeg\ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe`; SHA-256 `3256173F3F8BFFD7DF12227C68ADF68025EDB1832273A9530688A7BB1ED8EDEC`.
- FFprobe: `C:\Users\ptanz\AppData\Local\Programs\FFmpeg\ffmpeg-9.0.2-essentials_build\bin\ffprobe.exe`; SHA-256 `F0D36ECBBDD3BCFAC3EFA078C96C7271C2E68B3810595552AC3B7F17E9A65C52`.
- Both report `9.0.2-essentials_build-www.gyan.dev`, built with GCC 16.2.0 (MSYS2 Rev3).

Build configuration reported by both tools:

```text
--enable-gpl --enable-version3 --enable-static --disable-w32threads --disable-autodetect --enable-cairo --enable-fontconfig --enable-iconv --enable-gnutls --enable-libxml2 --enable-gmp --enable-bzlib --enable-lzma --enable-zlib --enable-libsrt --enable-libssh --enable-libzmq --enable-avisynth --enable-sdl2 --enable-libwebp --enable-libx264 --enable-libx265 --enable-libxvid --enable-libaom --enable-libopenjpeg --enable-libvpx --enable-mediafoundation --enable-libass --enable-libfreetype --enable-libfribidi --enable-libharfbuzz --enable-libvidstab --enable-libvmaf --enable-libzimg --enable-amf --enable-cuda-llvm --enable-cuvid --enable-dxva2 --enable-d3d11va --enable-d3d12va --enable-ffnvcodec --enable-libvpl --enable-nvdec --enable-nvenc --enable-vaapi --enable-openal --enable-libgme --enable-libopenmpt --enable-libopencore-amrwb --enable-libmp3lame --enable-libtheora --enable-libvo-amrwbenc --enable-libgsm --enable-libopencore-amrnb --enable-libopus --enable-libspeex --enable-libvorbis --enable-librubberband
```

Reported library versions are libavutil 61.1.102, libavcodec/libavformat 63.1.102, libavdevice/libavfilter 63.1.102/12.1.102, libswscale 10.1.102, and libswresample 7.1.102.

### 16.2 Verified capabilities

Token-based enumeration against the actual binary confirmed every required filter: `alphaextract`, `alphamerge`, `format`, `geq`, `hflip`, `scale`, `split`, `transpose`, `vflip`, and `zscale`. The native `png` video encoder is present. PNG, MJPEG/JPEG, static WebP, and animated WebP decoders are present; the renderer accepts only the approved static `png`, `mjpeg`, and `webp` inputs and rejects `webp_anim` with `ANIMATED_IMAGE_UNSUPPORTED`.

### 16.3 Verified adapter defects and repairs

Real execution revealed three adapter defects. None required changing the approved mathematical model.

1. The recovered graph converted RGBA to `gbrpf32le` through FFmpeg's format filter before inverse sRGB transfer. On this build, 8-bit white became float `0.9961547256`, then linear `0.9912750125`, producing gamut-boundary RGB errors up to five codes. Direct RGBA into zscale preserved white but premultiplied translucent RGB by alpha. The repaired graph therefore drops alpha through a lossless `format=rgb24` boundary, then performs zscale linearization; alpha continues independently through the existing split/extract/merge path.
2. FFmpeg copied source PNG `eXIf` into the already explicitly oriented output despite `-map_metadata -1`. Normal decoders then applied the stale orientation a second time. The renderer now removes only `eXIf` chunks from its owned staged PNG before verification/publication. Real tests cover orientations 1 through 8 and verify that output metadata returns to orientation 1.
3. FFprobe 9.0.2 identifies animated WebP as codec `webp_anim`; the recovered codec whitelist classified it as generic corrupt/unsupported input before frame counting. It is now rejected directly with the stable animated-input error.

### 16.4 Decoded-pixel measurement

The independent test implementation remains separate from production transform code. The measurement matrix contains 28 source RGB values: a neutral ramp including black, near-black, midtones, near-white and white; saturated primaries and secondaries; mixed saturated colors; and additional near-black colors. Alpha cycles through 28 values. Eleven render cases cover all five colored presets, custom saturated/neutral/white/black targets, intensities `0.0`, `0.3`, and `0.6`, and no-op behavior.

Before the RGB-boundary repair, 924 RGB channel comparisons produced `{0: 881, 1: 33, 2: 4, 3: 2, 4: 2, 5: 2}`, maximum error 5 and MAE 0.070346320; the small MAE hid serious boundary outliers. After the repair:

- RGB comparisons: 924.
- Error histogram in 8-bit code values: `{0: 635, 1: 289}`.
- Maximum absolute RGB error: 1 code value.
- RGB MAE: 0.312770563 code values.
- Alpha comparisons: 308; maximum error 0.
- Original, zero intensity, and black target are byte-exact no-ops in the tested PNG matrix.

The provisional two-code ceiling is removed. The Windows/Gyan 9.0.2 acceptance bound is now a measured maximum of one 8-bit RGB code value per channel with exact alpha. Encoded PNG bytes are not compared or claimed stable.

### 16.5 Real-media and regression evidence

The expanded WU3 integration suite exercises PNG, JPEG, lossless WebP, animated WebP rejection, all EXIF orientations, alpha, preset/custom/black/original/zero treatments, neutral and saturated reference pixels, actual 1200x600 to 1024x512 downscaling, no-upscale behavior, Unicode paths, ICC/profile rejection, deterministic repeat output, no-replace collision, source immutability, real timeout cleanup, pre-cancellation, corrupt/unsupported/oversized input, traversal rejection, and independent decoded-pixel comparison.

Executed on Windows 11 and CPython 3.12.3 with explicit Gyan 9.0.2 paths:

- `python -m pytest backend/tests/integration/test_wu3_still_renderer.py -q -rs` — **19 passed** in 20.43 seconds.
- `python -m pytest backend/tests/unit/test_still_image_renderer.py backend/tests/unit/test_color_transform.py backend/tests/integration/test_wu3_still_renderer.py -q -rs` — **83 passed** in 21.29 seconds.
- `python -m pytest backend/tests/contracts -q` — **87 passed**.
- `python -m pytest backend/tests/unit -q` — **230 passed, 3 skipped**.
- `python -m pytest backend/tests -q -rs` — **342 passed, 3 skipped** in 47.12 seconds on the final documented file state. This executed all five existing WU2 FFmpeg integrations and all WU3 media integrations. The remaining skips are one POSIX-only process-group test and two Windows directory-symlink tests lacking privilege.
- `python -m compileall -q backend/src backend/tests` — passed.

One initial WU3 run transiently skipped a case when Windows Job Object ownership setup failed during tool discovery. A direct rerun passed, the integration skip helper was narrowed to skip only `MEDIA_TOOL_MISSING`, and subsequent complete WU3/full-suite runs passed without hiding ownership failures.

### 16.6 Status and remaining coverage

The authoritative Phase 2 still renderer is **verified on Windows 11 with Gyan FFmpeg/FFprobe 9.0.2 essentials**. Remaining gaps are Linux execution, Python 3.11, other FFmpeg builds/versions, mid-process (rather than pre-start) real cancellation timing, broader JPEG/WebP samples and color-tag variants, and cross-platform confirmation that the one-code bound holds. These are portability/coverage gaps, not known Windows reference-build defects. Phase 3 remains out of scope and must not begin from this verification record alone without its separate authorization.

## 17. WU3 Visual Rendering CI baseline

`.github/workflows/wu3-visual-rendering.yml` adds dedicated WU3 automation for pushes and pull requests targeting `master` or `feature/wu3-visual-rendering`, plus manual dispatch. It grants only read access to repository contents.

The CI matrix is Ubuntu/Python 3.11 for WU3 media compatibility and Ubuntu/Python 3.12 plus Windows/Python 3.12 for contract, unit, WU3 real-media, and complete backend regression. The existing WU1/WU2 workflows retain their broader non-media Python coverage; the dedicated WU3 workflow does not repeat the complete pre-WU3 suite on its Python 3.11 compatibility entry.

Media tools are downloaded into the ephemeral runner directory and supplied through `WRLD_FFMPEG_PATH` and `WRLD_FFPROBE_PATH`; CI does not depend on runner-preinstalled tools or mutate global configuration. Windows uses the immutable Gyan `9.0.2-essentials_build` ZIP and publisher SHA-256 `60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba`. Linux uses BtbN's retained `autobuild-2026-09-30-13-08` GPL/static archive from the FFmpeg 9.0 release branch (`n9.0.2-17-g2a571b6068`) and published SHA-256 `68ee646831adaae2495618346f3bba94ff207ff83bbd34d643e7004730d66269`.

The builds are intentionally not claimed to be byte-identical: Windows is Gyan's MSYS2/GCC essentials build at upstream 9.0.2, while Linux is a BtbN static GPL release-branch build containing 17 later branch commits. Before tests, both must expose the required filters, PNG/JPEG/WebP fixture encoders, PNG/JPEG/WebP decoders (including animated WebP identification), and FFprobe. A missing tool or capability fails before pytest, so the WU3 suite cannot succeed through its tool-missing skip. Legitimate test-owned OS skips, such as POSIX versus Windows process-tree behavior or unavailable Windows symlink privilege, remain unchanged.

Python dependencies continue to use the repository's approved editable test installation, `python -m pip install -e ".[test]"`. The WU3-only `.github/wu3-ci-constraints.txt` snapshot pins the resolved runtime and test dependency graph, while pinned pip/setuptools versions and `--no-build-isolation` prevent an unbounded build backend from being fetched. `pip check` and a logged `pip freeze` expose the installed graph. Production dependency declarations in `pyproject.toml` are unchanged.

## 18. WU3 Phase 3A preview contracts and deterministic cache identity (2026-10-21)

### 18.1 Approval scope and architecture status

The user separately authorized Phase 3A after the Phase 2 and CI baselines above. This phase implements only pure preview contracts, validation, and deterministic cache identity. It does not implement source lookup or hashing, a filesystem cache, eviction, single-flight coordination, render scheduling, a worker, FFmpeg orchestration, HTTP/FastAPI routes, Pydantic models, frontend behavior, or animated previews. Phase 1 resolution, Phase 2 rendering, WU2 behavior, and `legacy_v2` remain unchanged.

The approved working architecture is synchronous and bounded, with an opaque server-owned artwork asset identifier. Its Phase 3A grammar is exactly 1–128 ASCII letters, digits, underscores, or hyphens (`^[A-Za-z0-9_-]{1,128}$`); periods, whitespace, Unicode, URL punctuation, drive delimiters, and path separators are rejected. Album, track, and Short identifiers remain request context and provenance, not pixel identity, and are not unnecessarily restricted by the artwork-ID policy. A caller cannot supply a local path or any trusted source, resolver, renderer, toolchain, cache, or verification metadata. The later Phase 3B source resolver must perform exact lookup of the opaque identifier in a server-owned registry and must never interpret it as a filesystem path. The later service is expected to use same-key single-flight generation, one active preview render, bounded waiting, WU2/full-render priority, and exact-key invalidation; none of that coordination is implemented in Phase 3A.

The following operational values are configurable provisional defaults, not permanent product requirements: 2 GiB maximum cache size, 2,000 entries, and 4 waiting requests. Phase 3A exposes the constants but does not implement storage, eviction, or waiting.

### 18.2 Versioned contracts

`contracts/schemas/preview-v1.schema.json` is a strict Draft 2020-12 schema with four definitions and no unknown properties:

- `preview-request-v1` contains a target (`album_id`, opaque `artwork_asset_id`, optional `track_id`, optional `short_id`), a Phase 1-compatible treatment selection, and the sole variant `authoritative_still`.
- `preview-result-v1` contains the preview ID, `hit`/`miss`, an opaque `preview:<sha256>` retrieval reference, `image/png`, dimensions, artifact and source hashes, the immutable Phase 1 resolved treatment, and cache-key/resolver/mapping/renderer/transform/toolchain provenance.
- `preview-error-v1` contains a typed code, non-empty message, JSON-compatible details, and correlation ID. Codes distinguish invalid request, source unavailable or changed, unsupported image, render failure, cancellation, timeout, capacity exhaustion, cache corruption, and internal failure. `SOURCE_CHANGED` deliberately preserves the existing Phase 2 mutation signal. HTTP status mappings are deferred to the adapter phase.
- `preview-cache-key-v1` describes the authoritative pixel inputs used to derive a preview ID.

The request schema reuses the Phase 1 treatment definition rather than pretending that a custom HEX selection is a complete resolved treatment. The result schema reuses the Phase 1 output definition. Request validation rejects paths, source hashes, resolved colors, version claims, binary fingerprints, cache keys, output paths, verification claims, and every other unknown field. JSON Schema provides structural validation only: it cannot prove that individually valid hashes, treatment provenance, and version fields came from the expected cache identity. `PreviewResult.from_dict()` therefore requires a separately supplied trusted `PreviewCacheIdentity` and additionally enforces semantic relationships, including `retrieval_reference == "preview:" + preview_id` and exact equality of every identity-derived field.

### 18.3 Cache descriptor and canonicalization

`backend/src/wrld_video_studio/domain/preview_cache.py` builds an immutable descriptor only from a server-derived full source SHA-256, a validated `ColorResolution`, and validated FFmpeg/FFprobe executable SHA-256 values. The Phase 3A boundary validator checks the complete applicable Phase 1 output contract: contract/resolver/mapping versions; mode; preset membership and preset-to-HEX mapping; normalized HEX; finite intensity; source/reason provenance; lowercase input fingerprint; and all mode, preset, treatment, and provenance cross-field invariants. Fabricated dataclass instances cannot enter identity or result construction merely by having plausible pixel fields. The builder does not accept a raw request, path, timestamp, context identifier, or caller-selected policy/version value.

The descriptor includes:

1. cache-key version;
2. source content SHA-256;
3. treated/untreated state, effective uppercase HEX or null, and effective intensity;
4. resolver and preset-mapping versions;
5. renderer and transform versions;
6. geometry and EXIF-orientation policy versions;
7. maximum longest side, no-upscale policy, Lanczos scaling, and no-dither policy;
8. PNG/RGBA output and the declared RGB color metadata;
9. exact FFmpeg and FFprobe executable SHA-256 values.

The preview ID is the lowercase SHA-256 of existing strict canonical JSON (`UTF-8`, sorted keys, compact separators, finite values only). Hashes must be lowercase 64-character hexadecimal strings. Negative zero is normalized to positive zero. Malformed hashes, non-finite numbers, inconsistent treated/untreated state, and unsupported versions or policies fail validation; they never receive substituted defaults. Untreated and treated-black states remain distinct. A separate toolchain fingerprint canonically hashes the two binary fingerprints with its own `preview-toolchain-fingerprint-v1` version.

The fixed independent test vector for source hash `3` repeated 64 times, custom `#ABCDEF` at `0.3`, FFmpeg hash `5` repeated 64 times, and FFprobe hash `6` repeated 64 times produces preview ID `7c2eadb17a2cfab9ed55570d6e68f72ee848b26d29af8307045df02cd60e84b3`. The expected descriptor and digest are constructed in the test without calling the production builder.

### 18.4 Trust boundary and source mutation

The caller-facing model accepts preference and context only. Trusted cache construction requires the concrete Phase 1 output type and a server-created toolchain identity; render policy is constructed internally from pinned Phase 2 values. Each cache identity retains its complete validated `ColorResolution` alongside—but not inside—the hashed descriptor. Pixel-equivalent custom, preset, and auto resolutions can therefore share a preview ID without losing the provenance for the current request. Every trusted `PreviewResult` carries a required, non-serialized identity binding. Its frozen dataclass post-initializer verifies preview ID, source hash, complete treatment provenance, cache/resolver/mapping/renderer/transform versions, toolchain fingerprint, and retrieval reference against that identity. The factory derives those fields from the identity; direct construction and `dataclasses.replace()` execute the same checks. `from_dict()` cannot establish trust from JSON alone and requires the expected identity from trusted server context. Frozen, slotted value objects and recursively frozen error details prevent mutable nested results.

`PreviewError.create()` treats `None` as empty details, accepts mappings, and rejects sequence-to-mapping coercion, non-string keys, non-finite values, malformed Unicode, and other non-JSON values. Nested objects and arrays are recursively frozen internally and thawed to schema-compatible JSON objects and arrays only for serialization.

Phase 3A intentionally does not open or hash source files. A later source adapter must hash the source before rendering, supply that digest to the identity builder, and rely on Phase 2's existing before-publication mutation check. If the source changes during rendering, the operation must return `SOURCE_CHANGED`, publish no artifact for the original key, and require the changed bytes to produce a new source digest and therefore a new key.

### 18.5 Validation evidence

Validation used Windows 11, CPython 3.12.3, the existing repository `.venv`, and—only for the full regression—the explicit approved Gyan FFmpeg/FFprobe 9.0.2 paths from Section 16. No dependency was installed and no persistent environment setting was changed.

- Phase 3A focused unit and contract tests: **188 passed**.
- Complete contract suite: **178 passed**.
- Complete unit suite: **329 passed, 3 skipped**. The skips are the existing POSIX process-group test and two Windows directory-symlink privilege cases.
- Complete backend suite with real WU2/WU3 media integrations: **532 passed, 3 skipped** in 43.12 seconds on the final trust-boundary repair state.
- Python compilation of `backend/src` and `backend/tests`: passed.
- `git diff --check`: passed.

Phase 3A itself is independently testable without FFmpeg; the explicit tools were used only to prevent established integration coverage from silently skipping during the complete regression.

The correction suite mutates every cache-descriptor leaf and proves each affects the digest, while separately proving album/track/Short context IDs do not. Identity-binding regressions substitute every authoritative result field with a validly formatted but incorrect value through direct construction, `dataclasses.replace()`, and untrusted JSON parsing. They also prove that same-key custom/preset resolutions cannot exchange request-specific provenance. Schema-valid integral JSON numbers such as `1.0` are normalized to Python integers during trusted parsing. Policy-drift coverage compares the Phase 3A descriptor against the exported Phase 2 renderer/max-dimension constants and exercises Phase 2's actual scaling, no-upscale behavior, explicit orientation filter, Lanczos/no-dither graph, PNG/RGBA output, and declared color metadata. Some Phase 2 policy strings remain intentionally duplicated because Phase 2 does not export a complete policy object; changing or centralizing those production values is outside Phase 3A. The behavioral comparison is the current drift detector, and any future policy change requires review of cache-key versioning.

### 18.6 Deferred work and next boundary

Phase 3B should implement only the server-owned artwork asset resolver and source snapshot/hash boundary needed to turn a validated request target into trusted source identity. It should define containment, regular-file and symlink policy, mutation/error propagation, and tests without adding cache storage, coordination, HTTP routes, or UI. Filesystem cache publication/verification/eviction, single-flight scheduling and WU2 priority, API mapping, and frontend review remain separate Phase 3C-3E decisions. Any future compatibility-family toolchain policy, new supported renderer/resolver/geometry/output policy, arbitrary preview dimensions, or changed cache identity requires explicit approval and an appropriate version change.
