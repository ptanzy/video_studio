# 17 — Wireframes, Component Inventory, and Copilot Mapping

## Visual assets
- `docs/ui/index.html`: open locally in a browser; use the left nav for the four-screen Import / Review / Metadata / Render reference. Review supports sample Short navigation, approximate color/title changes, draggable region, and demonstration buttons. No audio or FFmpeg runs.
- `docs/ui/import.png`, `docs/ui/review.png`, and `docs/ui/render.png`: checked-in reference screenshots. The interactive prototype also demonstrates Metadata; the prototype and screenshots are not application source or executable acceptance evidence.

## Desktop wireframes

### Import
```
┌──────────────┬───────────────────────────────────────────────────────────────┐
│ WRLD STUDIO  │ Import album                                     LOCAL        │
│ Import       │ ┌─────────────────────────────┬─────────────────────────────┐ │
│ Review       │ │ Choose folder/manifest      │ Cover artwork               │ │
│ Metadata     │ │ Validation results          │ File/metadata health        │ │
│ Render       │ │ Ordered WAV track list      │ Continue to Review          │ │
│              │ └─────────────────────────────┴─────────────────────────────┘ │
└──────────────┴───────────────────────────────────────────────────────────────┘
```
### Review
```
┌──────────────┬───────────────────────────────────────────────────────────────┐
│ WRLD STUDIO  │ Review Shorts · Track n/m                                      │
│ Import       │ ┌───────────────────────────────────────┬───────────────────┐ │
│ Review       │ │ [Short rail] [9:16 preview]           │ Color preset      │ │
│ Metadata     │ │                                       │ Intensity         │ │
│ Render       │ ├───────────────────────────────────────┤ Title             │ │
│              │ │ Whole-track waveform                 │ Zoom / grain      │ │
│              │ │ [==== selected excerpt ====]         │ Bars / progress   │ │
│              │ │ Play / Stop / Reset / Save            │ Refresh preview   │ │
│              │ └───────────────────────────────────────┴───────────────────┘ │
└──────────────┴───────────────────────────────────────────────────────────────┘
```
### Render
```
┌──────────────┬───────────────────────────────────────────────────────────────┐
│ WRLD STUDIO  │ Render & verify                                               │
│ Import       │ ┌─────────────────────────────┬─────────────────────────────┐ │
│ Review       │ │ Compilation job             │ Preflight checks            │ │
│ Metadata     │ │ Shorts job                  │ Output directory           │ │
│ Render       │ │ Thumbnails + metadata       │ Errors / verification      │ │
│              │ │ Render All / Cancel         │                             │ │
│              │ └─────────────────────────────┴─────────────────────────────┘ │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

## Component mapping
- `AppShell`: sidebar/top nav, route and global job indicator.
- `ImportPage`: `AlbumSourcePicker`, `TrackList`, `ArtworkCard`, `ValidationSummary`.
- `ReviewPage`: `TrackNavigator`, `ShortCarousel`, `ShortArtworkPreview`, `WaveformSelector`, `VisualSettingsPanel`, `SaveBar`.
- `RenderPage`: `PreflightChecklist`, `RenderQueue`, `JobProgress`, `OutputArtifacts`, `VerificationSummary`.
- Shared: `ErrorBanner`, `StatusBadge`, `ConfirmDialog`, `UnsavedChangesPrompt`, `LoadingSkeleton`.

## Implementation order
1. Static React shell matching screenshots; navigation and accessible forms, mocked fixtures.
2. Typed API adapter and validation/import screen.
3. WaveSurfer region + real audio audition, boundary tests.
4. Overrides state and optimistic concurrency.
5. Preview endpoints and visual controls, still first, motion second.
6. Render jobs, progress, cancellation and output verification.

Roadmap allocation: WU3A implements the headless album/track renderer before these UI steps. WU4 covers Import/Review and waveform interaction; WU5 covers Metadata; WU6 implements step 6 and integrates remaining Shorts/artifacts. The prototype never substitutes for WU3A real-video or human-playback acceptance.

The WU4 Import implementation must select a server-approved album project and later support project creation beneath configurable/selectable music-library roots and channels. The browser never submits an arbitrary server filesystem path. WU6 shows artifacts from the selected project's `output/`; this portability/security behavior takes precedence over any fixed paths implied by the static mockups.

## Tests
- Vitest + React Testing Library: navigation, state transitions, color/short overrides, validation errors, 409 conflicts, keyboard time controls.
- Playwright: import valid fixture, navigate Shorts, drag and resize selection, audition with test WAV, save/reload, request render, verify statuses. Mock heavy render in most E2E tests; one opt-in real FFmpeg smoke test.
- Accessibility: automated axe checks plus keyboard walkthrough. Screenshot comparisons use tolerant region-based baselines, not brittle full-frame pixel equality.


## v1.4 fourth-screen wireframe
```text
┌──────────────┬───────────────────────────────────────────────────────────────┐
│ WRLD STUDIO  │ Metadata review                                               │
│ Import       │ [ Compilation ] [ Short 01 ] [ Short 02 ] ...                  │
│ Review       │ ┌──────────────────────────────┬────────────────────────────┐ │
│ Metadata     │ │ Title [___________________]  │ Live YouTube text preview  │ │
│ Render       │ │ 65/100                       │ Validation warnings        │ │
│              │ │ Description [____________]   │ Generated chapter list     │ │
│              │ │ [________________________]   │ Missing-link placeholders  │ │
│              │ │ Visibility [Private v]       │                            │ │
│              │ │ Save · Regenerate defaults   │ Continue to Render         │ │
│              │ └──────────────────────────────┴────────────────────────────┘ │
└──────────────┴───────────────────────────────────────────────────────────────┘
```
Color inspector: `[Auto | Preset | Custom]` → swatches or `[color picker] [#HEX input]` → intensity slider → Reset to Mood. Updated visual references are in `docs/ui/`; docs 18–20 control behavior and testing.


## v1.5 update
`23_BATCH_METADATA_EDITOR.md` defines the authoritative Metadata **Table/Detail** layout and bulk operations. `docs/ui/index.html` demonstrates Table/Detail switching and an end-to-end simulated walkthrough. It is not a functioning renderer, persistence layer, or upload client. `22_PREVIEW_AND_COLOR_REGRESSION.md` distinguishes approximate instant color feedback from authoritative server-rendered confirmation. See `21` for standardized errors.

## v1.6 UI additions
On Import, add a compact normalization/validation review with source field, resolved field, source/provenance, severity and fallback. On Review, show resolved swatch and `why this color` explanation with custom HEX and reset. On Metadata, display generated/supplied/edited/approved badges and explicit approval, with chapter stale warnings and bulk edits. All design images and interactive reference now live under `docs/ui/`.

## v1.7 wireframe extension — comparison and batch validation
Review: `[Original | Split | Treated]` above the same-frame artwork comparison, keyboard-accessible divider, `Approximate`/`Authoritative` preview status, and refresh/error indicator. Metadata: `[Select] [ID] [Title + count/status] [Description + count/status] [Tags status] [Visibility] [Approval]`; per-row inline errors and aggregate invalid count; selected-row bulk toolbar; detailed editor for long descriptions. See 27 for interactions and tests.
