# 43 — Integrated UI flow, dialogs and component mapping

**Purpose:** Extend, not replace, Doc 17 wireframes and `docs/ui/index.html`. This is a design inventory, not an instruction to implement all components in WU4. Maintain the four existing navigation destinations.

## Shell / Project Library

Project selector with the current trusted project, search/filter and one active workspace. Projects may be empty, manifestless or not yet renderable. When manifest enrichment exists, show its album/channel/track identity separately from registry identity. Future multi-select is for batch actions only. Show inventory, manifest-enrichment, composition, metadata and render status only when backed by a real service; otherwise label them unavailable.

## Import screen

1. Select a directory beneath a server-configured trusted root and register it as the project boundary. The browser never supplies an arbitrary absolute server path.
2. Run bounded recursive discovery; display project-relative assets, counts, diagnostics, capability status and Rescan. Registration succeeds for safe empty, manifestless, audio-only or image-only projects.
3. If a recognized manifest exists, display normalized album/track enrichment and validation without changing the source. Import does not assign images to tracks, choose backgrounds, judge aesthetics, or infer canonical identity from filenames.
4. Exclude or restore discovered assets, then open the project in Review through the project-level v2 handoff. Workflow selection, album ordering, Singles and Shorts belong to Review/Creation. Do not claim compilation, layered or video rendering that the backend cannot perform.
5. Keep demonstration mode explicit. A real backend error remains visible and cannot silently switch the workspace to mock data.

## Review screen

- Preserve Doc 17 preview/carousel/waveform/right-inspector composition. Default selector shows one primary Short; advanced control exposes additional stable-ID Shorts without deleting multi-Short capability.
- Suggested alternatives appear near waveform with source/provenance and a **Use this range** action; replacement is a draft edit, not a new Short or approval. Numeric and keyboard controls remain fully available.
- Controls are inline; **Approve Short** is distinct from draft save, preview and render. Show Inherited/Overridden and Reset for settings. Background type and artwork selection belong here, under the approved trusted-resource/editor contract. A future solid-color source may become a valid draft choice only through an approved additive source contract and must remain non-renderable until an authoritative profile supports it; the current null image dependency is an incomplete draft, not a solid/black background. Imported video selection is a WU8 capability, not a WU4 control.
- Approximate live preview has visible approximation labeling; **Render Preview** uses bounded authoritative backend FFmpeg excerpt and has loading/error/release states.
- **Visual Source Wizard** (future): Step 1 Source (image/MP4/multiple clips); Step 2 Timing (fit/loop/trim/freeze/custom; independent audio/video ranges); Step 3 Effects (inherit/custom/none, each independently togglable); Step 4 Review and confirm. When multiple clips: reorder list, select clip, choose transition default and per-boundary override. Never claim browser-only playback is pixel-identical to output.
- If preview needs more room, use a large/full-screen workspace. Keep unsaved draft when stepping Back; cancellation discards only the wizard draft, not previously saved project edits.

### Phase 4 composition/template distinction

Revised Doc 50 supersedes the earlier shared-template authoring model for Creation v4. The future **Composition Editor** edits the selected Album, Single, or Short's owned `visual_configuration`; ordinary edits never mutate a reusable preset or another composition and therefore require no shared-consumer warning. **Apply Template** copies a complete preset into the composition, while **Save Composition** persists only that composition.

The future **Template Library** separately owns Create/Rename/Ungroup/Delete Family, Current Type Only preset editing, All Three Types preset synchronization, Update Template, Save as New Template, standalone preset management, and user-confirmed legacy cleanup. Template provenance is historical and may outlive the preset. Phase 4A provides the v4 contract and blocks the current frontend from editing v4; Phase 4B owns these UI surfaces. WU6 renderer admission remains separate.

## Metadata screen

Retain Doc 23 Table/Detail editor and Doc 19 chapter/validation. Drafts generated from trusted source data on import once WU5 exists. Filter by draft/edited/approved/stale; support inline edit, bulk approve with impact confirmation, manual override preservation, and explicit export. Separate canonical facts from publishing text. No automatic upload.

## Render screen

Retain Doc 16/30 preflight and job-progress UI. Add future queue table for album/track/Short selections with deduplicated plan, output profile, status, retry, cancellation, optional pause-between-jobs and verified reuse indicator. Show exact output profile, selected effects, resolved identity and location. Do not equate video-overlay progress with backend job progress. Export and publishing remain distinct.

## Reusable component concepts (proposed names only)

`ProjectLibrarySelector`, `AlbumDefaultsDialog`, `GenrePresetPicker`, `InheritedSettingControl`, `PrimaryShortEditor`, `SuggestedRegionChoices`, `ShortApprovalStatus`, `VisualResourcePicker`, `VisualSourceWizard`, `ClipPlaylistEditor`, `ClipTransitionControl`, `VideoTimingControl`, `ApproximateCompositionPreview`, `RenderedExcerptPreview`, `MetadataApprovalToolbar`, `BatchSelectionSummary`, `RenderQueueTable`.

Names are descriptive, not approved code paths. Do not create duplicate components where Doc 17's component inventory already covers the function.

## UX testing matrix (future implementation gates)

- Wizard Back/Cancel, focus trap, accessible step progression, project-boundary error, no nested modals.
- After the owning contracts are approved: genre preset applied to new album only; inherited values update safely; explicit overrides survive reimport.
- Primary Short suggestion and alternate replacement; waveform selection playback stop; no approval from edit/save.
- Preview approximation label versus FFmpeg-verified clip; stale requests cancelled/released.
- Visual MP4 speed-fit math, source audio exclusion, extreme-ratio warning, clip sequencing/transition timing when renderer supports them.
- Batch selection deduplication, collision detection, verified-only reuse, approval states and queue reconnection when queue is implemented.

## WU4 truth-in-UI constraints

- WU4 may render the four-route shell, but Metadata and Render must be labeled unavailable/pending until WU5 and WU6. Do not display fake actionable controls.
- Initial WU4 uses explicit Save and a dirty indicator; local undo/redo is separate from saved revision history. Autosave controls are deferred.
- Genre presets, visual-source wizard, clip playlist, MP4 timing, metadata generation and batch queue are design references until their owning units implement them.
- Legacy `docs/ui/import.png`, `review.png` and `render.png` illustrate earlier UI thinking, not the latest approved interaction behavior; the prototype is not production code.
- Phase 2A is an evolving production-intended candidate. Reuse its shell, Import/Review components, WaveSurfer integration and tests; isolate temporary adapters instead of rebuilding a parallel frontend.
- Distinguish `discovered`, `probed`, `auditionable`, `thumbnailable`, `previewable` and `renderable` capabilities. Never infer one from another.

## v2.7 implemented-candidate UI delta

- Import now presents **My Projects**, **Add Folder**, **Music Locations**, **Project Media**, **Scan for Files** and conditional **Locate Missing Folder** language while preserving trusted-root enforcement.
- Import asset filters are Included | Excluded | All plus media kind and path search. Exclude/Restore never deletes or moves source files.
- Opening a project creates the project-level v2 session handoff and Review loads every present non-excluded asset. The v1 workflow/ordered-audio handoff remains a compatibility type only.
- Review subnavigation is Media | Creation | Editor. Creation provides the responsive Albums | Singles | Shorts planning grid, stable draft instances, duplicate occurrence warnings/acknowledgment, archive/restore, editable Short ranges, explicit Save and local undo/redo.
- Suggest Shorts, Find Highlights and Explain This Selection remain visibly unavailable until evidence-backed analyzer observations exist. They do not generate fallback claims.

### Post-audit correction delta

- Creation and Editor register their real document dirty state with one shell guard. Review-tab, project and route changes offer Save, Discard and Cancel; a failed or conflicted save does not continue navigation.
- Editor range/effect/approval changes are stored in the same revisioned Creation document shown by Creation. Demonstration Editor changes are explicitly session-only.
- Missing and changed dependencies identify the asset path and dependent draft. Missing assets route to Import relinking; changed fingerprints require an explicit acceptance action and invalidate prior approvals.
- Multi-draft checkboxes archive every active instance (with confirmation for protected work) and restore existing identities before creating new drafts. Duplicate navigation is scoped to occurrences in the current album plan.
- Short controls clamp to source bounds, use the complete recording for sources shorter than five seconds, and keep waveform editing keyboard-accessible.
- Audio/image actions are rendered only for the relevant supported capability. Imported video remains visible as discovery-only WU8 input.
