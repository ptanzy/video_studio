# Product specification

## Goal
Publish existing WRLD-FI test recordings quickly. An album typically contains 12 WAVs, one image, and an ordered manifest. There is no scene/story system or A/B selection requirement for this POC. Support 1–12 tracks initially; don't hardwire 12 throughout the core. All audio remains unchanged musically; technical conversion for MP4 is allowed.

## User journey
1. **Import** a manifest or create a new project by selecting ordered audio files and an artwork image. Validate before proceeding.
2. **Review** a carousel of tracks and their zero-or-more Shorts. See actual artwork-derived visual previews and a draggable waveform excerpt selector. Play only the selected segment; create/delete/edit multiple excerpts per track.
3. **Adjust** small bounded settings: mood/color profile, grading intensity, portrait background mode, title, zoom on/off/intensity, grain on/off, waveform bars on/off, progress bar on/off, excerpt boundaries, optional fades. Support apply-to-track and reset-to-default.
4. **Render** after a summary and explicit confirmation. Output full compilation, portrait Shorts, thumbnails, metadata, validation report.

## Default design
- Full compilation: 1920x1080, 30 fps, one album image, current title, small audio-reactive bars immediately **left of title**, thin per-track progress bar, very slow continuous zoom/pan and subtle optional grain. Keep compilation color consistent.
- Shorts: 1080x1920, same artwork with blurred fill and uncropped foreground image by default; track-specific subtle mood color grade; same title/bars/progress. Do not require separately generated images.
- Previews: instant still at reduced size; optional 3–5-second low-resolution motion preview on demand. Waveform audition plays original track segment in browser; it is not a video render.
- Target exports use the project-local contract: album MP4 under `output/album/`, individual full-track MP4s under `output/tracks/`, later Shorts under `output/shorts/`, and publishing/render artifacts under `output/metadata/`. WU3A owns album/track MP4s, chapters and render report; WU5 owns approved publishing content; WU6 owns Shorts; upload state remains future work. See Doc 38 Section 6.1.

## Non-goals
No DAW, audio mastering, multi-track video timeline, arbitrary compositing, generative AI, cloud upload, direct YouTube auth, auto-posting, batch album rendering, track reordering in editor, full story scene generation, A/B version handling, or advanced color grading.

## Functional acceptance
- Track 5 short at 45.2–75.2 seconds uses only those 30 seconds of track 5, regardless of compilation position.
- Dragging center of selected waveform region preserves its length; resizing either edge updates boundaries; audition stops at end; no invalid/negative/out-of-bounds ranges can be saved.
- UI previews and final renders use identical resolved settings and titles, subject to preview quality/resolution differences.
- Every change is persisted in an override file; user can reopen and reproduce outputs.
- Source files never modified; render failures are reported and not marked successful.

## Work-unit allocation (v2.0)

WU3A delivers the first headless product video slice before frontend work: an explicit caller-selected album-project directory, validated album/individual-track requests, ordered audio-derived timeline, static-artwork 1920×1080 H.264/AAC MP4 export beneath `<album-project>/output/`, YouTube-compatible chapters, and a supported PowerShell entry point. The current `C:\Users\ptanz\job_search\WORLD_MUSIC\WRLD-FI\Albums\Echoes of Asia - Album 1` path is the real acceptance project, not a fixed application location. Its final gate includes that album render and human playback review. WU4 adds React Import/Review, future album-project initialization beneath configurable library roots, and waveform selection; WU5 adds metadata review/approval/export; WU6 integrates the Render UX, remaining Shorts/artifacts, and release acceptance. Advanced compilation motion/effects and full Shorts composition are not part of WU3A unless separately approved.


## v1.4 additions
Required: custom color picker in addition to mood/preset treatments; dedicated YouTube metadata review with per-compilation/per-Short title and description edits, chapter inspection, validation, and approved export. No YouTube publishing API or upload action in POC.
