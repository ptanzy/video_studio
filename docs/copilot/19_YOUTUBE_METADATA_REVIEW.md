# 19 — YouTube Metadata Review (v1.4 normative)

## Fourth screen and scope
App navigation: **Import → Review & Shorts → Metadata → Render & Verify**. The Metadata screen reviews *generated drafts* before final render/export, with tabs for the compilation and each Short (stable Short ID). Users can edit titles, descriptions, optional tags, and intended visibility; view the derived chapter listing; inspect unresolved placeholders and duplicate titles; and save explicit overrides. No YouTube upload, account connection, API keys, or publishing side effects in this POC.

## Proposed metadata model
The generated defaults are derived, read-only artifacts; editor overrides are independent and revisioned. Example fragment of `render_overrides.json`:

```json
{"publishing_metadata":{"compilation":{"title":"Castle Above the Fog — Full Compilation","description":"Atmospheric lo-fi...","visibility":"private"},"shorts":{"T01-S01":{"title":"Castle Above the Fog #Shorts","description":"Listen: {{compilation_url}}"}}}}
```

Omitted fields mean use generated defaults. Persist only fields actually edited. Generated metadata can be refreshed without overwriting user edits. The render/export snapshot merges defaults and overrides by stable IDs; retain both source values and provenance in diagnostics. On deleted or changed Short IDs, show orphaned overrides for explicit resolution, never silently reassign. Avoid writing manual metadata into canonical album manifest or WAV. Metadata export must match exactly what was approved.

## Chapters, links, and validation
Generate compilation chapter timestamps from **probed actual audio durations and finalized track order**, not guessed lengths or static sample text. Recompute when relevant source changes, flag stale manual chapter text and offer regeneration/confirmation. For a valid YouTube chapter list, first timestamp must be 00:00, at least three chapters, and chapters should be at least 10 seconds each; validate against the actual timeline. Titles: max 100 Unicode characters; descriptions: max 5,000 characters (platform rules should be centralized and rechecked before future API integration). Treat tag limits as separate configurable validation. Detect duplicate titles as warnings, not unconditional blockers. Validate placeholders using an allowlist; unresolved `{{compilation_url}}` may be saved as a draft but is a blocking error for a *publish-ready* export unless explicitly exported as a clearly marked draft. A POC without a known uploaded compilation URL must not invent one. Distinguish render preflight (may allow draft metadata) from publish-ready preflight (must resolve required fields). Default visibility: private. Do not claim royalty-free, copyright-free, or reuse licenses without evidence.

WU3A owns the authoritative probed album timeline and base YouTube-compatible chapter artifact. WU5 consumes that output for display, staleness detection, description composition, editing/approval, and publishing metadata export; it must not maintain a competing duration/offset calculation. Doc 38 Decision 4 approves WU3A's whole-second flooring, UTF-8/LF chapter artifact, and deferral of MP4 chapter embedding.

Publishing metadata is portable album-project content. Where it references local generated artifacts, use project-relative references beneath `output/`; do not persist a Windows drive, username, configurable library-root prefix, channel-root prefix, or development-repository location. Public YouTube text must not expose local filesystem paths at all.

WU5's export path is `output/metadata/youtube_metadata.json`. The authoritative editable source is revisioned publishing override/editor state layered over supplied/generated drafts by stable target ID; users may edit and approve it before rendering finishes. The JSON file is the authoritative approved materialization for downstream publishing, covering album, individual-track, and Short targets with revision/fingerprint, provenance, approval state, titles, descriptions, keyword tags, hashtags, thumbnail/artifact references, chapters, channel/artist settings, related-video placeholders, pinned-comment text, and applicable publishing settings. Only later metadata workflows may read or update this contract. WU3A does not open it for staleness detection or any other purpose; WU5 performs explicit reconciliation from WU3A's independently consumable chapters and render report. The inspected root-level `youtube_metadata.json` is legacy/draft import material and is neither read nor changed by WU3A.

`output/metadata/youtube_publish_state.json` is not content metadata. A future uploader owns platform IDs, URLs, upload attempts/status and history there; WU3A/WU5/WU6 do not create a placeholder or claim upload state.

## API boundary and component map
- React: `MetadataReviewPage`, `MetadataTargetTabs`, `VideoMetadataEditor`, `ChapterPreview`, `MetadataValidationPanel`, `MetadataSaveBar`.
- FastAPI application use cases: `GenerateMetadataDraft`, `ValidateMetadata`, `SaveMetadataOverrides`, `ExportApprovedMetadata`.
- Proposed endpoints (confirm in WU0, version under `/api/v1`): `GET /albums/{album_id}/metadata/draft`, `PUT /albums/{album_id}/metadata/overrides` with expected revision, `POST /albums/{album_id}/metadata/validate`, `GET /jobs/{job_id}/metadata/export`.
- Optimistic concurrency: stale revision returns 409 with no overwrite. Schema failures return structured 422. Do not expose arbitrary local paths to browser clients. Keep business logic outside FastAPI and React.

## UX acceptance and tests
- Tab navigation and keyboard access across compilation and all Shorts; preserve unsaved state and warn before leaving.
- Show character counts and actionable inline validation; title/description preview of first lines; no fake upload claims.
- Edits to one Short cannot affect another. Saving/reloading and regenerating drafts preserve explicit edits.
- Correct chapter offsets after reordering/changing source durations; correct Short metadata keyed by stable IDs.
- Rendered export `.txt`/`.json`/optional `.csv` contains approved metadata and UTF-8 text; validate escaping, Unicode, CSV formula injection protection, and deterministic output.
- Unresolved placeholders, duplicate titles, overlength fields, stale revisions, missing Shorts and failed export are covered by unit/API/UI/E2E tests.


## v1.5 batch mode
Follow `23_BATCH_METADATA_EDITOR.md`: Table/Detail toggle, multi-select, bounded bulk edits, dirty state, per-row validation, safe revisioned saves. Detail view owns long-form description and chapter editing; table owns quick batch review.

## v1.6 metadata generation override
The v1.6 `26_DESCRIPTION_GENERATION.md` is normative for draft source precedence, chapter generation, manual override preservation, explicit approval, and validation. `publishing_source.description` is optional; template generation must work offline. No fabricated URLs, licenses or rights claims.
