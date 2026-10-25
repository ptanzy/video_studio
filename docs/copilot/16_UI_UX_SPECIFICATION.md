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
Top: track title, navigation, unsaved indicator. Main left: Short carousel and 9:16 preview with blurred background, centered full artwork, track title with compact reactive bars to its left, thin progress line. Below: entire-track waveform and draggable/resizable excerpt region. Right: color preset, intensity, title, slow zoom, film grain, bars, progress, refresh still/motion preview, apply to track. Separate track selection from Short selection. Defaults from manifest; overrides persisted separately. Explicitly label approximated previews; backend-generated previews are authoritative.

### Waveform behavior
- WaveSurfer.js Regions plugin: drag body moves region, drag edges resizes, constrained within duration. One selected region at a time, multiple saved Shorts per track. Min clip 5 seconds, max configurable per platform; initial suggested range 15–60 seconds, not a hard YouTube rule.
- Display `mm:ss.t` start/end and duration. Provide numeric time entry and keyboard nudge (0.1s; Shift+arrow 1s) as accessibility fallback.
- `Play Selection` starts at start and stops at end; Pause and Stop distinct; track switch stops playback. No need to render a video for audio audition. If browser cannot decode WAV, use a browser-compatible audio proxy without altering source.
- Saving region updates only override state, never source WAV or analyzer metadata. Backend validates finite numeric boundaries, start < end <= probed track duration, unique Short ID, and revision.
- Audio analyzer recommendations can appear as optional labeled suggested regions later; no dependency in POC.

## Screen 3: Metadata
Provide the Table/Detail publishing-metadata workflow, generated/supplied/edited/approved status, validation, chapter inspection, and save/reload behavior defined by Docs 19, 23, and 26. WU5 consumes WU3A chapter/timeline output and must not calculate a competing timeline.

## Screen 4: Render
Show output checklist, preflight validation, estimated items (not invented duration/ETA), job status, progress, cancel, error details, final artifacts and verification results. Render action uses immutable config snapshot. No success state until FFprobe/output checks pass.

WU3A supplies the pre-UI album/track export use case and verified artifacts. The React Render screen and render-job HTTP/polling/cancellation UX remain WU6; WU4 must not duplicate or prematurely expose an unapproved job API. WU5 may display WU3A-derived chapters during metadata review without recalculating them.

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
