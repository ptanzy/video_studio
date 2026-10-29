# 39 — WU3B Core Motion and Audio Visualization

**Status:** Phases 1–4, Doc 40 Phase B motion-v2, Phase C real-artwork validation, and the additive Phase D player-overlay implementation are implementation candidates. The October 27, 2026 human review accepted the reviewed label-free Phase D pixels; other WU3B closure gates remain separately evidenced. Motion-v1 remains unchanged.

## 1. Authority and roadmap position

This document is the specific WU3B authority after Docs 31 and 38. It preserves the implemented WU1–WU3 history and every WU3A v1 contract. It does not close or weaken the independent WU3A acceptance gate.

The approved forward sequence is:

**WU3B → WU4 → WU5 → WU6 → WU7**

WU3A remains **IMPLEMENTED — ACCEPTANCE PENDING** until the real *Echoes of Asia* album and one full track pass the Doc 38 automated and human-playback requirements. WU3B may be implemented after its separate contract approval, but WU3B evidence must never be represented as WU3A acceptance evidence.

## 2. Goal and approved scope

WU3B extends the verified headless album/track renderer with three independently configurable effects over one flat artwork image:

1. bounded slow pan/zoom;
2. lightweight amplitude/RMS-reactive bars; and
3. current-track progress that resets at normalized-sample track boundaries.

All three effects are optional, deterministic, independently enabled, and available to album and individual-track targets. The output remains 1920×1080 H.264/AAC under the existing BT.709, CFR, audio, verification, publication, lifecycle, cancellation, recovery, diagnostic, and progress protections.

WU3B reuses the existing `RenderWorker`, shared heavy-render admission, project boundary, source snapshots, normalized 48 kHz stereo PCM, sample-derived timeline, process ownership, staging, FFprobe checks, full decode, artifact promotion, render report, and private job state. It must not add another scheduler, worker lifecycle, timeline, progress model, or FFmpeg bypass.

## 3. Explicit non-goals

- Separate title PNGs, creative/generated title graphics, title-aware camera limits, synchronized title-layer fades, scene layers, parallax, atmospheric overlays, masking, scene segmentation, effect depth placement, and a dedicated composition editor are WU7. The approved Phase D compact player typography is limited to technical time/metadata and optional track announcements; it does not transfer these WU7 responsibilities.
- WU3B does not generate or alter covers, thumbnails, source artwork, source audio, album folders, or source manifests.
- Frequency-spectrum bars are not WU3B v1. They require a later compatible contract and must not be implied by amplitude graphics.
- React UI, render-job HTTP routes, publishing metadata, YouTube upload, Shorts composition, mastering, AI/CV/DSP packages, GPU requirements, and cloud services remain outside WU3B.
- WU3B must not read, validate, migrate, modify, or generate any `youtube_metadata.json` or `youtube_publish_state.json`.

## 4. Compatibility rules already approved

1. Existing `wrld-video-album/1.0`, `video-export-request/1.0`, `video-export-result/1.0`, `youtube-1080p30-v1`, its output paths, and its rendered bytes are unchanged.
2. A v1 manifest cannot contain effect fields. It continues to select only the static profile.
3. WU3B is additive: a v2 manifest, v2 request/result, and a distinct motion profile are introduced rather than mutating v1 schemas.
4. Fully resolved effect settings are frozen into the immutable export request. Manifest defaults are never consulted again after snapshot creation.
5. Motion artifacts use profile-qualified paths so they cannot collide with v1 static artifacts.
6. Existing job, render-progress, render-diagnostic, and render-report contracts are reused unless implementation proves a strictly necessary additive change. No existing schema is silently widened.
7. Effects-off under the motion profile is deterministic, but it is not represented as a v1 artifact and does not reuse the v1 output path.

## 5. Final recommended versioned contracts — approval required

The following exact names are **PROPOSED FOR APPROVAL**, not yet implemented schemas:

| Purpose | Identifier/file |
|---|---|
| Album manifest | `wrld-video-album/2.0` / `video-manifest-v2.schema.json` |
| Export request | `video-export-request/2.0` / `video-export-request-v2.schema.json` |
| Export result | `video-export-result/2.0` / `video-export-result-v2.schema.json` |
| Motion profile | `youtube-1080p30-motion-v1` |
| Renderer identity | `wu3b-motion-export-1` |
| Preview request | `motion-preview-request/1.0` / `motion-preview-request-v1.schema.json` |

`wrld-render-report/1.0`, `wrld-render-progress/1.0`, the current diagnostic contract, and the current job snapshot/status contracts remain unchanged and may catalog either profile by request digest, renderer identity, and artifact path.

### 5.1 Manifest shape

The v2 manifest preserves the v1 `album`, `visual`, ordered `tracks`, stable-ID, and portable-path rules. Its `render` object is:

```json
{
  "profile_id": "youtube-1080p30-motion-v1",
  "effects": { "...": "complete effect configuration from Section 6" },
  "track_effects": [
    {
      "track_id": "stable-track-id",
      "effects": { "...": "complete effect configuration from Section 6" }
    }
  ]
}
```

`effects` is required and is the album configuration and the default for track exports. `track_effects` is optional, defaults to an empty array, allows at most one entry per existing track ID, and supplies a complete replacement configuration rather than a recursive partial merge. An album request always uses `render.effects`. A track request uses its matching `track_effects` entry or falls back to `render.effects`.

This structure stores chosen settings in the project manifest while allowing individual track videos to differ. Reusable presets are optional authoring conveniences for WU4–WU6: a preset must resolve to the complete Section 6 object before request creation, and preset names are not renderer input or artifact identity.

### 5.2 Immutable request and result

The v2 export request requires exactly:

```json
{
  "contract_version": "video-export-request/2.0",
  "target": { "kind": "album" },
  "profile_id": "youtube-1080p30-motion-v1",
  "effects": { "...": "complete resolved effect configuration" }
}
```

The existing album/track target union is unchanged. The request contains no filesystem path, preset reference, output override, force-replace switch, or publishing field. The trusted composition supplies the album-project root separately, as in WU3A.

The v2 result preserves every v1 result field and adds required `profile_id` and the complete resolved `effects` object. Artifact kinds remain `album_video`, `track_video`, and `chapters`; paths remain project-relative. No creative or publishing metadata is added to the technical result.

## 6. Final recommended effect contract and defaults — approval required

All objects use `additionalProperties: false`. All numbers must be finite JSON numbers. Defaults below are manifest-authoring defaults; the immutable request always materializes every field. Disabled effect parameters remain validated and fingerprinted so the request has one literal meaning.

```json
{
  "pan_zoom": {
    "enabled": false,
    "max_zoom": 1.04,
    "path": "diagonal_down_right",
    "cycle_seconds": 180.0,
    "return_to_origin": true,
    "return_duration_seconds": 5.0,
    "easing": "smoothstep"
  },
  "audio_bars": {
    "enabled": false,
    "bar_count": 24,
    "opacity": 0.65,
    "placement": "bottom_center",
    "rms_window_samples": 1920,
    "attack_ms": 60.0,
    "release_ms": 240.0
  },
  "track_progress": {
    "enabled": false,
    "style": "line",
    "placement": "bottom",
    "opacity": 0.80,
    "thickness_px": 6,
    "segment_count": 20
  }
}
```

| Field | Allowed value |
|---|---|
| `pan_zoom.max_zoom` | `1.00`–`1.05`, inclusive |
| `pan_zoom.path` | `center`, `horizontal`, `vertical`, `diagonal_down_right`, `diagonal_up_right` |
| `pan_zoom.cycle_seconds` | `15.0`–`600.0`, inclusive |
| `pan_zoom.return_duration_seconds` | `0.5`–`30.0`, inclusive |
| `pan_zoom.easing` | `smoothstep` only in motion v1 |
| `audio_bars.bar_count` | integer `8`–`64` |
| `audio_bars.opacity` | `0.10`–`1.00` |
| `audio_bars.placement` | `bottom_left`, `bottom_center`, `bottom_right` |
| `audio_bars.rms_window_samples` | integer `480`–`4800` at normalized 48 kHz |
| `audio_bars.attack_ms` | `0.0`–`500.0` |
| `audio_bars.release_ms` | `0.0`–`1000.0` |
| `track_progress.style` | `line`, `segmented` |
| `track_progress.placement` | `top`, `bottom` |
| `track_progress.opacity` | `0.10`–`1.00` |
| `track_progress.thickness_px` | integer `2`–`16` |
| `track_progress.segment_count` | integer `5`–`60`; used only by `segmented` but always validated/fingerprinted |

### 6.1 Pan/zoom semantics

- The existing contain-and-black-pad operation first creates the approved 1920×1080 canvas. Motion operates on that canvas, preserves aspect ratio, and never stretches the image.
- Zooming necessarily crops some canvas content. At `1.05`, up to approximately 2.38% of the canvas dimension is removed at each centered edge before pan offset. WU3B does not inspect flattened title locations.
- The configured path traverses only the crop-safe rectangle available at the current zoom. At `1.00`, offset is zero. No uninitialized or transparent border may appear.
- `cycle_seconds` is one deterministic out-and-back movement cycle. At time `t`, let `u = (t mod cycle_seconds) / cycle_seconds`, `q = 2u` for `u <= 0.5` and `q = 2(1-u)` otherwise, and `e = smoothstep(q)`. Zoom is `1 + (max_zoom - 1)e`. The path offset is the selected far-point vector multiplied by `e`; horizontal uses the positive safe x extreme, vertical the positive safe y extreme, and the two diagonal values use the positive x extreme with respectively positive or negative safe y. `center` has a zero vector. Motion uses the absolute target timeline, not track-relative time, so an album camera never resets at a track boundary.
- `smoothstep(t) = 3t² - 2t³` is used for each half-cycle and for final return. No random seed or host clock affects motion.
- If `return_to_origin` is true, the final `min(return_duration_seconds, target_duration / 2)` seconds override the cycle and ease from the current camera state to centered `1.00×`. The final displayed video frame must be at the original framing within one output-pixel tolerance. If false, motion ends at its deterministic timeline state.
- `path: center` applies zoom only. Other paths start from center and remain inside the valid crop rectangle.

### 6.2 Amplitude/RMS bars semantics

- WU3B v1 uses a lightweight precomputed RMS envelope from the normalized PCM. It is an amplitude display, not a frequency analyzer.
- RMS is computed across both normalized channels over `rms_window_samples`, with one envelope sample for each 30 fps output frame. The nominal window is centered on the frame's presentation sample; it is intersected with the current track's half-open sample interval and never consumes a neighboring track's samples. The mean square denominator is the actual number of interleaved channel samples in that clipped window.
- The envelope maps `-60 dBFS` or lower to zero and `0 dBFS` to one, clamped linearly in decibel space. Exact zero/silence yields the fixed baseline; it must not produce random motion or `-inf` arithmetic.
- Attack and release are deterministic one-pole filters. For frame interval `Δ = 1/30` seconds and selected time constant `τ`, `alpha = 1 - exp(-Δ/τ)`; `τ = 0` means `alpha = 1`. Use attack alpha when the raw value is at least the previous smoothed value and release alpha otherwise. Smoothing state is reset to zero at each exact normalized-sample track boundary.
- The bars are fixed white under motion v1; `opacity` controls alpha. They occupy a 640×180 pixel zone with a 64-pixel outer margin. Placement selects the left, centered, or right zone along the lower safe area. Four pixels separate equal-width bars.
- Each bar shares the same amplitude envelope. For zero-based bar `i` of `N`, its fixed symmetric height multiplier is `0.25 + 0.75 sin²(π(i + 0.5)/N)`. This creates an amplitude meter, not simulated frequency bands. Silence draws a two-pixel baseline.
- The implementation recommendation is a bounded precomputed control stream consumed by the production FFmpeg graph. A capability spike must prove the chosen `sendcmd`/filter integration or select an equivalently bounded deterministic implementation before Phase 3. `zmq`, live control sockets, uncompressed full-duration frame dumps, and heavyweight DSP dependencies are not required or approved.

### 6.3 Track-progress semantics

- Progress is calculated only from the existing normalized-sample timeline. Backend job progress remains a separate `wrld-render-progress/1.0` record.
- For output frame index `n`, the presentation sample is `n × 1600` because the profile is exactly 48,000 samples/s and 30 fps. The frame belongs to the last track whose `start_sample` is less than or equal to that presentation sample.
- If a boundary is not frame-aligned, the first frame whose presentation sample is greater than the boundary is the first frame of the new track. That frame resets displayed progress; no frame is synthesized at the fractional boundary.
- Progress is `(presentation_sample - track.start_sample) / track.sample_count`, clamped to `[0, 1]`. A single-track export uses a zero start sample and that track's normalized sample count.
- `line` is a continuously filled line. `segmented` fills `segment_count` equal cells from left to right. Both use fixed white, the configured opacity/thickness, a 64-pixel horizontal margin, and the selected top or bottom safe edge.
- The progress zone and bar zone are geometrically separate. WU3B does not detect collisions with text baked into the flat artwork; placement changes or disabling an effect are the available mitigations until WU7.

## 7. Encoding, output identity, reuse, and errors

The motion profile inherits every `youtube-1080p30-v1` media setting: 1920×1080 CFR 30 fps, H.264 High, `yuv420p`, CRF 18, `medium`, BT.709, AAC-LC 48 kHz stereo 192 kbit/s, and `+faststart`. Only the deterministic video filter graph differs.

Static paths remain exactly:

```text
output/album/<safe-album-title>.mp4
output/tracks/<NN> - <safe-track-title>.mp4
```

Recommended motion paths are:

```text
output/profiles/youtube-1080p30-motion-v1/<full-effect-config-digest>/album/<safe-album-title>.mp4
output/profiles/youtube-1080p30-motion-v1/<full-effect-config-digest>/tracks/<NN> - <safe-track-title>.mp4
```

The effect-config digest is SHA-256 over the canonical complete resolved `effects` object only, using sorted keys and the same canonical JSON rules as job snapshots. Its full 64-character directory prevents static/motion collision and permits multiple approved effect configurations without creating a circular dependency between output planning and the job request digest. Source/tool changes with the same effect configuration retain the existing WU3A collision behavior at that path. Album chapters remain the profile-independent `output/metadata/chapters.txt`; the shared `output/metadata/render_report.json` catalogs every verified artifact.

The full digest adds path length on Windows. Preflight must validate the resolved destination against the supported filesystem/toolchain before job submission and return `INVALID_OUTPUT_PATH` rather than truncate a title/digest, redirect output, or fail after encoding. Contract tests include long but otherwise valid project/title paths.

The canonical request digest includes the complete resolved v2 request, renderer identity, sorted input fingerprints, and media-tool identity using the existing canonical snapshot algorithm. Every effect field participates. Exact verified matches may be reused. An existing path with missing/mismatched provenance or bytes fails under the existing collision/validation policy; WU3B adds no force replacement.

Schema-shape, enum, type, non-finite, or bound violations fail before job submission as `MANIFEST_SCHEMA_INVALID` for the source manifest or `INVALID_EXPORT_REQUEST` for a request. Unsupported versions/profiles use the existing unsupported-manifest/request behavior; a request/manifest profile mismatch remains `PROFILE_MISMATCH`. Missing required FFmpeg filter capability fails preflight as `MEDIA_TOOL_INVALID`. Published-path collision remains the existing output collision/existence failure. No raw command, absolute source path, or unsanitized tool exception enters public result fields.

## 8. Temporary motion preview contract — approval required

WU3B provides an application-level motion-preview use case; it does not approve an HTTP route or React UI.

`motion-preview-request/1.0` contains the same target, `youtube-1080p30-motion-v1` profile, and complete effects object as the v2 export request, plus:

```json
{
  "excerpt": {
    "start_sample": 0,
    "sample_count": 240000
  }
}
```

- `start_sample` is target-relative, nonnegative, and must be within the target timeline.
- `sample_count` is 144,000–720,000 normalized sample frames (3–15 seconds), inclusive; the authoring default is 240,000 (5 seconds).
- The excerpt must fit entirely inside the selected target. Album excerpts may cross track boundaries so reset behavior can be previewed.
- Preview uses the same resolved sources, audio normalization, effect builder, BT.709 encoding, verification, full-decode path, cancellation, and shared heavy-render admission as publication. It renders full 1920×1080 output for fidelity; only duration and destination ownership differ.
- Output is an attempt-owned private temporary MP4, never under album `output/`, never entered into `render_report.json`, and never returned as a server filesystem path.
- Concurrent identical verified requests may share one in-flight result through lease ownership. There is no completed persistent preview cache in WU3B v1: the file is deleted after the final consumer lease closes. Cancelling one consumer does not cancel work still owned by another; cancelling the final consumer cooperatively stops/reaps work and removes owned staging within the existing bounded shutdown contract.
- A preview failure uses the existing private diagnostic record and exposes only a stable safe error. An invalid excerpt uses new proposed code `PREVIEW_RANGE_INVALID`; general contract errors use `PREVIEW_INVALID_REQUEST`.

WU4 may expose this use case through a separately approved API and UI. WU6 may reuse it from render confirmation. Neither unit may treat a preview as a published or verified final artifact.

## 9. Phased implementation plan

### Phase 1 — contracts and pure domain behavior

Create v2 manifest/request/result and preview schemas/fixtures; add immutable effect models, semantic validation, manifest-to-request resolution, frame/boundary math, canonical serialization, renderer versioning, and profile-qualified planning. Preserve all v1 fixtures and behavior byte-for-byte at the contract boundary.

Expected files: new schemas and contract fixtures/tests; additive models in `domain/video_export.py`; additive planning/resolution tests. Do not change the v1 schema files.

### Phase 2 — camera motion

Add one deterministic effect/filter builder and extend the existing video-export handler/renderer by request profile. Prove contain/pad, crop-safe bounds, easing, continuous album time, optional final return, cancellation, strict BT.709 verification, and effects-off behavior on tiny generated media.

Expected files: `infrastructure/video_export_renderer.py`, its unit/integration tests, and only the minimum application wiring needed to select the approved renderer profile.

### Phase 3 — RMS bars and track progress

Add a standard-library PCM envelope builder and bounded control artifact; reset analysis at timeline boundaries; compose bars and progress through the same production graph. First run a tool-capability preflight for the exact approved FFmpeg filters. Do not add NumPy, SciPy, librosa, AI/CV packages, `zmq` runtime control, or a parallel browser renderer.

Expected files: one small domain/application envelope module, renderer integration, owned scratch/control cleanup, and focused unit/media tests.

### Phase 4 — temporary preview and lifecycle integration

Add the application preview request/result/lease ports, shared admission and same-flight ownership, private staging, bounded cleanup, cancellation/recovery, and final-consumer deletion. No HTTP or frontend work.

The final-remediation policy further bounds interactive work: only tracks intersecting the excerpt are normalized, with ten RMS release time constants of pre-roll and half an RMS window of tail where bars are enabled. Album-relative sample time, track transitions, and total duration remain based on the probed full timeline. Each preview service allows four distinct running/queued identities; identical requests share one flight, while overflow returns `PREVIEW_CAPACITY_EXHAUSTED`. Application-owned owner markers and locks permit conservative, bounded cleanup of crash-abandoned preview directories without deleting active or unmarked state.

### Phase 5 — regression and acceptance

Run v1 contract/full backend regression, WU3A static real-media integration, WU3B generated-media tests, Windows/Ubuntu FFmpeg matrix, cancellation/recovery/reuse tests, and manual Windows motion review. Report WU3A and WU3B acceptance independently.

## 10. Required tests and acceptance

### Pure tests

- Every v1 valid/invalid fixture remains unchanged; a v1 manifest rejects v2 fields and a v2 manifest cannot select the static profile.
- Valid v2 defaults and every boundary value; unknown fields/enums, duplicate/unknown track overrides, non-finite numbers, and out-of-range values fail with the documented code.
- Album and per-track effect resolution produce complete immutable requests; presets, missing defaults, and partial recursive merges cannot reach the renderer.
- Canonical request/digest changes for every effective field and remains stable for identical resolved input.
- Camera position/zoom never leaves its crop-safe rectangle; cycle/easing/return calculations are deterministic and do not reset on a track boundary.
- RMS windows do not cross tracks; silence baseline, pulses, attack/release, stereo combination, and reset state are exact.
- Frame-to-sample mapping covers aligned and non-aligned boundaries, consecutive short tracks, final-frame clamp, album target, and single-track target.

### Tiny generated-media tests

- Two-to-four-second generated WAV/PNG renders for each effect alone, all effects together, and all effects disabled.
- Decoded frames prove 1920×1080, no exposed edge, no stretch, maximum zoom, smooth camera bounds, visible bars for pulses, silence baseline, correct placements, monotonic progress, and boundary reset.
- Distinct tones/chirps prove source order and audio content are unchanged. Probe and full decode must pass through EOF.
- Tests compare decoded pixels/geometry with tolerances; they never require byte-identical H.264 across platforms.

### Lifecycle and identity tests

- Cancellation during envelope generation, encoding, verification, publication, and preview streaming; repeated cancellation; startup reconciliation; cleanup failure; process timeout; no orphan task/process/control file.
- The same exact motion request reuses only its verified artifact. Changed effects select a different effect-digest path. Changed source or tool identity with the same effects retains the same planned path and therefore follows WU3A's existing verified-reuse-or-collision rule; it is never silently replaced. Corrupt or mismatched existing output is never accepted. Static and motion exports cannot collide.
- Long Windows project/title paths fail during destination preflight before rendering if the configured toolchain cannot address the full profile/effect-digest path.
- Preview range validation, cross-boundary excerpt, same-flight joining, one-caller cancellation, final-owner cancellation, lease cleanup, shutdown overlap, and proof that no preview enters the final report.

### Real Windows smoke and human acceptance

1. Verify the configured FFmpeg build exposes the exact filters chosen after the Phase 3 capability spike; record `ffmpeg -version`, `ffprobe -version`, encoders, and relevant `-filters` output.
2. Render and fully decode a bounded real *Echoes of Asia* preview containing motion, bars, and progress, preferably across a track boundary.
3. Render and fully decode one full real track with all approved effects.
4. Human-review the preview and full track in VLC or Windows Media Player for motion smoothness, crop acceptability, no exposed borders/flicker, amplitude response, progress reset/finish, audio continuity, seeking, and playback through the end.
5. Record CPU, peak memory, elapsed time, temporary-disk peak, tool versions, and pass/fail observations.

WU3B acceptance requires all applicable automated tests and this human review. It does not require rerendering the full real album and cannot close WU3A's separate real-album acceptance.

## 11. Downstream ownership

- **WU4:** React Import/Review, effect controls that reveal only the selected effect's bounded fields, v2 manifest/override editing, and temporary motion-preview invocation. It consumes WU3/WU3B services; it does not create a UI-only renderer or scheduler.
- **WU5:** publishing metadata only. It may display the shared timeline/chapters and preserve chosen video settings while editing metadata, but it neither owns nor recalculates effects.
- **WU6:** approved render-job HTTP contract and integrated Render UX. It displays the selected profile/effect summary and the existing backend job progress, submits the same immutable v2 request, and never confuses rendered track progress with job progress. Shorts remain WU6 only to the extent separately approved by its contract.
- **WU7:** planned advanced composition: independent title layers/PNGs, title-aware crop/fade behavior, layered artwork, parallax, atmospheric effects, effect depth placement, masks, scene composition, and a dedicated visual editing UI. WU7 is not implemented or authorized by this document.

## 12. Historical approval gate and current acceptance

The user approved the original implementation decisions below before Phases 1–4 were implemented:

1. the identifiers and v2 manifest/request/result shapes in Section 5;
2. the exact fields, defaults, bounds, paths, overlay constants, and frame semantics in Sections 6–7;
3. digest-addressed motion output paths and unchanged no-replace behavior;
4. the temporary preview contract and no-persistent-cache policy in Section 8; and
5. the precomputed RMS/control-stream recommendation, including the requirement for a Phase 3 FFmpeg capability spike.

Those contracts now remain the compatibility authority for motion-v1. Final WU3B acceptance still requires the applicable regression evidence and real-artwork human review in Section 10. Doc 40's proposed visual refinement has its own approval and implementation gates and must not be appended silently to these contracts.

## 13. Additive Phase D player-overlay generation

The user approved a new player generation alongside, not inside, the static, motion-v1, and motion-v2 generations. Its identifiers are:

| Purpose | Identifier/file |
|---|---|
| Player settings | `player-overlay/1.0` / `player-overlay-v1.schema.json` |
| Effects | `video-effects-v3.schema.json` |
| Album manifest | `wrld-video-album/4.0` / `video-manifest-v4.schema.json` |
| Export request/result | `video-export-request/4.0`, `video-export-result/4.0` |
| Preview request | `motion-preview-request/3.0` |
| Render profile | `youtube-1080p30-player-v1` |
| Renderer identity | `wu3b-player-export-1` |
| Resolved layout/theme | `wrld-player-layout/1.0`, `wrld-artwork-palette/1.0` |

Outputs are isolated beneath `output/profiles/youtube-1080p30-player-v1/<resolved-config-sha256>/...`. The identity is the canonical SHA-256 of the full v3 effects object, resolved player configuration, and presentation identity. `wrld-player-presentation/1.0` renders raw field values without visible diagnostic labels or decorative separators. The digest therefore binds pixel-affecting settings, geometry, artwork/palette identity, resolved colors/provenance, font identity, display metadata/provenance, progress policy, and presentation rule. No old manifest is rewritten or implicitly promoted.

The additive visual-correction generation retains every identifier in the table except renderer and presentation identity: corrected work uses `wu3b-player-export-2` and `wrld-player-presentation/2.0`. It fixes compact 16-bit control-mask alpha reconstruction, connects progress commands to the live video chain regardless of whether compact bars are enabled, and renders player camera motion from a 2× working canvas before producing 1920×1080 frames. Footer, metadata, timer, progress, and visualizer composition remain after the camera filter and therefore stationary. Presentation identity remains part of the resolved-config digest, so presentation-1.0 files and verified reuse are preserved in their existing digest directory. These repairs do not alter the v4 request, manifest, result, player-overlay, profile, layout, palette, effect settings, output root, or no-replace contract.

The backend resolves a 1920×1080 reference layout. The safe area is x=64..1856 and y=64..1016. The default footer is `(64,906,1792,110)`; the default Subtle Ambient visualizer is `(510,728,900,110)` and its 36-pixel padded glow extent is `(474,692,972,182)`. The glow bottom is exactly 32 pixels above the footer. Resolvers reject unsafe containment and overlaps rather than moving layers silently.

Subtle Ambient uses 32 organic RMS bars, 8-pixel gaps, opacity 0.55, glow intensity 0.25, centered horizontal placement, and footer-relative vertical placement. The compact footer defaults to `#101827` at opacity 0.65 and is independently switchable. Its progress row contains deterministic elapsed time, rail/fill, and total duration. Its single metadata row keeps album and track/BPM/key on the left and parent/genre channels on the right, using a project-relative Unicode-capable font, measured widths, and deterministic truncation.

Progress has explicit `album` and `track` modes and defaults to album mode for this profile. All progress and `MM:SS`/`HH:MM:SS` values derive from integer samples on the normalized 48 kHz presentation timeline. A six-second boundary transition fades outgoing track metadata during the three seconds before a boundary and incoming metadata during the three seconds after it; track strings never overlap. Album identity, channels, time, and progress remain stationary. Optional track announcements have explicit fade-in/hold/fade-out settings and are disabled for initial acceptance.

Theme modes are `automatic`, `manual`, and `hybrid`; default is Hybrid. Presets are Subtle, Balanced, and Vibrant with deterministic resolver constants recorded in Doc 40. Palette extraction uses the owned FFmpeg toolchain to create a bounded sample and pure-Python resolution; it adds no heavyweight image/CV dependency. The result binds artwork hash, algorithm version, all resolved colors, and per-color provenance.

Phase D retains the shared worker, admission lane, snapshot, cancellation, recovery, staging, verification, reporting, preview lease, and complete-decode contracts. It adds no HTTP/React work and never reads publishing metadata. Acceptance requires contract/domain/lifecycle regressions, decoded-pixel and synthetic multi-track proof, supported Windows FFmpeg execution, and a retained 15-second isolated *Echoes of Asia* player preview for human review.
