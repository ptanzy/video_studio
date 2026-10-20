# Rendering and media pipeline

## Baseline
The bundled legacy v2 uses FFmpeg to normalize input to 48 kHz stereo PCM, concatenate without crossfades, burn ASS titles, and encode H.264/AAC. It renders Shorts directly from original artwork and track excerpt rather than cropping a lossy compilation MP4. Preserve this behavior while refactoring. `ffprobe` is a new explicit requirement for robust validation.

## Required outputs
```
output/
  compilation.mp4
  thumbnail_1280x720.jpg
  preview_320x180.jpg
  youtube_description.txt
  uploads.csv
  render_report.json
  shorts/
    T01-S01.mp4
    T01-S01_description.txt
```
Names should be deterministic and sanitized; stable IDs preferred to titles. Do not silently overwrite successful prior output without explicit overwrite option.

## Audio and timing
- Source WAVs untouched. Probe sample rate, channels, duration. Convert temporary concatenation audio to common 48 kHz stereo PCM. No forced loudness normalization or mastering.
- Build exact timeline from normalized audio sample counts; preserve fractional offsets internally. Generate YouTube chapter times separately with explicit rounding policy and validate monotonicity. No crossfades in POC.
- Shorts excerpt boundaries are track-relative. Apply audio `atrim`/`asetpts` or precise input seek and `-t`, and confirm output length; fades optional and bounded. A Short's audio must never leak into next track.
- `-shortest` and duration flags require tests to avoid truncated last frames. AAC encoder padding/timing tolerance must be documented and verified.

## Video and effects
- Full: 1920x1080/30fps, H.264 yuv420p, AAC, `+faststart`.
- Shorts: 1080x1920/30fps, portrait blurred fill with foreground artwork, same typography/compact bars/progress; mood grade applied to entire composed background or both layers consistently. Expose `crop` and `letterbox` as alternatives.
- Zoom/pan default from 1.00 to ~1.04 over entire compilation (or per-Short for Shorts). Grain very subtle and optional. Avoid flicker, repetitive loop jumps, or overly noisy output.
- Bars: small amplitude-reactive vertical bars immediately left of title; implement via precomputed envelope or filter graph, deterministic and testable. Ensure title positioning accounts for bar width. Bar counts/config validated.
- Progress bar represents current track on compilation and selected excerpt on Short; reset precisely at boundaries. No rendering required for waveform audition.
- Color presets: `original`, `cool`, `warm`, `lavender`, `teal`, `dark`. Auto mapping from track mood is deterministic, unknown moods -> original. UI intensity bounded and reflected in preview/final.
- Fonts: package no font files; use configured system font with documented fallback. Subtitle escaping must handle unicode, apostrophes, backslashes, commas, colons, and Windows paths.

## Publishing metadata
- Description contains track list and timestamps; YouTube chapter eligibility rules may require >=3 chapters and minimum lengths. Keep timestamps even when eligibility isn't met; warn.
- Each Short gets title and description referencing album/track and a placeholder for the eventual compilation URL. CSV is for human upload planning, not direct API submission. No automatic claims about monetization.

## Verification and failure
After rendering, use ffprobe JSON to verify streams, codecs, dimensions, nonzero duration, expected duration tolerance, fps, audio presence. Decode sample frames/audio where practical to catch corrupt files. On failure record reason and keep original inputs; mark partial output failed, never success. Capture FFmpeg stderr in logs and provide human-readable errors.

## v1.1 binding requirements
Follow `11_JOB_LIFECYCLE_AND_RECOVERY.md` for render staging, idempotency, cancellation, promotion, reconciliation and logs. Follow `12_VISUAL_AUDIO_REGRESSION.md` for post-render content verification. All successful outputs must be probed **before** publication.
