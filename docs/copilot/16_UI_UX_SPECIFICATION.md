# 16 — UI/UX Specification (v1.3)

**Authority:** `docs/ui/index.html` demonstrates layout and limited local interactions; it is a design reference, **not production source**. Screenshots under `docs/ui/` are visual acceptance references, not exact pixel goldens. Implement in React/TypeScript in the assigned later work units.

## Layout / visual system
- Desktop-first, dark neutral UI; application background `#0b1018`, side navigation `#101824`, panels `#151f2d`, borders `#2a3648`, text `#e9eff9`, secondary text `#92a4bd`, accent `#4679ec`.
- 225px desktop sidebar, main area max-width ~1620px with 24–30px gutters; panels 12px radius, 18px padding; spacing scale 4/8/12/16/24px.
- Primary button reserved for next step/render; other actions secondary. Distinguish pending/failed/completed/verified with text and icons, not color alone.
- Keyboard navigation, visible focus rings, semantic buttons and labels; contrast should meet WCAG AA. Never rely on hover-only controls.
- At widths under ~1050px, stack Review inspector below preview; under ~650px, use top navigation and horizontal Short selector rail. On mobile, waveform controls must remain touch usable.

## Screen 1: Import
Left: server-approved album-project selector plus the future create-project workflow beneath configured/selectable music-library roots and channels, validation, and ordered tracks with portable project-relative paths/durations. Right: cover artwork and validation summary. Disable Continue until project/manifest/media validation succeeds. Display actionable errors (missing WAV, invalid schema, duplicate ID, unsupported image, missing FFmpeg, project-boundary escape). Do not claim a browser folder picker can read arbitrary server paths: use trusted backend project registration/selection. Do not hardcode the current library root/channel, and do not allow the UI to redirect final artifacts outside the selected project's `output/`.

## Screen 2: Review
Top: track title, navigation, unsaved indicator. Main left: Short carousel and 9:16 preview with blurred background, centered full artwork, track title with compact reactive bars to its left, thin progress line. Below: entire-track waveform and draggable/resizable excerpt region. Right: color preset/intensity plus WU3B pan/zoom, amplitude bars, and track-progress controls; selecting an effect reveals only its approved bounded fields. Refresh still/motion preview and apply-to-track remain explicit actions. Separate track selection from Short selection. Defaults come from the project contract and complete resolved settings are persisted through the approved revisioned state path. Explicitly label approximated previews; backend-generated previews are authoritative. Film grain, generated/separate title layers, title-aware camera/fades, parallax, atmospheric effects, and composition depth are WU7 rather than WU3B/WU4.

### Waveform behavior
- WaveSurfer.js Regions plugin: drag body moves region, drag edges resizes, constrained within duration. One selected region at a time, multiple saved Shorts per track. Min clip 5 seconds, max configurable per platform; initial suggested range 15–60 seconds, not a hard YouTube rule.
- Display `mm:ss.t` start/end and duration. Provide numeric time entry and keyboard nudge (0.1s; Shift+arrow 1s) as accessibility fallback.
- `Play Selection` starts at start and stops at end; Pause and Stop distinct; track switch stops playback. No need to render a video for audio audition. If browser cannot decode WAV, use a browser-compatible audio proxy without altering source.
- Saving region updates only override state, never source WAV or analyzer metadata. Backend validates finite numeric boundaries, start < end <= probed track duration, unique Short ID, and revision.
- Audio analyzer recommendations can appear as optional labeled suggested regions later; no dependency in POC.

## Screen 3: Metadata
Provide the Table/Detail publishing-metadata workflow, generated/supplied/edited/approved status, validation, chapter inspection, and save/reload behavior defined by Docs 19, 23, and 26. WU5 consumes WU3A chapter/timeline output and must not calculate a competing timeline.

## Screen 4: Render
Show output checklist, preflight validation, job state, current WU3A rendering phase, a phase-specific progress bar when measurable, current/total tracks, processed/total duration where available, elapsed time, reliable ETA only, cancellation controls, error and private-diagnostic information, final artifacts/verification results, MP4 location and an open action. Support queued, running, completed, failed, and cancelled states; reconnect to existing jobs; and monitor multiple queued jobs. Overall progress is shown only if a future reliable backend measurement is approved—never derive weighted percentages in the UI. Render action uses an immutable config snapshot. No success state until probing, complete decode, publication, and persistence pass.

WU3A supplies the pre-UI album/track export use case, verified artifacts, and `wrld-render-progress/1.0`. The React Render screen and render-job HTTP/polling/cancellation UX remain WU6 and must consume that same model through application APIs/events; WU4 must not duplicate or prematurely expose an unapproved job API. WU5 may display WU3A-derived chapters during metadata review without recalculating them.

WU3B supplies the v2 effect request and temporary motion-preview use case after contract approval. WU4 may expose them through separately approved typed API models; it must not construct an alternate filter graph in React. WU6 shows the chosen profile/effects during preflight and keeps the rendered track-progress overlay distinct from job progress. WU7's advanced composition editor is a later planned screen/capability, not part of the current four-screen implementation.

## State and feedback
- Persistent state: album ID, selected track ID, selected Short ID, overrides revision. Transient: playback position, open panel, local unsaved form state.
- Dirty state visible; navigating away prompts Save/Discard; 409 conflict prompts Reload/Compare rather than overwriting silently.
- Loading skeletons and error retry for previews; cancel stale preview requests; cache by source content identity and visual settings.
- Apply-to-track must preview count of affected Shorts and require confirmation.

## Accessibility/testable acceptance
- All four screens navigable by keyboard; forms have accessible labels.
- Waveform selected excerpt can be changed without dragging using numeric inputs.
- Save/reload preserves timestamps and color; stale revision rejected; switching track stops playback; Short end boundary stops playback within 0.15s browser timing tolerance (mocked clock test plus E2E).
- UI never labels a fake render or fake media as verified. Mockup-only controls are replaced with real API actions or disabled with explanation.


## v1.4 UI changes (normative)
Add **Metadata** between Review and Render. Review color editor now includes Auto / Preset / Custom modes, native color picker, HEX input, intensity, Reset to Mood, and effective-color swatch. See docs 18 and 19 for exact behaviors. Render preflight distinguishes video-render blockers from publish-ready metadata blockers; draft metadata may be exported as draft but never labeled publish-ready.
