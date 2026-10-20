# Copilot implementation handoff: WRLD Music YouTube compilation MVP

## Goal
A free, offline, standalone tool for quickly publishing existing WRLD-FI test recordings as 12-track YouTube compilations. This is **not** the story/scene-based WRLD-FI visual system, **not** an A/B selection pipeline, and **not** the Music Analyzer.

## Current starter implementation
`build_video.py` uses only Python's standard library plus FFmpeg. `manifest.example.json` defines explicit playback order, audio files, titles and a background. See `README.md` for usage.

## Acceptance criteria
1. Accept 1–12 tracks, with explicit ordered manifest entries and descriptive errors for missing files.
2. Preserve original audio files; use temporary working files; avoid automatic mastering or loudness changes.
3. Convert all inputs to a common audio format before concatenation; use sample counts for track durations.
4. Render one background at 1920×1080, 30fps; show the current track title at correct boundaries.
5. Export a playable H.264/AAC MP4 with audio spanning the entire compilation.
6. Export a description with timestamps beginning at 00:00, plus a machine-readable render report.
7. Work with Windows paths containing spaces; clean up temp files on failure.
8. No API credentials, cloud calls, YouTube uploads, paid tools, or analyzer integration in MVP.

## Important implementation review items
- Inspect FFmpeg invocation for Windows portability and libass availability.
- Confirm exact track transitions and absence of audible gaps; test with different source sample rates and channel layouts.
- Confirm image orientation/cropping and legible titles on light/dark backgrounds.
- Add an optional `--dry-run` validation mode, clearer FFmpeg failure messages, and an automated smoke test with short generated WAVs and a generated background.
- Test Unicode titles, punctuation, apostrophes, long names, and unusual filenames.
- Ensure the rendered audio is neither cut short nor padded with unwanted silence.
- Consider optimizing rendering with hardware encoders or still-image codecs later, without adding complexity now.

## Deliberately deferred
Audio visualizer, waveform, slow zoom, animation, individual song videos, thumbnails, auto-upload, playlist creation, analytics, music analysis, rankings, audio refinement, and album schema migration.

## Integration later
Add an adapter that reads a future canonical WRLD album manifest. Do not assume that an existing WRLD-FI planning JSON has local audio paths or final selected track order. Keep this standalone manifest independent for now.

## Extension: track-relative Shorts and thumbnail assets
- Support zero or more `shorts` per track, each with `start_seconds`, `end_seconds`, optional `title`.
- Validate finite numeric timestamps, nonnegative start, strictly increasing end, end within track duration, and clip length <= 180 seconds. Reject NaN/infinity too.
- Generate portrait 1080×1920 Shorts with the same background and title aesthetic, using source audio rather than extracting from lossy compilation. Do not stretch landscape images.
- Generate 1280×720 thumbnail and 320×180 preview images from background.
- Record short provenance and compilation-relative offsets in render report.
- Preserve backward compatibility for manifests without `shorts`.
- Add tests for track 5 at 45–75s, multiple shorts per track, boundaries, missing data, Windows paths, and vertical cropping.
- Future enhancement: use analyzer-provided highlight windows as inputs; do not require analyzer in this MVP.
