# 22 — v1.5 Preview Pipeline and Color Regression (normative)

## Two-tier preview contract
1. **Interactive proxy**: browser CSS/canvas overlay responds immediately to picker, HEX and intensity input. It is explicitly labeled **Approximate preview**. Never imply browser color compositing is identical to FFmpeg output. No requirement to add WebGL in POC.
2. **Authoritative still**: debounce changes (e.g. 250–400 ms) and request a low-resolution server-rendered frame using the exact FFmpeg transform builder that final output uses. Cache by artwork hash + visual settings + frame time + transform version; cancel/ignore stale responses via request token. Label **Rendered preview** and show loading/error state.
3. **Motion confirmation**: on demand, request a short low-resolution encoded preview using the same transform builder; never automatically render every Short in full.
4. The preview cache is disposable and must not be mistaken for a final artifact.

## Color contract
- Input is sRGB 6-digit HEX plus bounded blend intensity and an explicit transform mode. The canonical backend maps these into a deterministic filter graph and documents filter ordering relative to blur, foreground, overlays, grain, and zoom.
- POC required codec is H.264/AAC. ProRes is **not** a required deliverable; optional cross-codec tests only if supported by local FFmpeg. Record encoder, pixel format, color metadata and FFmpeg version in report.
- Visual golden tests compare **decoded** frames at fixed timestamps, fixed test artwork and fixed filter parameters in a defined comparison space (e.g. RGB after conversion), with declared MAE/per-channel tolerance and perceptual check. Do not compare MP4 file hashes. Exclude dynamic grain or freeze its seed for comparison. Test both foreground and blurred background tint.
- Negative tests: malformed HEX, intensity out of range, stale preview response, unknown mood fallback, unsupported encoder, non-deterministic grain and color-space mismatch.

## Acceptance
- Picker change updates approximate preview promptly; authoritative preview eventually matches the persisted backend treatment and final render within documented tolerance.
- A failed preview never overwrites approved settings; the UI can still display last confirmed preview with a clear stale indicator.

## WU3A boundary

WU3A does not make this color-treatment pipeline a prerequisite for basic album and individual-track export. Under approved Doc 38 Decisions 3 and 8, WU3A's baseline visual operation is deterministic orientation/contain/pad of the selected static background, with no generated text or creative transform. Tests for that profile compare decoded output geometry and source-image presentation; this document's color-regression requirements apply only when a later approved render profile actually selects those transforms.
