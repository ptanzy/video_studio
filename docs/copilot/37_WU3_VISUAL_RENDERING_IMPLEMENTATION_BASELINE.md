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

## 19. WU3 Phase 3B secure artwork source resolution (2026-10-22)

### 19.1 Implemented scope and boundaries

Phase 3B implements only the trusted source-resolution and acquisition boundary. `AcquireArtworkSource` accepts an already validated Phase 3A `PreviewTarget` and passes only its `(album_id, artwork_asset_id)` composite identity to an `ArtworkSourceResolver` port. It never joins request text to a path. The infrastructure registry is built once from trusted server-side root and registration values, performs exact case-sensitive composite-key lookup, rejects duplicate keys and roots, stores immutable records behind read-only mappings, and has no caller-facing deserialization path.

The acquired `ArtworkSourceSnapshot` contains the opaque identities, request-owned snapshot path, full lowercase source SHA-256, and byte size. Its lease exposes explicit snapshot verification, original-source revalidation, idempotent cleanup, and context-manager ownership. This representation is directly consumable as the existing Phase 2 `StillRenderRequest.source_path`; Phase 2 production code is unchanged. The Phase 3B source-size limit and supported `.jpg`, `.jpeg`, `.png`, and `.webp` suffixes are checked against the existing Phase 2 boundary by regression tests.

Phase 3B does not implement preview cache storage, cache publication, eviction, single-flight coordination, render scheduling, HTTP routes, transport mappings, persistence, or UI. Those remain Phase 3C, 3D, and 3E work in the approved sequence.

### 19.2 Trusted roots, locality, and containment

Trusted roots and the separately provisioned snapshot root must already exist as real directories. Source and snapshot roots cannot identify the same directory or contain one another. Registered paths use normalized relative POSIX spelling and reject absolute paths, UNC/drive syntax, backslashes, empty components, `.` and `..`, NULs, and unsupported suffixes. Both roots and every source component are rechecked by the platform adapter; canonical string containment alone is never treated as sufficient.

On Windows, root inspection and acquisition use existing PyWin32 APIs. UNC roots are rejected before volume access. `GetVolumePathName` plus `GetDriveType` rejects mapped remote drives and fails closed for unknown or missing-root drive classifications; only removable, fixed, optical, and RAM-disk local classes are accepted. Root, intermediate directory, and leaf handles use `FILE_FLAG_OPEN_REPARSE_POINT`. Handle attributes reject every reparse point and require directories for parents and a non-directory leaf. `GetFileInformationByHandle` supplies volume/file identity, and `GetFinalPathNameByHandle` must remain beneath the registered root. The leaf is read through its Win32 handle with only read sharing, preventing cooperative writers from replacing or modifying it during acquisition. Real Windows junction tests cover intermediate, leaf, and root rejection without requiring symbolic-link privilege.

On Linux, initialization requires `O_NOFOLLOW`, `O_DIRECTORY`, and root-relative `dir_fd` support. A `statfs` check fails closed unless the root is on the explicit local-filesystem allowlist: ext2/3/4, XFS, Btrfs, tmpfs, OverlayFS, ZFS, F2FS, JFS, ReiserFS, NILFS, UBIFS, or ramfs. Consequently NFS, SMB/CIFS, FUSE, and every unknown filesystem type are rejected rather than presumed local. Acquisition opens the root directory descriptor, compares its device/inode identity with registration time, walks every parent with root-relative no-follow directory opens, and opens the regular-file leaf with no-follow semantics. Other POSIX platforms currently fail closed because equivalent filesystem-locality classification has not been verified.

The filesystem allowlist is deliberately operational policy rather than a claim that every possible local filesystem is unsafe. A new local filesystem must be reviewed and added explicitly; it is not silently accepted. No network adapter, URL source, remote share, or new dependency was introduced.

### 19.3 Snapshot, integrity, mutation, and cleanup semantics

Each acquisition creates a unique private directory beneath the trusted snapshot root and a suffix-preserving file with exclusive creation. The adapter hashes while copying, synchronizes and closes the file, marks it read-only, rewinds and independently hashes the still-open source a second time, then securely reopens the registered path and compares content hash plus platform file identity. A mutation, disappearance, or replacement—including replacement with identical bytes—produces `SOURCE_CHANGED` and removes partial owned state. Windows additionally prevents cooperative write/delete sharing while its source handle is open.

The returned lease records the snapshot identity, digest, and size. `verify_snapshot()` reopens the owned regular file without following POSIX links, hashes it, and compares all three values before consumption or acceptance. Snapshot replacement or content tampering produces `PREVIEW_INTERNAL_ERROR`. `revalidate_source()` repeats secure source acquisition and compares current content and identity with the acquired source, producing `SOURCE_CHANGED` if either differs. Callers must perform both explicit checks at their service boundaries; Phase 2 retains its own before/after render source hashing when it consumes the snapshot.

Cancellation is checked before lookup and throughout copy, source hashing, snapshot hashing, and revalidation. Pre-cancellation and deterministic mid-copy cancellation both remove the exact request-owned snapshot and directory. Cleanup never removes a broad tree, is idempotent after success, and reports an internal error rather than silently swallowing a cleanup failure. Snapshot storage/open/write/sync/protection failures are distinguished from source availability failures.

Errors reuse only the accepted preview-facing codes. Unknown registrations, unreadable/missing/non-regular sources, and rejected traversal return the path-safe `PREVIEW_SOURCE_UNAVAILABLE`; empty, oversized, or unsupported configured sources use `PREVIEW_IMAGE_UNSUPPORTED`; mutation/replacement uses `SOURCE_CHANGED`; cancellation uses `PREVIEW_CANCELLED`; and owned snapshot/storage failures use `PREVIEW_INTERNAL_ERROR`. Runtime error text does not include registered or canonical filesystem paths. Invalid trusted startup configuration raises configuration errors rather than masquerading as a request failure.

### 19.4 Threat model and limitations

The implemented boundary targets the approved cooperative local-writer model. Handle-relative/no-follow acquisition, Win32 reparse inspection, identity comparison, repeated hashing, and private snapshots close ordinary traversal, replacement, and mutation races. They do not claim protection from an administrator, kernel compromise, hostile mount-namespace changes, or a same-user attacker continuously racing path components and snapshot verification. Windows closes intermediate handles before opening the leaf, although final-handle containment and reparse inspection detect ordinary escapes. Read-only snapshot mode is defense in depth, not an ACL security boundary; a same-user actor may restore write permission, which is why identity and digest verification remain mandatory. There is necessarily a small interval between a caller's final verification and its consumer opening the snapshot; the existing Phase 2 renderer independently hashes before and after rendering.

Windows 11 and the Win32/PyWin32 path are exercised locally. This host does not grant unprivileged Windows symbolic-link creation, so two symbolic-link-specific tests skip with explicit privilege errors; actual Windows junction coverage exercises the same reparse rejection for roots, intermediate components, and leaves. No Linux runtime is installed on this workstation. Linux no-follow traversal and the actual `statfs` call therefore remain to be executed in Linux CI; deterministic classification tests cover accepted ext-family and rejected NFS/SMB/unknown magic values, but that is not equivalent to live Linux filesystem execution. Non-Linux POSIX is intentionally unsupported and fails closed.

### 19.5 Validation evidence

Validation used Windows 11, CPython 3.12.3, the existing repository `.venv`, and the explicit approved Gyan FFmpeg/FFprobe 9.0.2 paths from Section 16 for the complete backend regression. No dependency, global environment variable, PATH entry, or system setting was added or changed.

- Phase 3B focused source, filesystem, and import-boundary tests: **38 passed, 2 skipped**. The two skips are the privilege-limited Windows symbolic-link cases. Real Windows root/intermediate/leaf junction, drive-classification, UNC, mutation, integrity, cancellation, and cleanup-retry tests passed.
- Phase 3A focused preview contract/cache-identity regression: **188 passed**.
- Complete contract suite: **178 passed**.
- Complete unit suite: **346 passed, 3 skipped**. The skips are the established POSIX process-group test and two Windows directory-symlink privilege cases.
- Phase 3B filesystem integration module: **20 passed, 2 skipped**. The skips are the two privilege-limited Windows symbolic-link cases.
- Complete backend suite with real WU2/WU3 media integrations: **569 passed, 5 skipped** in 42.59 seconds. All media integrations executed against the approved Gyan 9.0.2 binaries; the five skips are the two Phase 3B Windows symbolic-link cases plus the three established unit-suite platform cases.
- Python compilation of `backend/src` and `backend/tests`: passed after the final locality corrections.
- `git diff --check`: passed after the final locality corrections.

The accepted Phase 3A schema, result binding, descriptor fields, and cache-key implementation were not modified. Its focused regression independently reconfirmed the fixed cache-key digest `7c2eadb17a2cfab9ed55570d6e68f72ee848b26d29af8307045df02cd60e84b3`.

### 19.6 Targeted Phase 3B security corrections (2026-10-22)

Independent acceptance review found five defects in the uncommitted Phase 3B implementation. The approved architecture remained unchanged, and the corrections stayed within source acquisition, snapshot ownership, portable registration validation, and their tests.

1. Every low-level snapshot read and write descriptor now includes `getattr(os, "O_BINARY", 0)`. A Windows regression copies bytes containing LF, CRLF, `0x1A`, NUL, and non-ASCII values and compares the physical snapshot byte for byte with its source. A separate valid-PNG integration acquires through Phase 3B, renders through the unchanged Phase 2 `FFmpegStillImageRenderer`, compares the renderer's source SHA-256 with the lease SHA-256, and verifies exact snapshot cleanup. These tests executed against the approved Gyan FFmpeg/FFprobe 9.0.2 binaries.
2. Linux acquisition now applies fail-closed `fstatfs` classification to the opened root descriptor, every opened intermediate-directory descriptor, and the opened regular-file descriptor. The existing local-filesystem allowlist remains unchanged; NFS, SMB/CIFS, FUSE, and unknown magic values remain rejected. Deterministic descriptor tests cover a local root followed by a remote intermediate, a remote or unknown leaf, classification failure, and an all-local traversal, including closure of every descriptor on rejection. Those tests also exposed and corrected a late-bound closure that would have made the returned POSIX reader and closer reference the root descriptor instead of the leaf descriptor.
3. Snapshot protection and cleanup are now bound to the file identity captured from the exclusive creation descriptor. The adapter verifies that identity before and after changing attributes and again before exact-path deletion. A missing already-removed snapshot remains retryable and idempotent, but a substituted symlink, junction/reparse point, or unrelated hard link is not modified or deleted and produces `PREVIEW_INTERNAL_ERROR`. Windows hard-link and real-junction substitution tests verify unrelated bytes and attributes remain unchanged; symlink behavior is covered by a privilege-conditional test for Windows and will run normally on Linux.
4. The resolver retains the configured snapshot-root identity and final path. It re-runs platform locality, non-reparse, and directory inspection immediately before and after private request-directory creation, and rejects identity or canonical-root changes as `PREVIEW_INTERNAL_ERROR`. Filesystem inspection failures (`OSError`) and fail-closed classification failures (`RuntimeError` or `ValueError`) are translated at this snapshot-storage boundary to the same path-safe internal error, rather than being misclassified as a registered-source failure. Tests cover ordinary-directory replacement, disappearance, simulated locality failure, pre- and post-creation `OSError`, post-creation recheck failure, Windows junction replacement, privilege-conditional symlink replacement, and a stable root. The `OSError` regressions also verify that no private path is exposed, no lease is accepted, request-owned state is cleaned up, and an unrelated marker remains unchanged.
5. Registered relative source components now reject colons before filesystem acquisition. This prevents Windows alternate-data-stream paths such as `file:cover.png`, `file.png:stream`, and `file::$DATA.png` while retaining the existing rejection of absolute, drive-qualified, UNC, backslash, empty, dot, dot-dot, NUL, and unsupported-suffix forms. Valid nested portable POSIX spelling remains accepted. Linux locality regressions now explicitly include the FUSE filesystem magic `0x65735546` in both path and descriptor rejection coverage.

Final Windows validation on the corrected uncommitted state produced:

- Phase 3B focused source, filesystem, and import-boundary tests: **58 passed, 4 skipped**.
- Phase 3B filesystem integration module with the approved FFmpeg/FFprobe paths: **29 passed, 4 skipped**.
- Phase 3A focused preview contract/cache-identity regression: **188 passed**; the fixed digest remains `7c2eadb17a2cfab9ed55570d6e68f72ee848b26d29af8307045df02cd60e84b3`.
- Complete contract suite: **178 passed**.
- Complete unit suite: **357 passed, 3 skipped**.
- Complete backend suite with the approved FFmpeg/FFprobe paths: **589 passed, 7 skipped** in 45.33 seconds.
- Python compilation of `backend/src` and `backend/tests`: passed.
- `git diff --check` and separate whitespace checks for every untracked Phase 3B file: passed.

The four Phase 3B Windows skips are the cleanup-substitution, snapshot-root replacement, source-component, and trusted-root symbolic-link tests; this user context lacks symbolic-link privilege. Real Windows junction tests for source traversal, cleanup substitution, and snapshot-root replacement passed. The three unit-suite skips remain the established POSIX process-group case and two WU2 directory-symlink privilege cases.

Phase 3B's live Linux gate subsequently passed on committed baseline `6c6f1190ae8df9c9fb844b9b695726a972f99337`. WU3 Visual Rendering run [#6](https://github.com/ptanzy/video_studio/actions/runs/39776876409) completed successfully on 2026-10-22. Its Ubuntu/Python 3.12 reference job ran the complete backend suite on a native GitHub-hosted Ubuntu filesystem, so the Phase 3B acquisition module exercised real `statfs`/`fstatfs`, root-relative `openat`, `O_NOFOLLOW`, descriptor ownership/closure, source snapshot integrity, symbolic-link rejection, and snapshot-root failure handling. The Ubuntu/Python 3.11 compatibility job did not run the complete suite at that baseline. Windows-only junction, drive-classification, and UNC cases remained platform skips on Ubuntu; remote/FUSE/unknown filesystem magic rejection used deterministic classification doubles because CI does not provide privileged hostile mounts. WU1 Foundation [#18](https://github.com/ptanzy/video_studio/actions/runs/39776876473) and WU2 Media Infrastructure [#14](https://github.com/ptanzy/video_studio/actions/runs/39776876329) also passed for the same commit. Phase 3B is accepted; those privileged-mount exclusions remain documented threat-model coverage limits rather than an open acceptance gate.

## 20. WU3 Phase 3C-1 secure preview-cache storage (2026-10-22)

### 20.1 Approved boundary and implemented API

Phase 3C-1 implements only disposable authoritative-preview storage. It adds a framework-independent `PreviewCacheStore` port with `lookup()`, `begin_write()`, `discard_corrupt()`, `enforce_limits()`, and explicit `close()` ownership. `PreviewCacheStagingLease` owns one private render destination and can publish it once. `PreviewArtifactLease` owns a verified open read handle, exposes immutable artifact metadata plus `read()`/`seek()`, and must be closed before its entry can be evicted. No consumer-facing raw cache pathname is returned. Closing the store while artifact leases remain pinned or staging leases remain active fails rather than silently releasing process ownership. Successful publication and explicit staging closure each release their lifecycle registration exactly once.

The accepted Phase 3A `PreviewCacheIdentity`, descriptor, canonical cache-key algorithm, public schemas, and fixed digest are unchanged. The private manifest version is `preview-cache-entry-v1`; it contains only the preview ID, complete pixel-affecting Phase 3A descriptor, and verified artifact SHA-256, byte size, dimensions, and `image/png` media type. It does not serialize request-specific `ColorResolution` provenance, source paths, cache paths, timestamps, or caller-supplied verification claims. Canonical JSON encoding and an exact field/type/version policy are required during lookup.

Phase 3C-1 does not acquire a Phase 3B source, invoke Phase 2 rendering, coordinate requests, choose WU2 versus preview admission, or construct `PreviewResult`. Trusted treatment/context loading and preview-service orchestration remain Phase 3C-3 responsibilities. Shared non-preemptive WU2-priority admission, same-key single flight, the four-admitted-waiter limit, and the required but not yet product-selected wait timeout remain Phase 3C-2.

### 20.2 Layout, integrity, and atomic publication

The cache root must already exist. The adapter reuses the accepted Phase 3B platform root inspection: Windows rejects UNC/remote/unknown volumes and every reparse root; Linux requires the explicit local-filesystem allowlist and no-follow directory support; other POSIX platforms fail closed. Root device/file identity and canonical final path are retained and revalidated throughout operation. A process-global identity claim plus the existing `portalocker` dependency holds a root-local lock for the store lifetime; lock path and open-handle identity, regular-file type, non-reparse status, and single-link ownership are rechecked. A private exclusive write probe establishes writability without chmod or deleting a file it did not create.

Managed layout is:

```text
<cache-root>/
  .preview-cache.lock
  .preview-cache-staging/entry-<random-128-bit-id>/
    preview.png
    entry.json
  entries/<first-two-cache-key-hex>/<complete-cache-key>/
    preview.png
    entry.json
```

Publication validates the staged file through a no-follow regular-file handle, rejects hard links, streams SHA-256 and PNG parsing with bounded memory, and verifies the PNG signature, chunk names and ordering, chunk boundaries and CRCs, the exact 13-byte first IHDR, optional RGB/RGBA palette placement and size, non-interlaced 8-bit RGB/RGBA policy, zlib completion, scanline sizes/filter bytes, IEND/trailing bytes, animation chunks, and dimensions. The manifest file is flushed and the staging directory is synchronized before publication. The already-closed staged PNG is not explicitly file-flushed, so the guarantee is atomic visibility rather than full power-loss durability. Every reopened entry is reverified; post-crash damage is treated as corruption and uses the exact trusted-identity invalidation path rather than being served.

Windows publication calls `MoveFileExW` with `MOVEFILE_WRITE_THROUGH` and without `MOVEFILE_REPLACE_EXISTING`. Linux calls `renameat2(..., RENAME_NOREPLACE)`. Both move the complete staging directory atomically within one cache root and never overwrite an entry. `EEXIST`/the equivalent Windows collision result is accepted only after a complete verified lookup of the existing identity; corrupt or mismatched collision material fails closed. A platform without one of these verified primitives is unsupported rather than receiving an `os.rename()` fallback. Failure before the move leaves only request-owned staging for exact cleanup; failure after the move leaves a complete verifiable entry and reports path-safe `PREVIEW_INTERNAL_ERROR`.

### 20.3 Corruption recovery, cleanup, and eviction

Lookup verifies root and lock identity, the exact two-file directory shape, containment, non-reparse regular files, single-link ownership, canonical strict manifest, descriptor/cache-key equality, artifact size/SHA-256, and streamed PNG encoding/dimensions before returning a pinned handle. Failures map to `PREVIEW_CACHE_CORRUPT` without filesystem or operating-system details. A safely recognized persisted entry whose content is corrupt does not prevent store construction: it remains unserved, non-evictable, entry-count-consuming, and byte-capacity-consuming until a trusted identity selects it. Unsafe directory ownership or unaccountable material still fails closed. `discard_corrupt(identity)` refuses to remove a valid entry or a pinned entry and removes only the exact invalid key selected by a trusted identity. This is storage support for the approved single safe invalidation/regeneration attempt; the one-attempt counter and regeneration belong to Phase 3C-3.

Deletion first atomically quarantines an exact entry back beneath the private staging root, then removes only recognized regular files whose identities remain stable. Abandoned staging recovery recognizes only adapter-generated directory names and known output/manifest/Phase 2 partial filenames. Unknown files, directories, symlinks, reparse targets, and ambiguous shapes are preserved and fail closed; there is no recursive broad deletion and no chmod that could mutate unrelated hard-linked content.

Capacity defaults remain the approved 2 GiB and 2,000 entries, with no TTL. Logical artifact plus manifest bytes and entry count are enforced before a new publication. Safely inspectable regular files in a corrupt entry are included in its logical byte charge, but the entry cannot be evicted without trusted exact invalidation. Construction remains available for recovery even when retained corruption alone exceeds a configured limit; explicit enforcement and new publication continue to fail with `PREVIEW_CAPACITY_EXHAUSTED` until recovery. Verified candidates sort deterministically by entry-directory modification time and then preview ID. Eviction skips pinned entries, never deletes unknown or unverified targets, and returns `PREVIEW_CAPACITY_EXHAUSTED` when limits cannot be satisfied. A collision is resolved before admission-space eviction, so an existing legitimate winner is never evicted merely to publish equivalent staged bytes.

### 20.4 Security scope and limitations

The adapter preserves the Phase 3B cooperative same-user threat model. Root/lock identity revalidation, local-filesystem classification, handle-based no-follow file reads, Win32 reparse inspection, hard-link rejection, exact-shape cleanup, and atomic no-replace moves close ordinary traversal, substitution, partial-publication, and read/eviction races. Artifact leases prevent adapter-driven eviction while a consumer streams an already-open file; staging leases retain root ownership while a writer remains active. On POSIX, an external same-user unlink would not change bytes visible through an already-open artifact descriptor.

This is not a defense against administrators, kernel compromise, hostile mount namespaces, denial of service by a same-user process continuously racing managed paths, or privileged filesystem remounts. Atomic publication does not claim full power-loss durability. The logical byte limit does not include filesystem allocation metadata or active request-owned staging; Phase 3C-2/3C-3 must bound admitted active work and always close staging leases. Windows cannot create symbolic links in this local user context, so its symbolic-link test remains an explicit privilege skip; real Windows junction and hard-link cases execute. A live cache-root replacement test is POSIX-only; Windows retains deterministic identity fault injection because an open locked root cannot be replaced safely in this test context. Native Linux publication, cache-root locality, symlink handling, live root replacement, and `renameat2` require the updated WU3 workflow to run after these uncommitted changes are eventually pushed.

### 20.5 Validation evidence

Validation used Windows 11, CPython 3.12.3, the existing repository `.venv`, existing dependencies only, and the explicit approved Gyan FFmpeg/FFprobe 9.0.2 paths for the complete backend run.

- Targeted Phase 3C-1 security-repair regressions: **13 passed, 1 skipped**. The skip is the live POSIX cache-root replacement case on Windows.
- Phase 3C-1 storage unit, import-boundary, and real-filesystem integration tests: **49 passed, 2 skipped**. The skips are Windows symbolic-link creation without the required privilege and the POSIX-only live root-replacement case; Windows junction and hard-link cases passed.
- Phase 3A cache-identity unit regression: **97 passed**, including fixed digest `7c2eadb17a2cfab9ed55570d6e68f72ee848b26d29af8307045df02cd60e84b3`.
- Complete contract suite: **178 passed**.
- Complete unit suite: **374 passed, 3 skipped**.
- Complete backend suite with real WU2/WU3 FFmpeg integrations: **636 passed, 9 skipped**. The skips are four accepted Phase 3B Windows symbolic-link cases, one Phase 3C-1 Windows symbolic-link case, one Phase 3C-1 POSIX live root-replacement case, one POSIX process-group case, and two established WU2 Windows directory-symlink cases.
- Python compilation of `backend/src` and `backend/tests`: passed.
- `git diff --check` and whitespace inspection of tracked and untracked Phase 3C-1 files: passed.

The dedicated WU3 workflow now runs the Phase 3C-1 storage unit and filesystem modules explicitly on Ubuntu/Python 3.11, Ubuntu/Python 3.12, and Windows/Python 3.12 in addition to the complete 3.12 regressions. That workflow change is locally validated but cannot execute against this uncommitted working tree. Live Ubuntu verification of `renameat2(RENAME_NOREPLACE)`, native symlink cases, local-filesystem classification, and Linux cleanup/eviction behavior therefore remains the Phase 3C-1 acceptance gate after an approved commit and push.

## 21. WU3 Phase 3C-2 render coordination (2026-10-22)

### 21.1 Implemented boundary and ownership

Phase 3C-2 adds a framework-independent, injectable process-local render-admission port and application implementation. A single `ProcessLocalRenderAdmission` instance owns one non-preemptive render slot. WU2 and preview waiters are FIFO within their own classes; an already admitted operation is never preempted, and waiting WU2 work is always selected before waiting preview work. Lease closure is idempotent, and cancellation checks and operation callbacks occur outside the admission lock. Existing WU2 repository worker locking remains the cross-process authority.

`RenderWorker` now requires the admission dependency. It claims the attempt and registers its cancellation event before waiting for admission, then holds admission across the complete existing probe, encode, validate, and promote operation. Cancellation while waiting is acknowledged through the established durable WU2 transition without starting the encoder. Phase 2 media behavior, public WU2 errors, publication reconciliation, and the repository lock are unchanged. The future application composition root must inject the same admission instance into WU2 and the Phase 3C-3 preview service; constructing separate instances would intentionally create separate process-local scheduling domains.

`PreviewSingleFlightCoordinator` accepts only a trusted `PreviewCacheIdentity` and coalesces on its `preview_id`. The first caller's operation becomes flight-owned background work; joining callers' unused operations are closed exactly once. A successful flight communicates completion only—it does not return a cache path, artifact lease, or shared result. Phase 3C-3 remains responsible for source verification, authoritative rendering and publication, and a fresh verified per-caller cache lookup after coordination.

### 21.2 Capacity, cancellation, deadlines, and shutdown

The coordinator enforces the approved global limit of four waiting preview callers. A queued first caller and every waiting same-key follower count separately. Once a flight becomes active, its oldest attached caller is the sponsor and is excluded from waiting capacity; active followers remain counted. Sponsor detachment promotes the oldest follower atomically. A fifth waiting caller receives path-safe `PREVIEW_CAPACITY_EXHAUSTED`; WU2 work does not consume preview capacity. Verified cache-hit bypass is intentionally absent here and belongs to Phase 3C-3.

The injected preview wait timeout is required, positive, and finite; there is no production default. A flight receives one fixed deadline when first registered, and a late joiner cannot extend it. The monotonic instant immediately after `operation.run()` returns is the authoritative completion instant: a successful return strictly before the deadline is eligible for success, while a return at or after the deadline atomically becomes `PREVIEW_TIMEOUT` for every still-attached caller. A caller cancellation or timeout is established when its detach transition wins the coordinator condition; an already-published terminal flight outcome wins over a cancellation signal that has not yet established that transition. Cancellation or timeout detaches only that caller while another interested caller remains. Last-caller detachment cooperatively cancels queued or active flight work. An abandoned queued operation cannot run, while active abandoned work remains owned until it terminates and is closed. The Phase 2 renderer's independent execution timeout is unchanged.

Shutdown is explicit and requires a positive finite bound. It stops registration, wakes callers with `PREVIEW_CANCELLED`, signals every queued or active flight, and joins the non-daemon coordinator worker. An adopted queued operation claimed for last-caller cleanup is registered as coordinator-owned before `close()` runs outside the lock; shutdown waits for that registration to be released exactly once. Worker and detached-cleanup completion instants are compared with the fixed shutdown deadline, so delayed wakeup cannot turn an after-deadline cleanup into success. If active work or cleanup remains live at the bound, shutdown reports path-safe `PREVIEW_TIMEOUT` while ownership remains tracked; a later close can reap the completed work. Cleanup failure reports `PREVIEW_INTERNAL_ERROR` without exposing the underlying path. No live background render is silently abandoned, and admission is not released while active rendering remains alive.

Strict WU2-first selection can starve previews under an unlimited WU2 stream by approved design. The finite fixed preview deadline converts that condition to `PREVIEW_TIMEOUT`; Phase 3C-2 adds no WU2 timeout, preemption, or fairness-burst policy.

### 21.3 Validation evidence and remaining gate

Validation used Windows 11, CPython 3.12.3, the existing repository `.venv`, and the approved Gyan FFmpeg/FFprobe 9.0.2 paths. No dependency, global environment variable, PATH entry, or system setting was added or changed.

- Phase 3C-2 coordination, WU2 worker, and import-boundary tests: **54 passed**.
- Expanded coordination, Phase 3A identity, Phase 3B/3C-1 filesystem-security, cache-storage, and import-boundary run: **226 passed, 6 skipped**. The skips are five Windows symbolic-link privilege/platform cases and the POSIX-only live cache-root replacement case.
- WU2 real-media integration module: **5 passed**. An earlier isolated attempt had one transient Windows job-object ownership skip during media-tool discovery; the clean rerun and complete backend run both executed all five tests.
- Complete backend suite with the approved FFmpeg/FFprobe paths: **669 passed, 9 skipped** in 56.52 seconds. The skips are the four accepted Phase 3B Windows symbolic-link cases, one Phase 3C-1 Windows symbolic-link case, the Phase 3C-1 POSIX live root-replacement case, the established POSIX process-group case, and two established WU2 Windows directory-symlink cases.
- Python compilation of `backend/src` and `backend/tests`: passed before the final documentation update and is rerun as a final diff gate.
- The Phase 3A fixed preview digest remains `7c2eadb17a2cfab9ed55570d6e68f72ee848b26d29af8307045df02cd60e84b3`.

The WU3 workflow now executes the focused coordination module explicitly on Ubuntu/Python 3.11, Ubuntu/Python 3.12, and Windows/Python 3.12, in addition to the complete 3.12 backend regressions. Because this working tree is uncommitted, live Ubuntu verification remains outstanding. That gate must confirm thread/admission behavior and the focused module on native Linux; no Linux-specific process primitive was added by Phase 3C-2.

Phase 3C-2 does not perform cache lookup, source acquisition, rendering, publication, authoritative result construction, HTTP mapping, or UI work. Those service-composition responsibilities remain Phase 3C-3 or later.

### 21.4 Targeted concurrency repairs

Independent review identified two scheduler-dependent gaps in the initial Phase 3C-2 implementation. First, a waiting caller could observe success when an operation returned after the fixed flight deadline because only caller wakeup checked time. Worker publication now records the operation-return instant and resolves the deadline under the coordinator condition before completing attached callers. Deterministic tests cover before-deadline success, at/after-deadline timeout, multiple callers receiving one late terminal outcome, cancellation/completion ordering, and key/capacity recovery. The original 50 ms deadline/approximately 150 ms late-return adversarial probe now returns `PREVIEW_TIMEOUT`.

Second, last-caller cancellation of a still-queued flight previously ran adopted-operation cleanup in the caller thread after removing the flight from the coalescing map, allowing shutdown to join its worker and return while that cleanup remained blocked. The coordinator now retains a separate immutable ownership registration from cleanup claim through completion. Shutdown waits for every such registration within its bound, records monotonic worker and cleanup completion instants, returns `PREVIEW_TIMEOUT` without forgetting late work, and permits a later close after cleanup finishes. Tests cover blocked cleanup timeout, cleanup completion before shutdown's deadline, eventual release after timeout, cancellation/shutdown overlap, exactly-once close, and preservation of normal queued-cancellation behavior.

## 22. WU3 Phase 3C-3 authoritative preview service (2026-10-22)

### 22.1 Implemented application boundary

`AuthoritativePreviewService.execute(request, resolution, cancel_event=None)` is the internal application entry point. It accepts only an already validated `PreviewRequest` and a server-established `ColorResolution`; it never accepts a source path, source digest, tool fingerprint, cache identity, output path, or artifact-verification claim. Direct custom and preset resolutions are recomputed from the request and must match exactly. Automatic resolutions are validated as complete Phase 1 outputs and must match the requested mode and effective treated intensity, but their server-owned album/track context is intentionally not present in the public preview request. Phase 3D must construct automatic resolution from server-owned context and must not deserialize a client's claimed resolution.

The service has four explicit injected dependencies: `ArtworkSourceResolver`, `PreviewCacheStore`, `PreviewFlightCoordinator`, and `PreviewRenderBackend`. It imports no infrastructure adapter and creates no global singleton, cache, registry, render queue, or admission coordinator. Application composition must give WU2's `RenderWorker` and the preview coordinator the same `ProcessLocalRenderAdmission` instance. Phase 3C-3 adds no FastAPI route, HTTP streaming, UI behavior, MP4 export, persistence schema, or dependency.

`PreparedPreview` pairs the trusted `PreviewResult` with one independently pinned `PreviewArtifactLease`. It is internal, serializes no path, supports context-manager use, and closes its lease idempotently. The service and flight operation do not own the shared resolver, cache, coordinator, or backend lifetimes. The later HTTP adapter owns closing every returned delivery after reading or streaming it.

### 22.2 Identity, cache, and source pipeline

Every caller first acquires and verifies a Phase 3B immutable snapshot, revalidates the registered source, establishes the exact rendering tool identity, and constructs the accepted Phase 3A cache identity from the snapshot content digest, trusted color resolution, and FFmpeg/FFprobe fingerprints. A verified initial cache hit remains pinned while the snapshot, registered source, and tool identity are checked again; it bypasses preview admission and returns `cache_status="hit"`.

An initial miss closes its preflight source lease before entering coordination. The per-caller flight operation is deliberately lightweight until adopted: unused operations held by same-key followers own no snapshot, staging directory, or render process. The adopted operation rechecks tool identity and cache after admission, reacquires the source by opaque IDs, requires its content digest to match the coordinated identity, verifies and revalidates the source, creates unique Phase 3C-1 staging, and renders through the accepted Phase 2 implementation. Before publication it verifies the exact staging destination, source digest, complete treatment, dimensions, renderer/transform versions, PNG output, RGBA pixel format, snapshot integrity, registered source identity, tool identity, and cancellation/deadline state.

The operation closes the cache publication lease rather than distributing it. Pixel identity can be shared across different opaque artwork targets when their source bytes, effective treatment, render policy, and toolchain are identical, but source validity is always caller-specific. After successful coordination, every caller independently reacquires its own `(album_id, artwork_asset_id)`, verifies the new snapshot, requires its digest to match the coordinated identity, revalidates the registered source, and reconfirms the expected toolchain before performing a fresh verified lookup. While its own artifact pin is held, the caller verifies and revalidates its source and toolchain again before accepting the result. A changed digest returns `SOURCE_CHANGED`; a missing or revoked target preserves the approved source-unavailable error. The adopted operation's source checks and its admitted cache recheck can never substitute for this caller-specific final boundary.

Each successful caller therefore owns its own post-coordination source lease and independent artifact pin. It constructs its result from its own `PreviewCacheIdentity`, so pixel-equivalent custom, preset, and automatic requests can share one render while retaining different request-specific Phase 1 provenance. Every caller that entered coordination reports `cache_status="miss"`, including joined callers and a flight whose admitted cache recheck found a concurrently published entry. If coordination succeeds but final lookup finds no artifact, the service fails closed with path-safe `PREVIEW_INTERNAL_ERROR`; it does not start an unbounded rerender.

The service permits at most one exact corrupt-entry invalidation and one corruption-triggered regeneration per execution. Corruption encountered again returns `PREVIEW_CACHE_CORRUPT`. Valid, pinned, unrelated, or unaccountable cache material retains the Phase 3C-1 fail-closed rules.

### 22.3 Verified FFmpeg preview backend

`VerifiedFFmpegPreviewBackend.identify(cancel_event=None)` returns the existing immutable `PreviewToolchainIdentity`. `render(source_path=..., output_path=..., resolution=..., expected_toolchain=..., cancel_event=None)` returns the existing `StillRenderResult`. The port is application-owned; the concrete adapter pins canonical absolute FFmpeg and FFprobe paths for its lifetime, requires regular non-empty files, computes complete SHA-256 fingerprints, obtains version/build text, and verifies the Phase 2 filters and PNG encoder plus PNG, MJPEG, WebP, and animated-WebP decoders. Capability results are reused only while new full-file hashes match the already verified identity.

Rendering constructs the existing `FFmpegStillImageRenderer` with the trusted cache staging directory as its fixed output root and the cache-owned PNG filename as its relative output. This preserves the Phase 2 graph, geometry, orientation, timeout, source hashing, output verification, and no-replace behavior rather than introducing another transform. The renderer receives a pinned media-tool resolver, so it cannot silently re-resolve different environment paths. Exact binaries are hashed before use and again after rendering; the operation independently confirms the current identity again before publication. Replacement or mismatch fails with `PREVIEW_INTERNAL_ERROR` and publishes no artifact.

This is the approved cooperative local-writer policy, not protection from administrators, kernel compromise, or a privileged process capable of replace-and-restore between observations. Environment changes after backend construction do not retarget a live backend; application restart establishes a new pinned selection and cache identity.

### 22.4 Cancellation, deadlines, publication, and errors

The Phase 3C-2 fixed monotonic flight deadline remains authoritative. Its internal event-compatible signal now becomes canceled either when explicitly set or when the fixed deadline is reached. Existing source hashing, tool hashing, process execution, source verification, cache verification, and service publication checks therefore observe expiry without requiring a caller thread to win a scheduling race first. `wait(timeout=None)` reevaluates explicit cancellation and the fixed deadline after every underlying wakeup; a premature or spurious wakeup cannot return `False`. A finite caller-supplied wait timeout is tracked by its own monotonic deadline and returns `False` only when that separate budget expires first. Zero and negative timeouts retain immediate-poll behavior, while explicit cancellation or flight expiry already established at the poll returns `True`. Sponsor cancellation still detaches only that caller while followers remain; last-caller cancellation sets the same shared signal. WU2 priority, the four-waiting-caller limit, non-preemptive admission, exactly-once operation closure, detached cleanup ownership, and bounded shutdown are unchanged.

The service checks the signal immediately before calling cache publication. Cache publication checks it on entry, after staging synchronization/test hooks, and again after capacity preparation immediately before the atomic no-replace directory operation. Deterministic barriers prove that cancellation during publication validation leaves no entry, and a renderer held past the flight deadline cannot publish. This is a cooperative deadline linearized at the final pre-publication check. It does not claim that monotonic time cannot cross the deadline in the unavoidable instruction/syscall interval between that check and the filesystem's atomic rename operation. Atomic cache visibility and no-replace collision safety remain the Phase 3C-1 guarantees; neither is a claim of full power-loss durability.

Typed mapping preserves approved source errors and `SOURCE_CHANGED`; maps caller/flight cancellation to `PREVIEW_CANCELLED`, deadlines and media timeouts to `PREVIEW_TIMEOUT`, preview/cache capacity to `PREVIEW_CAPACITY_EXHAUSTED`, unsupported or corrupt source media to `PREVIEW_IMAGE_UNSUPPORTED`, FFmpeg/output failure to `PREVIEW_RENDER_FAILED`, repeated cache corruption to `PREVIEW_CACHE_CORRUPT`, and tool mismatch, snapshot tampering, storage failures, cleanup failures, or impossible trusted invariants to `PREVIEW_INTERNAL_ERROR`. Only the initial caller request and trusted-resolution compatibility boundary maps `PreviewContractError` to `PREVIEW_INVALID_REQUEST`; a later malformed source digest, cache metadata value, or trusted result invariant is an internal failure rather than a client mistake. Public messages contain no source, cache, staging, or executable paths and no raw operating-system or subprocess detail. Correlation IDs and HTTP status mapping remain Phase 3D responsibilities.

### 22.5 Validation evidence and remaining gate

The initial implementation validation used Windows 11, CPython 3.12.3 from the existing repository `.venv`, existing dependencies only, and the approved Gyan FFmpeg/FFprobe 9.0.2 binaries configured only for each test process. The targeted acceptance repair added deterministic different-target follower mutation/removal, admitted-cache-recheck, trusted-invariant classification, and independent FFmpeg/FFprobe mid-render replacement regressions. Both executable replacement cases fail before publication with path-safe `PREVIEW_INTERNAL_ERROR`, close staging/source ownership, and leave no cache entry. No approved system binary is modified by those tests.

A final independent review reproduced an early-return race in the deadline-aware signal: one bounded underlying event wait could return fractionally before the monotonic deadline, causing an event-style operation to observe `False` and be classified as an internal failure. The corrected wait uses separate monotonic flight and caller deadlines in a reevaluation loop. Controlled tests force the first underlying wait to return early and cover explicit cancellation, caller timeout, deadline-only cancellation, `None`, zero and negative timeouts, and multiple waiters without relying on scheduling luck. The original active-flight deadline regression completed 100 consecutive iterations with zero failures; controlled explicit/caller-timeout early-wakeup cases completed 200 iterations with zero failures, and controlled deadline cases completed another 200 iterations with zero failures.

The repair also adds real-media comparisons of decoded service pixels against direct Phase 2 output for preset treatment with alpha, custom HEX, zero intensity, and downscaling. Sandboxed tests cannot stat the approved `%LOCALAPPDATA%` binaries. During the independent re-review, all four new decoded-pixel equivalence cases passed individually outside the sandbox against the approved Gyan FFmpeg/FFprobe 9.0.2 binaries. A whole-module elevated run did not return a final pytest summary under the host's Windows process/Job Object constraints, so no successful whole-module run is claimed. The existing process-safety behavior was not weakened; native Windows and Linux CI execution remains required.

- Targeted Phase 3C-3 service and adapter regressions: **18 passed** in 0.67 seconds.
- Phase 3C-3 service, coordination, cache-publication, and import-boundary focus after the deadline repair: **107 passed, 2 skipped** in 6.05 seconds. The skips are the Windows directory-symlink privilege case and POSIX-only live cache-root replacement.
- Complete contracts plus the Phase 3A preview-identity module: **275 passed** in 5.79 seconds; this includes the unchanged fixed digest.
- Complete unit suite after the deadline repair: **432 passed, 3 skipped** in 20.84 seconds. The skips are the established POSIX process-group case and two Windows directory-symlink privilege cases.
- Before the final deadline repair, the cross-phase contract, Phase 3A identity, Phase 3B source security, Phase 3C-1 cache, Phase 3C-2 coordination, Phase 3C-3 service, Phase 2 unit-renderer, and WU2 worker/adapter regression without accessible external media tools produced **483 passed, 8 skipped** in 18.41 seconds. The subsequent complete unit and backend runs include the final repair coverage.
- Complete backend suite after the deadline repair in the restricted environment: **670 passed, 44 skipped** in 23.39 seconds. Media-dependent skips are not counted as FFmpeg evidence; the remaining skips are the documented Windows symbolic-link privilege and POSIX-only cases.
- The accepted Phase 3A fixed preview digest remains `7c2eadb17a2cfab9ed55570d6e68f72ee848b26d29af8307045df02cd60e84b3`.
- Python compilation of `backend/src` and `backend/tests`, the five import-boundary tests, `git diff --check`, and explicit trailing-whitespace inspection of all four untracked files passed.

The WU3 workflow includes the complete Phase 3C-3 service unit module in its focused Windows and Ubuntu matrix step, so the new caller-specific and tool-mutation regressions require no selector change. It includes the real service integration module beside the existing Phase 2 real-media module, which includes the new direct decoded-pixel comparisons. It retains the verified pinned Gyan Windows and BtbN Linux FFmpeg 9.0.2-family archives and performs no Ubuntu APT FFmpeg installation. Its expressions, platform guards, hashes, and test selectors were inspected locally; no YAML parser or `actionlint` is installed in the existing environment, so parser-backed workflow validation was unavailable without adding a dependency. This uncommitted implementation has not run in GitHub Actions. Native Windows and Ubuntu equivalence execution plus Ubuntu tool hashing, source/cache filesystem, deadline, and real-media execution remain mandatory after an approved provisional commit and push; no restricted-host result is reported as CI evidence.

## 23. WU3 Phases 3D + 3E backend HTTP integration (2026-10-23)

### 23.1 Approved completion boundary and HTTP contract

WU3 completion is backend-complete. The product's authoritative Original/Split/Treated React comparison remains required, but its implementation is explicitly deferred to WU4 together with album ingestion and review UI. WU3 does not add a frontend, motion preview, video export, persistence API, administration API, authentication layer, or permissive CORS policy.

The sole WU3 HTTP route is `POST /api/v1/previews/still`. It accepts the strict existing `preview-request-v1` representation. Pydantic validation forbids unknown properties and coercion and does not expose fields for paths, hashes, cache identity, resolution provenance, toolchain identity, or verification claims. Successful responses use a generated standards-safe `multipart/related` boundary. The first part is the exact `preview-result-v1` JSON representation with `application/json`; the second is the pinned authoritative artifact with `image/png`. `retrieval_reference` remains opaque provenance and is not a URL. No cache path or secondary download token is exposed.

The provided blocking server entry point requires an explicit port and always binds to `127.0.0.1`. Programmatic application construction does not add a public listener. Public network exposure is outside the local POC security model.

### 23.2 Trusted resolution and composition

`ResolvedPreviewService` is a framework-independent application boundary. Preset and custom requests resolve directly through the accepted Phase 1 resolver. Automatic treatment obtains context only from `ImmutablePreviewContextRegistry`, keyed by the complete `(album_id, artwork_asset_id, track_id, short_id)` target. Supplying either optional identifier requires an exact full-target registration and never falls back to album metadata. With both absent, the exact album/artwork registration is used. An explicitly registered empty context produces the deterministic original-artwork fallback; unrestricted unknown mood text retains the accepted resolver behavior. Invalid trusted registrations fail during startup. HTTP cannot provide context.

`PreviewApplicationRuntime` owns one immutable artwork registry and secure snapshot resolver, secure preview cache, verified FFmpeg backend, context registry, single-flight coordinator, authoritative service, and `ProcessLocalRenderAdmission`. Its WU2 worker factory injects that exact admission instance into every `RenderWorker`, retaining nonpreemptive WU2 priority while cache hits continue to bypass admission. Tool paths and all preview/render/shutdown timeouts are explicit trusted configuration. Startup claims and validates roots, verifies both executable identities and required capabilities, then starts coordination. Partial startup releases acquired cache and coordination ownership.

### 23.3 Streaming, cancellation, shutdown, and errors

Blocking service work and bounded cache reads run outside the ASGI event loop. Every HTTP call owns one cancellation event. A disconnect watcher, ASGI task cancellation, runtime shutdown, the existing single-flight deadline, and FFmpeg's render timeout all propagate through existing cooperative boundaries. Detaching one HTTP caller does not directly cancel another caller sharing the flight; the accepted coordinator cancels shared work only after the last interested caller detaches.

The HTTP ownership object receives `PreparedPreview` explicitly after service success. It serializes bounded reads against closure and releases the pin exactly once on full consumption, early iterator termination, disconnect, iterator failure, response-construction failure, or shutdown. Shutdown stops registration, signals every request, closes coordination within the injected deadline, waits only for live application executions, then closes remaining delivery pins before cache ownership. If service work remains live past the deadline, shutdown returns a typed timeout and deliberately does not close the cache underneath active work.

Expected preview codes map to the approved 422/404/409/408/504/503/500 statuses. Each response is the existing `preview-error-v1` envelope with a new server-generated correlation ID and empty path-safe public details. Unexpected adapter errors are logged privately and become `PREVIEW_INTERNAL_ERROR`; request validation does not echo rejected private values.

### 23.4 Dependencies and cross-platform gate

The backend adds only FastAPI, Pydantic, and Uvicorn as runtime dependencies and HTTPX as a test dependency. The WU3 constraint set pins direct and newly introduced transitive packages. The existing Windows Gyan and Linux BtbN 9.0.2-family archives and checksum/capability gates are unchanged.

The WU3 matrix remains Windows/Python 3.12 and Ubuntu/Python 3.11 plus 3.12. Its focused selector now includes HTTP contract/application/streaming tests and the actual artwork-source and cache filesystem modules. Its media selector includes the complete HTTP-to-source-to-FFmpeg-to-cache pipeline. The 3.12 jobs retain the complete backend regression. Native Ubuntu execution must demonstrate POSIX no-follow acquisition, filesystem locality checks, atomic cache publication, cancellation/deadline cleanup, and real FFmpeg output. Windows directory-symlink tests may skip only where the runner lacks the required privilege; those skips must remain visible.

### 23.5 Local implementation evidence and remaining acceptance gate

Focused strict request/context and HTTP ownership tests, deterministic direct-ASGI disconnect coverage, and a real loopback Uvicorn smoke test are part of the new suite. Real-media coverage exercises an initial miss and verified hit; PNG, JPEG, and WebP sources; EXIF orientation; alpha; preset, custom, automatic, and zero-intensity treatments; downscaling and no-upscaling; source immutability; and decoded-pixel identity with direct Phase 2 output. Existing Phase 3A–3C suites remain authoritative for cache identity, the four-caller bound, same-key coalescing, distinct-key separation, fixed deadlines, WU2 priority, source replacement/revocation, cache tampering, and filesystem race defenses.

Windows 11 / CPython 3.12.3 local validation used the approved Gyan FFmpeg/FFprobe 9.0.2 binaries through process-local `WRLD_FFMPEG_PATH` and `WRLD_FFPROBE_PATH` values. The new HTTP/context focus produced **59 passed**; the complete contract suite produced **202 passed**; the complete unit suite produced **441 passed, 3 skipped**; the non-media backend suite produced **729 passed, 9 skipped, 36 deselected**; the new real HTTP media pipeline produced **1 passed**; and the complete FFmpeg-enabled backend suite produced **765 passed, 9 skipped**. The fixed Phase 3A digest remains `7c2eadb17a2cfab9ed55570d6e68f72ee848b26d29af8307045df02cd60e84b3`. Compilation, dependency compatibility, OpenAPI assertions, and diff/whitespace checks passed. The local skips are the established POSIX-only process/root-replacement cases and Windows symlink/reparse tests unavailable without link privilege.

The installed test versions were FastAPI 0.161.1, Pydantic 2.14.1, Uvicorn 0.54.0, HTTPX 0.28.1, and Starlette 1.9.0. FastAPI's compatibility shim emits a deprecation warning because Starlette 1.9 recommends `httpx2`; HTTPX remains the explicitly approved WU3 test dependency and all TestClient and live-Uvicorn behavior passes. The existing JSON Schema contract test infrastructure also emits its pre-existing `RefResolver` deprecation warning. Neither warning changes runtime behavior.

GitHub Actions has not validated these uncommitted Phase 3D/3E changes. Native Windows and Ubuntu CI remain the final acceptance gate, including POSIX no-follow traversal, live cache-root replacement, filesystem locality, atomic publication, and real-media equivalence. Privileged mount/reparse scenarios unavailable to ordinary hosted runners remain explicit limitations rather than silently skipped claims.
