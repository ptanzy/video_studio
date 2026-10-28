# Rendering and media pipeline

## Baseline
The bundled legacy v2 uses FFmpeg to normalize input to 48 kHz stereo PCM, concatenate without crossfades, burn ASS titles, and encode H.264/AAC. It renders Shorts directly from original artwork and track excerpt rather than cropping a lossy compilation MP4. Preserve this behavior while refactoring. `ffprobe` is a new explicit requirement for robust validation.

## WU3A allocation

WU3A implements the first product album and individual-track MP4 slice using static source artwork, ordered WAV audio, exact derived timeline, H.264/`yuv420p`/AAC/`+faststart`, chapter output, and the existing verified job lifecycle. The caller-selected album directory is the project boundary and the `output/` tree below is relative to it; no generated artifact may be redirected to the development repository or a sibling album. For WU3A, generated motion, title overlays, grain, bars, progress graphics, portrait/Short composition, thumbnails, descriptions, and upload CSV remain deferred. The complete output tree below remains the final product target, not the minimum WU3A artifact set. Doc 38 controls WU3A output and acceptance.

## WU3B allocation

Doc 39 moves only flat-image pan/zoom, amplitude/RMS bars, and rendered current-track progress into WU3B. Its additive v2 motion profile inherits WU3A's exact 1080p30 H.264/AAC/BT.709 settings, normalized-sample timeline, verification, and lifecycle while keeping v1 static behavior and paths unchanged. Older effect examples below are product direction only where Doc 39 does not define a more specific contract. Frequency-spectrum graphics, grain, generated/title layers, title-aware motion/fades, parallax, atmospheric/layered composition, and effect depth remain deferred to a later approved extension or WU7. WU3B implementation remains blocked until Doc 39's exact proposed contracts are approved.

## Approved output contract
```text
output/
  album/<safe-album-title>.mp4
  tracks/<NN> - <safe-track-title>.mp4
  shorts/<stable-short-id>.mp4
  metadata/youtube_metadata.json
  metadata/chapters.txt
  metadata/render_report.json
  metadata/youtube_publish_state.json
```
WU3A creates album/track MP4s, `chapters.txt`, and `render_report.json` only as needed. WU5 owns `youtube_metadata.json`; WU3A must not read, validate, migrate, modify, or generate it. WU6 owns Shorts; a future publisher owns `youtube_publish_state.json` and no placeholder is created. Exact naming, sanitization, reuse, and collision behavior are approved in Doc 38 Decision 5. No stage silently overwrites a different existing file. A future work unit may add an explicit controlled replacement operation under a separately approved recoverable contract.

## Audio and timing
- Source WAVs untouched. Probe sample rate, channels, duration. Convert temporary concatenation audio to common 48 kHz stereo PCM. No forced loudness normalization or mastering.
- Build exact timeline from normalized audio sample counts; preserve fractional offsets internally. Generate YouTube chapter times separately with explicit rounding policy and validate monotonicity. No crossfades in POC.
- Shorts excerpt boundaries are track-relative. Apply audio `atrim`/`asetpts` or precise input seek and `-t`, and confirm output length; fades optional and bounded. A Short's audio must never leak into next track.
- `-shortest` and duration flags require tests to avoid truncated last frames. AAC encoder padding/timing tolerance must be documented and verified.

## Video and effects
- WU3A approved profile: `youtube-1080p30-v1` = 1920×1080 CFR 30 fps, H.264 High/`yuv420p`/CRF 18/`medium`/BT.709, AAC-LC 48 kHz stereo 192 kbit/s, and `+faststart`.
- Shorts: 1080x1920/30fps, portrait blurred fill with foreground artwork, same typography/compact bars/progress; mood grade applied to entire composed background or both layers consistently. Expose `crop` and `letterbox` as alternatives.
- Zoom/pan default from 1.00 to ~1.04 over entire compilation (or per-Short for Shorts). Grain very subtle and optional. Avoid flicker, repetitive loop jumps, or overly noisy output.
- Bars: small amplitude-reactive vertical bars immediately left of title; implement via precomputed envelope or filter graph, deterministic and testable. Ensure title positioning accounts for bar width. Bar counts/config validated.
- Progress bar represents current track on compilation and selected excerpt on Short; reset precisely at boundaries. No rendering required for waveform audition.
- Color presets: `original`, `cool`, `warm`, `lavender`, `teal`, `dark`. Auto mapping from track mood is deterministic, unknown moods -> original. UI intensity bounded and reflected in preview/final.
- Fonts: package no font files; use configured system font with documented fallback. Subtitle escaping must handle unicode, apostrophes, backslashes, commas, colons, and Windows paths.

WU3A v1 holds `visual.background` static for the complete album or track duration. The approved operation is orientation correction, alpha over black, aspect-preserving fit, and symmetric black padding with no crop/stretch or generated title overlay. The current exact 1920×1080 *Echoes of Asia* background requires no geometry change and its visible title now matches the album; the historical mismatch is resolved subject to normal file validation.

## Publishing metadata
- Description contains track list and timestamps; YouTube chapter eligibility rules may require >=3 chapters and minimum lengths. Keep timestamps even when eligibility isn't met; warn.
- Each Short gets title and description referencing album/track and a placeholder for the eventual compilation URL. CSV is for human upload planning, not direct API submission. No automatic claims about monetization.

## Verification and failure
After rendering, use ffprobe JSON to verify streams, codecs, dimensions, nonzero duration, expected duration tolerance, fps, audio presence. Decode sample frames/audio where practical to catch corrupt files. On failure record reason and keep original inputs; mark partial output failed, never success. Capture FFmpeg stderr in logs and provide human-readable errors.

## v1.1 binding requirements
Follow `11_JOB_LIFECYCLE_AND_RECOVERY.md` for render staging, idempotency, cancellation, promotion, reconciliation and logs. Follow `12_VISUAL_AUDIO_REGRESSION.md` for post-render content verification. All successful outputs must be probed **before** publication.
