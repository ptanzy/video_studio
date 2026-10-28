> **v1.3 authoritative override:** React + TypeScript + Vite + Tailwind + WaveSurfer.js frontend; FastAPI backend; docs live in `docs/copilot/`. Any earlier Streamlit or Python-only UI guidance in this document is superseded by `15_FRONTEND_ARCHITECTURE.md`, `16_UI_UX_SPECIFICATION.md`, and `17_UI_WIREFRAMES.md`. Do not implement Streamlit.

# UI, carousel, waveform and preview specification

## Four-screen target and work-unit ownership
**Import:** select an existing server-approved album project or use the future initialization workflow to create one beneath a configured/selectable music-library root and channel; then choose/adapt its manifest, WAVs and artwork. Display validation errors, ordered list, duration summary, and Short counts. Do not expose arbitrary server-path entry in the browser and do not make the current drive, username, `WORLD_MUSIC`, `WRLD-FI`, or album name a fixed UI default. No full render.

**Review:** carousel across tracks with a second selector for the current track's Shorts; portrait preview on one side, compact bounded controls on the other. Provide current Short index, add/duplicate/delete Short, apply profile to all Shorts in current track, revert changes, save. Changes persist to overrides atomically.

**Metadata:** inspect and edit compilation and per-Short publishing text, chapter data, validation and approval state as defined by Docs 19 and 26.

**Render:** summary of tracks, Shorts, overrides, missing inputs, estimated outputs, chosen output directory. `Validate` / `Preview` / `Render All` distinct actions; no accidental full render from editing. Show progress, errors, cancellation policy, output links/paths.

## Waveform region selector (must-have)
- Use actual track audio, not compilation MP4. Display a downsampled peak waveform and a region representing `[start_seconds,end_seconds]`.
- Drag body moves window preserving length; drag handles adjusts either edge; keyboard and numeric input allow >=0.1 s precision; keyboard nudges are accessible.
- `Play Selection` starts at selected start and **stops at end** (including after seek/drag); `Pause`, `Replay`, and time readout. Browser autoplay requires user click. Selecting another track stops current audio and releases prior resources.
- Region changes are sent to the backend only on drag end/debounce, avoiding a network request on every pixel. React rerenders must preserve playback/selection state appropriately.
- Add multiple selections per track; IDs stable across saves; selection defaults to 30 s if enough duration; prohibit selection beyond duration; short clips handle gracefully.
- Preview optional fade-in/out without destructively changing source; final render applies same fades if configured. Audio preview must use the chosen excerpt, not simply seek-and-play without a stop boundary.
- Later analyzer highlight markers are a future extension; do not require analyzer for POC.

## Preview fidelity
- Static frame: generate with actual artwork, selected crop/blur, mood grade, title, waveform representative state, progress state. Fast resolution ~360x640 for Shorts.
- Motion preview: on-demand 3–5 s low-res MP4 from the selected segment, using shared FFmpeg filters; do not pre-render all Shorts.
- Reactive bars should respond to track amplitude; may use precomputed envelope for previews and final rendering. They sit immediately left of track title; do not overlay title or exceed safe text margins.
- `slow_zoom` for compilation must remain continuous across track boundaries; Shorts motion is independent. Preserve aspect ratio; portrait default uses blurred background plus sharp centered original image.
- Long titles wrap/shrink safely; preview layout should be visually consistent with final output.

## State lifecycle
Import -> validate -> probe -> cache thumbnails/waveform envelopes -> review -> save overrides -> dry-run -> render -> verify. Cache keys include input fingerprint + relevant settings. Never store giant audio arrays in manifest or browser state.


## v1.4 four-screen flow
Import → Review → **Metadata** → Render. Review adds custom HEX color picker; Metadata provides compilation and per-Short title/description editing, chapter inspection, link-placeholder checks and save/reload. See 18–19 and updated ui-reference HTML.

## v2.2 roadmap allocation

WU3A delivers headless static album/track MP4 generation and the authoritative audio timeline before frontend work, with acceptance still independently pending. After its exact contract gate, WU3B adds production-path flat-image motion, amplitude/RMS bars, rendered track progress, and a private bounded temporary MP4 preview use case. WU4 implements Import/Review and exposes the approved WU3B effect controls and motion preview; WU5 implements Metadata and consumes shared chapter data; WU6 implements the Render screen plus integrated job HTTP behavior and remaining Shorts/artifacts. WU7 owns layered/title-aware/atmospheric composition and its dedicated editor. Earlier preview examples do not authorize low-resolution divergence, title generation, frequency-spectrum claims, or persistent preview artifacts contrary to Doc 39.
