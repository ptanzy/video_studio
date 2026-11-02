# 40 — WU3B Visual Refinement Phase A

**Status:** Historical Phase A proposal with subsequent approvals. Phase B motion-v2 and Phase C real-artwork review are complete implementation/validation candidates. Consolidated Phase D is the separate player generation in Section 11. Motion-v1 and static behavior remain unchanged; the reviewed label-free Phase D pixels received human acceptance on October 27, 2026.

## 1. Authority, current state, and boundary

This document supplements Docs 31, 38, and 39. It does not replace the accepted WU3A static profile or the implemented WU3B motion-v1 contracts. The current implementation uses:

- `video-effects-v1.schema.json` with a complete strict `pan_zoom`, `audio_bars`, and `track_progress` object;
- `wrld-video-album/2.0`, `video-export-request/2.0`, and `video-export-result/2.0`;
- `motion-preview-request/1.0`;
- `youtube-1080p30-motion-v1` and renderer identity `wu3b-motion-export-1`; and
- SHA-256 over canonical, fully resolved effects for the profile-qualified output namespace.

WU3B Phases 1–4 are present in the working tree. They provide versioned contracts, camera motion, RMS bars, track progress, and private lease-owned rendered previews through the shared production graph. The bounded real *Echoes of Asia* preview is technical evidence, not a substitute for pending human visual acceptance or WU3A's separate full-album acceptance.

The original Phase A pass changed documentation only. Later user approvals authorized Phase B motion-v2, Phase C real-artwork validation/architecture review, and the additive Phase D player generation. None authorizes React, publishing metadata, source-asset mutation, or automatic manifest migration.

## 2. Compatibility and versioning decision

Appending fields with defaults to `video-effects-v1` would change the meaning and digest of an already resolved request. Rebinding the existing v2 manifest/request/preview schemas to another effects shape would also silently widen checked-in contracts. The refinement therefore uses a fully additive generation.

The proposed identifiers for approval are:

| Contract | Existing, preserved | Proposed refinement |
|---|---|---|
| Effects schema | `video-effects-v1.schema.json` (selected by its enclosing contract; no in-object version field) | `video-effects-v2.schema.json` (selected by the new enclosing contracts; no in-object version field) |
| Album manifest | `wrld-video-album/2.0` | `wrld-video-album/3.0` |
| Export request | `video-export-request/2.0` | `video-export-request/3.0` |
| Export result | `video-export-result/2.0` | `video-export-result/3.0` |
| Motion preview | `motion-preview-request/1.0` | `motion-preview-request/2.0` |
| Render profile | `youtube-1080p30-motion-v1` | `youtube-1080p30-motion-v2` |
| Renderer identity | `wu3b-motion-export-1` | `wu3b-motion-export-2` |

The new profile retains 1920×1080 CFR 30 fps, H.264 High, `yuv420p`, CRF 18, `medium`, BT.709, AAC-LC 48 kHz stereo 192 kbit/s, and `+faststart`. Its distinct identifier records changed visual semantics and isolates artifacts under:

```text
output/profiles/youtube-1080p30-motion-v2/<effects-v2-sha256>/...
```

No existing schema is edited. Motion-v1 manifests, requests, fingerprints, preview identities, output paths, verified reuse, and rendered output remain literal motion-v1 behavior. Static `youtube-1080p30-v1` remains unchanged.

Migration is explicit, never automatic. An approved future migration command or UI action may create a new manifest/request generation by copying unchanged camera and timing settings, mapping the old progress `opacity` to new `fill_opacity`, and materializing every new field. It must show that the profile, fingerprint, destination, and pixels will change. It must not rewrite the source manifest in place without a separate approved operation.

## 3. Proposed effects-v2 contract

All objects remain strict with `additionalProperties: false`. Every request contains every field. JSON numbers must be finite. Disabled effect parameters remain validated and fingerprinted, consistent with motion-v1. All fields below affect renderer configuration and belong in canonical identity; no element-selection or editor-only state is included.

### 3.1 Camera

`pan_zoom` is byte-for-byte the motion-v1 shape and retains its current defaults, bounds, paths, smoothstep behavior, absolute timeline, and ending return. Phase A proposes no camera semantic change.

### 3.2 Audio bars

```json
{
  "enabled": false,
  "variation_mode": "organic_rms",
  "bar_count": 24,
  "color": "#FFFFFF",
  "opacity": 0.65,
  "placement": "bottom_center",
  "zone_width_px": 640,
  "zone_height_px": 180,
  "gap_px": 4,
  "horizontal_offset_px": 0,
  "bottom_margin_px": 64,
  "rms_window_samples": 1920,
  "attack_ms": 60.0,
  "release_ms": 240.0,
  "glow": {
    "enabled": true,
    "intensity": 0.35
  }
}
```

| Field | Proposed validation |
|---|---|
| `variation_mode` | `organic_rms` or `symmetrical` |
| `bar_count` | integer 8–64 |
| `color` | normalized six-digit `#RRGGBB` |
| `opacity` | 0.10–1.00 |
| `placement` | `bottom_left`, `bottom_center`, or `bottom_right` |
| `zone_width_px` | integer 160–1792 |
| `zone_height_px` | integer 32–952 |
| `gap_px` | integer 0–32, additionally constrained by bar count and zone width |
| `horizontal_offset_px` | integer -1792–1792, additionally constrained by the safe rectangle |
| `bottom_margin_px` | integer 64–1016, additionally constrained by zone height |
| RMS window/attack/release | unchanged motion-v1 bounds |
| `glow.enabled` | boolean |
| `glow.intensity` | 0.00–1.00; zero produces no glow contribution |

The reference canvas is 1920×1080 and the safe rectangle is `[64,1856) × [64,1016)`. Placement first selects the left, centered, or right base x coordinate inside that rectangle. `horizontal_offset_px` is then added. The zone top is `1080 - bottom_margin_px - zone_height_px`. Semantic validation rejects any zone outside the safe rectangle; it never clamps or silently moves it.

For `N` bars, `usable = zone_width_px - gap_px × (N - 1)` must be at least `N`. Bar width is `floor(usable / N)`. The unused remainder is split left/right with the extra pixel on the right. This makes size and spacing deterministic for every accepted configuration.

### 3.3 Organic RMS variation

The audio driver remains the real stereo PCM RMS envelope defined by Doc 39: track-clipped windows, dBFS mapping, attack/release smoothing, and a reset to zero at each normalized-sample track boundary. It is amplitude visualization, not a frequency spectrum.

For output frame `n`, let `t = presentation_sample / 48000`, where presentation sample uses the absolute selected-target timeline. Let `A(n)` be the existing smoothed RMS amplitude in `[0,1]`. For zero-based bar `i`:

```text
phi_i = 2π × fract((i + 0.5) × 0.61803398875)
psi_i = 2π × fract((i + 0.5) × 0.41421356237)

m_i(t) = 0.70
         + 0.18 × (0.5 + 0.5 × sin(2π × 0.11 × t + phi_i))
         + 0.12 × (0.5 + 0.5 × sin(2π × 0.037 × t + psi_i))

h_i(n) = 2 + round_half_up((zone_height_px - 2) × clamp(A(n) × m_i(t), 0, 1))
```

For these nonnegative values, `round_half_up(x) = floor(x + 0.5)`. `m_i(t)` is bounded to `[0.70,1.00]`. It creates slow, deterministic spatial variation without claiming separate frequency bands. No random number, seed, host clock, or encoder timing participates. The two low temporal frequencies, the existing RMS smoothing, integer-pixel quantization, and command updates only when geometry changes prevent single-frame flicker. The modifier timeline remains continuous across album tracks while only the real RMS smoothing state resets at a track boundary. A rendered excerpt uses the same absolute target sample so it matches the corresponding production frames.

`symmetrical` retains the existing multiplier exactly:

```text
0.25 + 0.75 × sin²(π × (i + 0.5) / N)
```

Motion-v1 always retains its current symmetrical implementation regardless of the motion-v2 default.

### 3.4 Glow

The glow color is derived from the normalized bar color, not independently authored. Convert each sRGB channel to linear light, then calculate:

```text
glow_linear = 0.75 × bar_linear + 0.25
```

Convert back to sRGB using the standard transfer function and round each channel to the nearest integer. The profile uses a fixed 12-pixel Gaussian sigma and 36-pixel transparent padding. Glow alpha is:

```text
bar_opacity × glow_intensity × 0.60
```

clamped to `[0,1]`. Disabled glow or zero intensity omits the glow branch.

The renderer should draw bars into a small transparent attempt-owned overlay, split that overlay, apply FFmpeg `gblur` only to the padded glow branch, composite glow behind the crisp bar branch, and finally overlay the result on the already transformed artwork. It must not blur or duplicate the 1920×1080 background. Phase B must capability-test `gblur` and the required alpha/overlay filters on the supported Windows build. A missing required filter fails preflight as `MEDIA_TOOL_INVALID`; motion-v2 does not silently select a host-dependent fallback with different pixels.

### 3.5 Track progress

```json
{
  "enabled": false,
  "style": "line",
  "placement": "bottom",
  "color": "#FFFFFF",
  "fill_opacity": 0.80,
  "rail_color": null,
  "rail_contrast_strength": 0.60,
  "rail_opacity": 0.35,
  "thickness_px": 6,
  "segment_count": 20
}
```

`style`, `placement`, `thickness_px`, and `segment_count` retain motion-v1 values and bounds. `color` and a non-null `rail_color` use normalized six-digit HEX. `fill_opacity` and `rail_opacity` are independently validated from 0.10–1.00. `rail_contrast_strength` is 0.00–1.00. The progress area remains the existing safe width from x=64 through x=1856. Top or bottom placement retains the established 64-pixel safe edge. The rail occupies the full area for the entire track; fill overlays it using the unchanged normalized-sample progress calculation. Segmented fill draws over the same continuous rail, so unfilled cells and gaps expose the rail.

If `rail_color` is non-null, its normalized value is used. Otherwise derive the rail from `color` as follows:

1. Decode each 8-bit sRGB channel `c` to `[0,1]` and linearize with `c/12.92` for `c <= 0.04045`, otherwise `((c + 0.055)/1.055)^2.4`.
2. Compute relative luminance `Y = 0.2126R + 0.7152G + 0.0722B`.
3. If `Y >= 0.50`, choose linear black as the contrast target; otherwise choose linear white.
4. For strength `s`, calculate each rail channel in linear light as `(1-s) × fill + s × target`.
5. Apply the inverse sRGB transfer function, clamp, round to the nearest 8-bit integer, and serialize uppercase `#RRGGBB`.

Mixing in linear light preserves the source channel relationships when darkening and retains the general hue when lightening. It is deterministic and dependency-free. At the proposed default strength `0.60`:

| Fill | Luminance | Direction | Derived rail |
|---|---:|---|---|
| `#FFFFFF` | 1.000000 | darker | `#AAAAAA` |
| `#000000` | 0.000000 | lighter | `#CBCBCB` |
| `#FFFF00` | 0.927800 | darker | `#AAAA00` |
| `#0000FF` | 0.072200 | lighter | `#CBCBFF` |
| `#FF69B4` | 0.346584 | lighter | `#FFD4E5` |
| `#800080` | 0.061477 | lighter | `#D8CBD8` |

This is overlay-to-overlay contrast, not a claim of WCAG text contrast against arbitrary artwork. Human acceptance must still assess visibility on real artwork.

### 3.6 HEX normalization

Authoring input accepts exactly `#[0-9A-Fa-f]{6}` with no surrounding whitespace. Three-, four-, or eight-digit shorthand, alpha suffixes, CSS names, and missing `#` are rejected. Domain resolution uppercases the six digits before constructing an immutable request. Preview and production use that same resolved uppercase value. Source JSON may retain its authored case; canonical request identity does not.

## 4. Instant composition preview contract

WU4 needs two deliberately different preview types.

### 4.1 Instant composition preview

The proposed `composition-preview-descriptor/1.0` is a pure application result. Creating it performs no FFmpeg invocation and publishes no media. It contains:

- profile and effects contract identifiers;
- 1920×1080 reference canvas and the exact 64-pixel safe rectangle;
- an opaque approved artwork asset reference, intrinsic dimensions, contain/pad geometry, and camera crop at the requested presentation sample;
- ordered visible layers with stable IDs, enabled state, z-order, reference-pixel bounds, colors, opacities, bar rectangles, glow parameters, progress rail rectangle, and progress fill rectangle; and
- a clearly separate illustrative dynamic state containing presentation sample, amplitude, and track progress used only to draw that preview frame.

The descriptor never contains a server filesystem path. A future WU4 API must resolve the opaque artwork reference to a loopback-authorized image resource under the selected project boundary. Exact HTTP routes remain a separate contract decision.

Backend pure functions own safe-area validation, camera geometry, bar layout, HEX normalization, glow color, rail color, and progress math. The React client scales reference pixels uniformly into its viewport and draws the returned layers. It does not independently reimplement renderer formulas. JSON Schema supplies generated TypeScript types; shared checked-in test vectors prove Python/TypeScript serialization and viewport scaling parity.

The UI may request another descriptor as controls change. Because this is pure geometry/color work rather than an encode, it is suitable for local interactive updates. Stable layer IDs such as `artwork`, `audio-bars`, and `track-progress` allow click/keyboard selection to open the corresponding settings panel. Selection, hover, focus, panel state, and viewport scale are UI-only and never enter effects JSON or render fingerprints.

Instant preview can accurately show artwork, contain/pad geometry, a camera crop at one sample, colors, bar layout, glow approximation, progress geometry, layering, and enabled state. It may use an illustrative or cached amplitude and therefore cannot prove live RMS response, temporal easing, blur equivalence, encode color conversion, audio synchronization, or playback smoothness. It must be labeled **Approximate composition preview**.

### 4.2 Rendered motion preview

The existing private lease-owned preview remains authoritative for production behavior. Its next version consumes the same complete effects-v2 request and production graph, real normalized PCM, absolute presentation samples, BT.709 encode, verification, and full decode. It proves camera movement, actual RMS response, track-boundary resets, progress timing, FFmpeg glow, synchronization, and encoding behavior. It remains temporary and is never a published artifact.

## 5. Phase B — renderer refinement

### Proposed files

Create:

- `contracts/schemas/video-effects-v2.schema.json`
- `contracts/schemas/video-manifest-v3.schema.json`
- `contracts/schemas/video-export-request-v3.schema.json`
- `contracts/schemas/video-export-result-v3.schema.json`
- `contracts/schemas/motion-preview-request-v2.schema.json`
- `backend/src/wrld_video_studio/domain/video_effects_v2.py`
- `backend/src/wrld_video_studio/domain/video_export_v3.py`
- `backend/src/wrld_video_studio/domain/visual_refinement.py`
- matching contract fixtures and pure unit tests

Modify only as required to add the new generation alongside existing behavior:

- `infrastructure/project_sources.py`
- `application/video_export.py`
- `application/video_export_worker.py`
- `application/motion_preview.py`
- `infrastructure/video_effect_controls.py`
- `infrastructure/video_export_renderer.py`
- CLI composition and relevant ports

### Acceptance

- Every old fixture, digest, output path, static filter string, and motion-v1 test remains unchanged.
- New schemas reject missing/unknown fields and normalize through domain models to one literal request.
- Organic and symmetrical modes match mathematical vectors; HEX and rail vectors match this document.
- Preview/export identity changes for every output-affecting field and remains stable for canonical equivalents.
- All effect combinations render, verify, and decode through EOF on supported FFmpeg.
- Overlays remain inside the safe rectangle; source audio and sample timeline remain unchanged.
- Cancellation, cleanup, diagnostics, verified reuse, collision rejection, and no-publish preview ownership retain existing guarantees.

## 6. Phase C — real-artwork validation and architectural review

Use an isolated v3 *Echoes of Asia* test project containing only the required regular-file source copies and no publishing metadata. Render one bounded first-track preview with camera, organic bars, glow, and progress. Do not write the album's source or `output/` tree.

Acceptance requires strict probe and full decode plus human review of crop, motion, bar response, glow restraint, rail visibility, progress timing, audio, seeking, and completion. Record tool versions, elapsed time, CPU, peak memory, control-file size, and temporary-disk peak. Keep/release the preview only through its lease contract.

## 7. WU4 — React composition editor (future authorization)

Create the frontend structure already assigned by Doc 15, including:

- `frontend/src/features/review/CompositionPreview.tsx`
- `frontend/src/features/review/VisualControls.tsx`
- `frontend/src/features/review/AudioBarsControls.tsx`
- `frontend/src/features/review/TrackProgressControls.tsx`
- generated contract types under `frontend/src/api/`
- Vitest/React Testing Library tests and the approved Playwright flow

Implement the instant descriptor view, actual artwork loading through an approved loopback API, uniform coordinate scaling, layer selection, keyboard access, enabled-state controls, validation feedback, and explicit rendered-preview action. Do not add drag-and-drop composition, a browser renderer, FFmpeg access, or WU7 layers.

Acceptance requires accurate reference-coordinate scaling, no client-authored defaults or color math, accessible element selection, stale-response protection, and a clear distinction between approximate and rendered previews.

## 8. WU4 integration (future authorization)

Wire approved HTTP contracts to the existing application use cases without adding another scheduler, timeline, or progress model. Prove manifest/save/reload parity, generated TypeScript contract parity, descriptor-to-render geometry vectors, preview/export request equality, cancellation, reconnection, and output identity. Run the complete backend and frontend suites plus Windows FFmpeg and real-artwork smoke tests.

Acceptance requires that the persisted resolved effects object, instant descriptor, rendered preview, and production export identify the same profile/configuration; any approximation is explicitly labeled; and motion-v1/static regressions remain unchanged.

## 9. Test and performance matrix

| Area | Required evidence |
|---|---|
| Organic RMS | Exact formula vectors, repeat-run equality, silence baseline, pulse response, track reset, excerpt/production sample parity, bounded per-frame delta |
| Color | Valid upper/lowercase normalization; rejection of shorthand/alpha/names/whitespace; six rail examples; threshold cases immediately around luminance 0.50 |
| Identity | Every new field changes effects-v2 digest; canonical HEX case does not; v1 fixture/digest remains unchanged; motion-v1/v2/static paths cannot collide |
| Geometry | Minimum/maximum counts, dimensions, gaps, offsets, semantic safe-area rejection, all placements, progress rail full extent, segmented fill |
| Preview parity | Same resolved config and presentation sample produce matching descriptor/reference geometry and decoded rendered geometry within approved pixel tolerance |
| Timing | Existing sample-derived full-track progress and boundary reset tests remain unchanged; no UI duration calculation |
| Lifecycle | Cancellation during analysis/control generation/encode/verify; repeated cancellation; preview lease deletion; no derived-file orphan |
| FFmpeg | Windows 9.0.2 capability probe, all effects, full decode, BT.709, H.264/AAC, no background blur or exposed edge |
| Performance | 1920×1080 effect-off baseline versus bars, bars+glow, and all effects; elapsed time, CPU, peak memory, command-file bytes/minute, temporary-disk peak |

Organic modulation can increase geometry changes and control-file size toward `frames × enabled bars`; this remains linear in duration and bar count. Phase B must stream control generation, retain update-on-pixel-change behavior, add a projected/control-file size assertion in long-duration tests, and avoid holding all commands or PCM in memory. Glow adds one local alpha blur and two local overlays per frame. Blurring a padded bar-zone layer rather than the full background bounds the added work. No NumPy, SciPy, librosa, OpenCV, AI/CV package, socket controller, or raw full-frame dump is proposed.

## 10. Historical Phase B decision disposition

The user approved decisions 1–6 below before Phase B implementation. The WU4-only choice in item 7 remains outside Phase D and is still unresolved until the WU4 contract gate:

1. Approve the additive effects-v2/manifest-v3/request-v3/result-v3/preview-v2/profile-v2 identifier set and explicit-only migration policy.
2. Approve the audio-bar fields, defaults, bounds, safe-area rules, and organic formula in Section 3.
3. Approve the fixed glow derivation, 12-pixel sigma, 36-pixel padding, 0.60 alpha scale, and default intensity 0.35.
4. Approve the progress fields, default rail contrast strength 0.60, default rail opacity 0.35, luminance threshold 0.50, and linear-light derivation examples.
5. Approve strict six-digit HEX normalization to uppercase in resolved requests.
6. Approve the pure application-owned composition descriptor architecture; exact HTTP route and opaque artwork-resource shape remain for the WU4 API contract gate.
7. Decide whether WU4 should use actual cached RMS values at the current playback sample when available or an explicitly illustrative amplitude until a rendered preview is requested. Either choice remains preview-only and outside render identity.

Phase B implementation is an implemented candidate. React/HTTP work still requires its own WU4 authorization.

## 11. Approved consolidated Phase D player generation

Phase D adds `player-overlay/1.0` through effects-v3, manifest/request/result v4, preview request v3, `youtube-1080p30-player-v1`, renderer `wu3b-player-export-1`, layout `wrld-player-layout/1.0`, and palette algorithm `wrld-artwork-palette/1.0`. This generation is additive and never modifies or automatically migrates static, motion-v1, or motion-v2 requests, fingerprints, filters, destinations, or artifacts.

### 11.1 Reference composition and defaults

The backend owns a 1920×1080 coordinate system and rejects layouts that leave the 64-pixel safe area or overlap reserved regions. The bottom-anchored 110-pixel footer defaults to `#101827` at opacity 0.65. The default Subtle Ambient visualizer is 900×110 with 32 organic RMS bars, 8-pixel gaps, opacity 0.55, glow intensity 0.25, and centered placement above the footer. The glow has 36-pixel padding and must remain at least 32 pixels from the footer. Default resolved rectangles are documented in Doc 39 Section 13.

The footer has a progress/time row and one metadata row. The left side shows album plus transitioning track/BPM/key; the right shows distinct parent and genre channels. Text uses an explicitly project-relative Unicode-capable font. Its file hash is frozen into the request. Backend font metrics measure widths and apply deterministic ellipsis truncation; text fields never overlap. Compact informational text is authorized here, while all creative title graphics and layered/title-aware work remain WU7.

### 11.2 Timeline, metadata, and transitions

Progress is explicitly `album` or `track`; the player default is `album`. It uses integer samples from the normalized 48 kHz presentation timeline and deterministic `MM:SS` or `HH:MM:SS` formatting. It never uses prompt duration. The metadata policy prefers reliable analyzed BPM/key, then explicitly intended values with provenance, then omission. It never invents a measurement.

The fixed album/channel/time/progress fields do not transition. Track title/BPM/key fade out only in the three seconds preceding a boundary and the next values fade in only in the three seconds following it, producing the approved six-second transition without overlapping text. Optional track announcements have configurable fade-in, hold, and fade-out values and default disabled for acceptance.

### 11.3 Artwork themes and deterministic identity

Theme modes are Automatic, Manual, and Hybrid; Hybrid is default. Presets use these fixed resolver triples `(saturation scale, accent/white mix, footer/black mix)`: Subtle `(0.65, 0.18, 0.78)`, Balanced `(0.90, 0.10, 0.68)`, and Vibrant `(1.20, 0.04, 0.58)`. FFmpeg downsamples the artwork to a bounded 32×32 RGB sample; the standard-library resolver uses a deterministic 4-bit-per-channel histogram. It resolves footer, primary/secondary text, progress fill/rail, and visualizer colors, with contrast validation against the composited footer.

Canonical identity includes all effects/player values, resolved layout, resolved colors and provenance, artwork SHA-256, palette algorithm version, font SHA-256, display strings and measurement provenance, progress/timeline policy, and presentation rule. `wrld-player-presentation/1.0` removes visible diagnostic field prefixes and decorative separators while leaving typed values/provenance unchanged. The destination is `output/profiles/youtube-1080p30-player-v1/<resolved-config-sha256>/...`; existing verified-reuse and no-replace behavior applies.

The October 28, 2026 visual-correction generation is additive: `wu3b-player-export-2` with `wrld-player-presentation/2.0` repairs compact alpha-mask reconstruction, live progress-command wiring, and player-only camera sampling through a 2× working canvas. No v4 schema, profile, effect setting, layout coordinate, palette rule, or output-root contract changes. The new presentation identity produces a different resolved-config digest, preserving every existing presentation-1.0 artifact and its verified-reuse identity. Presentation-2.0 pixels require a new bounded human visual review.

### 11.4 Phase D acceptance boundary

Phase D reuses one worker/admission model and the existing snapshot, process ownership, cancellation, recovery, progress, diagnostics, verification, staging, publication, report, and private preview lease. It adds no frontend or HTTP contract. Its real-artwork gate is one new 15-second isolated *Echoes of Asia* preview using the player profile and Subtle Ambient settings, strict probe, complete decode, decoded-region checks, and available performance measurements. A partial project must report its actual partial duration and must not fabricate the full album duration. Human review of layout, readability, theme, motion, responsiveness, seeking, and completion is mandatory before acceptance.

## 12. Phase D acceptance and remediation addendum

The user completed the Phase D human review on October 27, 2026 and approved the label-free presentation shown by the retained 30-second three-track acceptance MP4. The evidence included metadata transitions, continuous album progress, playback/seeking review, and clean release of the 15-second temporary preview lease. This is durable acceptance of the reviewed Phase D pixels only; WU3A full-album/full-track acceptance remains independent.

The later final-remediation decision adds numeric accessibility enforcement without claiming that this proposal originally supplied those numbers: ordinary footer text requires 4.5:1 contrast and qualifying large text requires 3:1 against the actual footer/artwork composite. Derived colors may be corrected deterministically. Manual text overrides that fail are rejected with a validation error. Provenance and render identity continue to include the resolved colors.
