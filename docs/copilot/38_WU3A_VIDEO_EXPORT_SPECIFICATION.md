# 38 — WU3A Video Export Specification

**Roadmap successor (v2.2):** WU3A's contracts and acceptance criteria below remain unchanged. WU3A has an implementation candidate but remains **IMPLEMENTED — ACCEPTANCE PENDING**. Doc 39 places WU3B next, before WU4, while tracking WU3A's real-album and human-playback acceptance independently.

**Status:** all eight WU3A contract decisions are approved and an implementation candidate is present. **Final WU3A acceptance is pending** the real *Echoes of Asia* album render, one full-track render, automated probe/full-decode evidence, and human playback review. WU3A's historical position remains after WU3; Doc 39 controls successor sequencing.

## 1. Authority and historical boundary

This document is the specific forward authority for WU3A and for responsibilities transferred from WU4–WU6. It supplements the authority rules in Doc 31 and the roadmap in Doc 32. It does not rewrite completed history:

- WU1 implemented foundations, narrow structural manifest validation, identity checks, revisioned storage, and typed errors.
- WU2 implemented reusable media-process and single-worker job infrastructure plus a synthetic proof. It did **not** implement album or track export.
- WU3 implemented authoritative still-image/color-preview infrastructure and its backend HTTP boundary. It did **not** implement MP4 video export.
- No full album MP4 has yet passed automated end-to-end verification and human playback acceptance through the current application.

Where older documents assign full compilation to WU2, motion/final video to WU3, or defer all real video generation to WU6, the allocation in this document controls. Product behavior not explicitly transferred remains in its existing later work unit.

## 2. Objective

WU3A delivers a headless, real video-export vertical slice before more frontend work. It must accept an explicit album-project directory, render playable MP4 files from validated local WAV and artwork inputs inside that boundary, publish beneath that project's `output/`, expose a supported ordinary-PowerShell entry point, derive the album timeline and YouTube chapter data, and reuse the established WU2/WU3 safety boundaries. It must not depend on the development repository's location or a fixed drive, username, music-library root, channel, or album name.

Passing mocked or synthetic-only tests is insufficient. Final WU3A acceptance requires a complete *Echoes of Asia* album render, automated verification, decode through the end, and documented human playback review.

## 3. Dependencies and reuse requirements

WU3A depends on accepted WU1–WU3 contracts and must reuse rather than fork:

- WU1 canonical JSON, error, schema-test, import-boundary, and source-immutability patterns.
- WU2 `SubprocessRunner`, `MediaToolchain`, FFprobe adapter, immutable snapshots, `JsonJobRepository`, one-worker lifecycle, progress/heartbeat, cancellation, attempt-owned staging, `FilesystemArtifactStore`, verification, promotion, reconciliation, event logging, and process-tree ownership.
- WU3 `ProcessLocalRenderAdmission` and application composition rules so preview and export cannot create independent heavy-render domains.
- Docs 05, 11, 12, 21, 30, 34, 35, and 37 for media integrity, lifecycle, error, concurrency, and platform requirements.

Do not broaden `SyntheticMediaEncoder` or its opaque WU2 request. Add a separately named album/track renderer and a versioned product render contract behind application ports. Do not import, call, copy, or modify `legacy_v2`.

## 4. In scope

1. A checked-in, versioned, machine-validated input contract for album and individual-track video export.
2. An explicit adapter from supported Studio album input into an immutable render request; the existing minimal `manifest-v2` schema remains a structural subset, not a complete render request.
3. Ordered full-album audio concatenation with no crossfades and no musical processing.
4. Individual-track MP4 export using the same audio/image/output pipeline.
5. A static source image held for the complete artifact duration.
6. H.264 video, `yuv420p`, AAC audio, and `+faststart`; the existing approved production target is 1920×1080 at 30 fps.
7. Explicit, validated output settings selected only from a checked-in supported allowlist; invalid or unsupported combinations fail before job submission.
8. An exact shared timeline derived from probed/normalized audio, plus YouTube-compatible chapter metadata for albums.
9. A supported CLI or equally explicit headless programmatic entry point usable from an ordinary Windows PowerShell terminal without the frontend.
10. Unit, contract, fault-injection, real FFmpeg integration, and Windows human-acceptance evidence.
11. An explicit runtime album-project path whose canonical directory is the source-resolution/security boundary, with all final generated artifacts rooted beneath `<album-project>/output/`.

## 5. Out of scope

- React screens, WaveSurfer integration, browser audio, or render-dashboard wiring.
- YouTube upload/authentication or any network publishing side effect.
- Shorts composition or portrait-video export.
- Slow zoom/pan, grain, audio-reactive bars, progress graphics, animated backgrounds, motion previews, generated title overlays, or other advanced effects. A title already baked into the source image remains visible.
- Loudness normalization, mastering, crossfades, gap insertion, or rearrangement of source audio.
- Multi-album batching, multiple concurrent workers, distributed infrastructure, GPU requirements, or cloud storage.
- Metadata description generation and human approval UI, except the chapter artifact required by WU3A.
- Reading, validating, migrating, modifying, or generating any root-level or output `youtube_metadata.json`; publishing metadata belongs entirely to later workflows.
- Creating, moving, renaming, or relocating the primary album-project directory; library-root configuration, album initialization, selectable libraries, and multi-channel project creation belong to the future Import workflow.

## 6. Input and request contract

WU3A Phase 1 must check in and contract-test the final schema before renderer implementation. The approved semantic contract is:

- `contract_version`: required exact version discriminator.
- `target`: exactly one of album compilation or one identified track.
- Stable album identity and, for a track target, stable track identity. Filenames, titles, order, or hashes must not be invented as recording IDs.
- An explicit runtime album-project directory supplied through trusted local composition. Its canonical directory is the project/security boundary; portable manifests and publishing metadata store references relative to it rather than embedding its machine-specific absolute prefix.
- One static artwork/background reference.
- For an album target, a nonempty explicitly ordered track list; each item has stable ID, display title, and WAV reference. Order in the immutable request is authoritative.
- For a track target, exactly one track from the validated source model.
- A relative artifact path under the fixed project-local `output/` root. Exact filenames and descendants inside `output/` remain subject to the approved naming/layout policy.
- An explicit output-settings object validated against the approved WU3A allowlist.
- A chapter-generation request for album targets; individual-track targets do not fabricate multi-track chapters.

Validation must canonicalize the supplied album-project directory and reject missing/non-directory projects, traversal, absolute persisted source paths, symlink/junction/reparse or replacement escapes, duplicate IDs/order values, missing or non-regular files, unsupported/corrupt images or audio, non-finite media observations, empty track lists, unknown contract versions, unsupported output settings, source/output aliasing, and any artifact outside `<album-project>/output/`. It must preserve source data and report typed errors without echoing private paths through public adapters.

The current library convention is:

`<music-library-root>/<channel>/Albums/<album-project>/`

with the current root `C:\Users\ptanz\job_search\WORLD_MUSIC` and acceptance project `WRLD-FI\Albums\Echoes of Asia - Album 1`. This is an operational default/example only. WU3A accepts the complete album-project path directly and must work for other library roots, channels, drives, users, and computers. It must not discover the project by walking from the repository or assume `WORLD_MUSIC`, `WRLD-FI`, or `Albums` is always present.

WU3A may create approved owned directories/files beneath the existing album project's `output/` according to the lifecycle contract. It must not automatically create or relocate the primary album folder. Future configuration may supply a default library root, selectable library locations, and multiple channel roots without changing the WU3A application use case.

Section 15 Decision 1 provides the approved schema names, versions, semantic fields, and draft-adapter behavior. Examples cannot become schemas by implication.

### 6.1 Approved album-folder and output-artifact contract

The following layout is the approved cross-work-unit album/output contract. WU3A owns only the entries explicitly marked WU3A:

```text
<album-project>/
├── video_manifest.json                         # source video configuration; never render-owned
├── <source WAV and artwork paths>              # manifest-relative/project-relative source assets
└── output/                                     # generated/publishing namespace
    ├── album/
    │   └── <safe-album-title>.mp4              # WU3A
    ├── tracks/
    │   └── <NN> - <safe-track-title>.mp4       # WU3A
    ├── shorts/
    │   └── <stable-short-id>.mp4               # WU6, not WU3A
    └── metadata/
        ├── youtube_metadata.json               # WU5 authoritative approved content export
        ├── chapters.txt                        # WU3A derived timeline artifact
        ├── render_report.json                  # WU3A render-owned factual report
        └── youtube_publish_state.json           # future publisher; absent until real state exists
```

Only `output/album/`, `output/tracks/`, and `output/metadata/` are created by WU3A, and only when an approved WU3A artifact needs them. Within `output/metadata/`, WU3A creates only `chapters.txt` and `render_report.json`. It does not read or create `youtube_metadata.json`, and it does not create `youtube_publish_state.json` or `output/shorts/`. Empty output directories are neither required nor pre-created. Temporary media remains in the existing attempt-owned `FilesystemArtifactStore` staging area and is promoted into this tree only after verification; a partial file is never a final artifact.

Source locations are manifest-controlled relative paths, not mandatory fixed filenames or subfolders. The conceptual names `cover.png`, `thumbnail.png`, and `video_background.png` are roles, not discovery rules. The current *Echoes of Asia* project now contains those exact files and its manually migrated `wrld-video-album/1.0` manifest supplies the approved stable identities and exact paths. The implemented validator accepts that current state. WU3A must not fuzzy-match, rename assets, invent identity from a title, or rewrite the source manifest automatically.

All result and publishing references use `/`-separated paths relative to `<album-project>` (for example, `output/album/Echoes of Asia.mp4`) and reject `.`/`..`, empty segments, absolute/drive/UNC paths, reserved device names, and canonical containment escapes. Runtime diagnostics and immutable job records may retain resolved local paths where required for recovery, but portable manifests and publishing exports do not.

### 6.2 Metadata ownership and lifecycle contract

| File | Owner and lifecycle | WU3A behavior |
|---|---|---|
| `video_manifest.json` | Album-project source configuration created by the future Album Project Initialization workflow and explicitly edited/migrated by an approved user workflow. It identifies the album, ordered media, artwork roles, supported render defaults, and clip definitions. | Read/validate/adapt only. Never invent album identity, overwrite it, or store measured durations/results in it. |
| `output/metadata/youtube_metadata.json` | WU5's revisioned, explicitly approved publishing-content materialization. Generated defaults, user overrides, approval revision/fingerprint, and resolved artifact references remain distinguishable; the editable source remains the WU5 editor/override state described below. | Must not open, read, validate, migrate, modify, or generate it. It is not a render input and its presence or validity cannot affect WU3A. |
| `output/metadata/chapters.txt` | WU3A render-owned UTF-8 chapter artifact derived from the authoritative final audio timeline. | Generate/reuse only when its request/input fingerprint matches; never treat edited publishing prose as the timeline. |
| `output/metadata/render_report.json` | WU3A factual render result: request/job/attempt IDs, relative source/artifact references, fingerprints, settings, timeline, measured media, verification, warnings, timestamps, and renderer/tool identity. | Generate after artifact verification/promotion; no titles/descriptions/approval state are authoritative here. |
| `output/metadata/youtube_publish_state.json` | A future publishing adapter's mutable upload ledger: platform IDs/URLs, statuses, attempts, and history. It is separate from content metadata and render reports. | Do not create a placeholder, read it as render input, or imply upload success. |

The existing root-level *Echoes of Asia* `youtube_metadata.json` has draft schema `wrld-youtube-publishing/0.1-draft`. It remains source material outside WU3A. A later WU5 workflow may explicitly import it with validation/provenance and separately save `output/metadata/youtube_metadata.json`; WU3A must not open, read, validate, migrate, move, rewrite, or copy either file.

The approved WU3A JSON artifact contract and later-workflow metadata boundaries are:

- `render-report-v1.schema.json`, `schema_version: "wrld-render-report/1.0"`: atomically revisioned project artifact catalog with `project_id`, `revision`, ordered `artifacts`, job/attempt history, request/input/tool fingerprints, timeline, verification, warnings, and timestamps. It references artifacts and sources by project-relative path. A single-job `video-export-result/1.0` is merged into this catalog only after successful promotion.
- `youtube-metadata-v1.schema.json`, `schema_version: "wrld-youtube-metadata/1.0"` is a WU5 proposal, not approved or implemented by this WU3A decision record. Its intended fields remain `revision`, source/timeline fingerprints, approval record, channel/artist settings, `album_video`, ordered `track_videos`, and ordered `shorts`, with publishing content and provenance per stable target ID.
- `youtube-publish-state-v1.schema.json`, `schema_version: "wrld-youtube-publish-state/1.0"` is a future-publisher proposal, not approved or implemented by WU3A. It remains separate from both `youtube_metadata.json` and `render_report.json`.

During WU5, the authoritative editable source is the revisioned publishing override/editor state merged over supplied/generated drafts by stable target ID. Editing and approval can occur before video rendering finishes. `youtube_metadata.json` is the deterministic approved materialization of that state. WU5—not WU3A—compares its source/timeline fingerprint with independently produced `chapters.txt` and `render_report.json`, marks stale content, and performs any explicit regeneration/review/export. Future upload automation resolves approved media and thumbnails from `youtube_metadata.json` plus the verified artifact catalog in `render_report.json`, never by reverse-engineering filenames.

## 7. Audio, timeline, and chapters

- Probe every source with FFprobe before freezing the job snapshot. Never trust user-entered duration.
- Leave source WAV files unchanged. Convert job-owned temporary audio to a common 48 kHz stereo PCM representation where needed.
- Concatenate in immutable request order with no crossfades. Derive offsets from normalized sample counts, retain fractional precision internally, and use this same timeline for duration verification and chapters.
- Verify transition order with distinguishable synthetic fixtures. Cover mono/stereo and differing supported source sample rates if the approved input contract permits them.
- Generate YouTube chapter lines from final track order and derived offsets. The first timestamp is `00:00`; validate the current project rule of at least three chapters and at least 10 seconds per chapter as defined by Doc 19. Ineligible timelines retain accurate timestamps and emit a warning rather than falsifying eligibility.
- Chapter values are generated output, never authoritative input duration. Source changes invalidate the timeline and chapter artifact.
- Approved Decision 4 floors displayed chapter starts, requires deterministic UTF-8/LF text, and defers MP4 chapter embedding. Tests must lock this policy.

## 8. Static-image video rendering

- The selected image supplies every video frame for the artifact duration; no motion/effects are introduced in WU3A.
- Production output retains the approved baseline: 1920×1080, 30 fps, H.264, `yuv420p`, AAC, `+faststart`.
- RGB artwork conversion must use the BT.709 matrix and assign frame-level `colorspace=bt709`, `color_primaries=bt709`, and `color_trc=bt709` before encoding while retaining the encoder-level BT.709 options. Verification remains strict for all three FFprobe stream fields. Direct libx264 VUI parameters are not part of the profile unless a real-media regression proves the frame/filter and encoder options insufficient.
- The encoder uses argument arrays through the existing owned-process runner. No shell command construction or manual FFmpeg bypass is an application interface.
- Audio and video termination must be tested so the last track is neither truncated nor followed by an unintended material tail. AAC padding and video-frame tolerance must be measured and documented.
- Approved Decisions 2–3 define the single `youtube-1080p30-v1` profile and aspect-preserving contain/black-pad image policy. The corrected *Echoes of Asia* acceptance background is exact 1920×1080 and visibly identifies *Echoes of Asia*, subject to normal application validation of the current file.

## 9. Lifecycle, ownership, and recovery

The export use case must submit an immutable snapshot through the existing durable job lifecycle and hold the shared render-admission lease across probe/encode/validate/promote. It must:

1. Fingerprint every input and freeze request/tool/renderer identity.
2. Render only into attempt-owned same-filesystem staging.
3. Cooperatively cancel through the existing event and reap the entire owned process tree.
4. Probe the complete staged MP4, verify streams/settings/duration/provenance, and decode representative media before promotion.
5. Atomically promote only verified output beneath the selected project's `output/`; never overwrite a different validated artifact silently or publish into another album/repository.
6. Reconcile interruption using existing promotion records and snapshot identity.
7. Clean only recorded job-owned staging; never mutate or delete WAVs, artwork, manifests, unrelated output, or cache data.
8. Surface cleanup, persistence, process-ownership, timeout, disk, permission, and verification failures; never report false completion.

Album and track export share these semantics. WU3A must not create a second scheduler, repository, artifact-store convention, cancellation model, or render-admission instance.

### 9.1 Durable progress and failure diagnostics

WU3A owns two application-private versioned records: `wrld-render-progress/1.0` and `wrld-render-diagnostic/1.0`. They are stored in the OS-appropriate per-user state root partitioned by project identity, never in album output and never in publishing metadata.

The progress record uses exactly the phases in Doc 30, keeps job state separate, and records only measurable phase percentage, applicable track counts and duration, elapsed time, reliable ETA, progress/heartbeat timestamps, and failure phase/diagnostic reference. There is no weighted overall percentage. Encoding reaches 100% on FFmpeg `progress=end`; probing and complete decode are subsequent phases; completion follows verification, artifact/report publication, cleanup, and required persistence.

A failed attempt diagnostic contains job/attempt/request identity, failure phase, primary error and exact predicate/expected/actual values, sanitized FFmpeg arguments, bounded sanitized stderr, FFmpeg/FFprobe versions, relevant path-free FFprobe properties, cleanup outcome/timestamps, and failure time. Absolute source paths and publishing metadata are prohibited. Failed media is not retained. Diagnostic or cleanup failure cannot replace the authoritative primary rendering failure.

## 10. Headless entry point

Before WU3A completion, an ordinary Windows PowerShell user must be able to invoke a supported entry point from the installed/development environment regardless of repository location that:

- accepts the explicit album-project directory and approved input contract; derives the only permitted final root as `<album-project>/output/` rather than accepting an unrelated arbitrary destination;
- uses configured absolute FFmpeg/FFprobe paths or the existing supported discovery policy;
- validates and prints preflight failures before encoding;
- submits and runs/reconciles the application job rather than constructing an ad hoc FFmpeg render;
- prints job/attempt identity, status, output path, verified media summary, chapter artifact path, and actionable diagnostics;
- emits throttled non-in-place live progress and terminal outcome to stderr while reserving stdout for the existing machine-readable final JSON result;
- exits nonzero on any non-completed or unverified result.

The entry point must be a thin interface over application use cases and work without Node, React, or a running FastAPI server. Approved Decision 6 provides the exact module and arguments. WU3A final documentation must include the actual tested PowerShell command; a test-only harness is not a substitute for the supported entry point.

## 11. Automated test requirements

### Contract and unit

- Positive/negative fixtures for album and track requests, version rejection, explicit project selection, safe relative paths, project/output containment, supported settings, unique identities, and immutable ordering.
- Timeline/sample-count arithmetic, chapter formatting/eligibility/staleness, Unicode titles, and no guessed durations.
- Progress/diagnostic schema fixtures, exact phase transitions, FFmpeg end-at-100 behavior, concurrent CLI-read/worker-write safety, private path-free diagnostics, and cleanup/diagnostic failure non-masking.
- Application use-case tests with fake probe/encoder/repository/artifact ports.
- Album/track plan validation, idempotent digest changes, source mutation, cancellation, retry, recovery, and collision behavior.
- Portability tests using different temporary project roots, nested directories, spaces/Unicode, drive/root conventions where available, multiple channel-like layouts, a repository location unrelated to the album, and traversal/symlink/junction/reparse escape attempts.
- Import-boundary tests: domain/application do not import FFmpeg, FastAPI, or interface modules.

### Real FFmpeg integration

- Generated 2–4 second PCM WAVs with distinguishable content and a generated image; no user music in automated CI.
- At least a tiny multi-track album and one individual-track render through the real application entry point/use case.
- Probe container, H.264/AAC codecs, `yuv420p`, dimensions, frame rate, audio presence, expected duration tolerance, provenance, and `+faststart` behavior where testable.
- Assert actual FFprobe `color_space`, `color_transfer`, and `color_primaries` are all `bt709` on the pinned Windows FFmpeg/FFprobe 9.0.2 build and the Ubuntu gate.
- Decode video and audio through EOF; verify album transition order and that the final track is present.
- Verify chapter output against the derived timeline.
- Exercise failure/cancel/recovery/promotion paths and prove no source mutation or false final.
- Windows and Ubuntu media jobs with pinned/verified tool capabilities; skips remain explicit and cannot satisfy WU3A acceptance.

## 12. Human acceptance — *Echoes of Asia*

Final acceptance uses the real local album at:

`C:\Users\ptanz\job_search\WORLD_MUSIC\WRLD-FI\Albums\Echoes of Asia - Album 1`

For this acceptance run, `C:\Users\ptanz\job_search\WORLD_MUSIC` is the current default music-library root and `WRLD-FI` is the current channel convention. The full album path must be passed explicitly. Neither prefix becomes a schema default or hardcoded discovery rule, and the promoted MP4/chapter/report artifacts must be under this album's `output/`.

Preflight must confirm the manifest-selected background and all 12 ordered WAVs. The current asset review found compatible 48 kHz stereo 16-bit PCM WAVs and an exact 1920×1080 `video_background.png`, with an expected source duration near 36:35.587. These observations must be re-probed by the implemented application; documentation values are not render inputs.

Acceptance requires:

1. Resolve the manifest/asset-name and visible artwork-title blockers without an automatic source rewrite.
2. Render the complete 12-track album and at least one individual full-track MP4 through the supported WU3A entry point outside a sandbox that blocks Windows Job Object assignment.
3. Use the manifest-selected supplied background and publish the album, track, `chapters.txt`, and `render_report.json` at the approved project-relative paths; do not create Shorts, publishing state, or unapproved publishing prose.
4. Record command, tool versions, job/attempt IDs, output paths, file sizes, elapsed time, and all test counts.
5. FFprobe each promoted MP4 and decode both streams through EOF.
6. Compare derived chapter starts with actual audible transitions and confirm track order and complete final-track audio.
7. Use an acceptance harness external to the WU3A application path to confirm source WAVs, artwork, `video_manifest.json`, and the existing root publishing draft are byte-unchanged. This preservation check does not authorize WU3A itself to open or hash `youtube_metadata.json`.
8. Exercise matching-output reuse, conflicting-output refusal, failure, cancellation, and recovery without false success or partial promotion.
9. Open the album MP4 in VLC or Windows Media Player; confirm image, audible ordered tracks, seeking near early/middle/late boundaries, resumption after seek, final-track completion, and clean termination.
10. Record the human reviewer, date, player/version, result, and any observed defects. Automated evidence alone cannot mark WU3A accepted.

The user corrected the album images. Read-only inspection on 2026-10-25 confirmed that the current manifest-selected `video_background.png` is 1920×1080 and visibly says *Echoes of Asia*. The historical *Lanterns Across Asia* mismatch is resolved, but the implemented application must still validate the selected file at acceptance time. This approval does not authorize WU3A to rename or alter source artwork.

## 13. Acceptance gate

WU3A is complete only when all of the following are true:

- The Phase 1 blocked contract decisions are approved and represented by checked-in schemas/contracts.
- Album and individual-track exports use one application pipeline and the existing WU2/WU3 lifecycle infrastructure.
- The caller can select an album project independent of repository location; all resolved sources remain inside that project and all final artifacts remain inside its `output/`.
- Contract, unit, fault-injection, complete backend regression, and real-media integration suites pass with reported counts/skips.
- Windows and Ubuntu CI media gates pass; native platform limitations are reported.
- A full *Echoes of Asia* album MP4 is successfully rendered, promoted, probed, decoded through EOF, and manually reviewed.
- At least one *Echoes of Asia* individual full-track MP4 is rendered through the same pipeline, promoted to `output/tracks/`, probed, and decoded through EOF.
- Chapter output is derived, accurate under the approved policy, and manually checked at transitions.
- Required outputs match the approved Section 6.1 layout; unused directories/files are absent, existing mismatched artifacts are not overwritten, and matching artifacts are reused only after verification.
- Source media/configuration is unchanged; external acceptance evidence confirms the root publishing draft is unchanged without WU3A reading it. WU3A creates no `youtube_metadata.json` or placeholder `youtube_publish_state.json`.
- Sources are unchanged; no `legacy_v2`, frontend, upload, Shorts, or advanced-effect scope entered WU3A.
- Documentation includes the real supported PowerShell invocation, output layout, troubleshooting, limitations, and evidence.
- Independent review finds no P0/P1 lifecycle, media-integrity, or false-success defect.

If the real album render or human review has not occurred, report **WU3A IMPLEMENTED — ACCEPTANCE PENDING**, not complete.

## 14. Effect on later work units

- **WU4 — Import and Review React workflow:** consumes WU3A album-project validation and timeline capabilities; implements project selection plus the future album-initialization workflow beneath configurable/selectable music-library roots and channels, WAV access, WaveSurfer Short selection, authoritative WU3 previews, and revisioned overrides. It does not reimplement album/track encoding, and browser payloads cannot supply arbitrary server filesystem paths.
- **WU5 — Metadata workflow:** consumes WU3A derived timeline/chapters; implements Table/Detail editing, description drafts, validation, approval, and metadata export. It may format chapters into approved descriptions but does not re-probe, recalculate a competing timeline, or persist machine-specific absolute library paths in portable publishing metadata.
- **WU6 — Integrated Render UX and release acceptance:** adds approved render-job HTTP contracts/UI, preflight/confirmation, polling/heartbeat/reconnection/cancel UX, project-local artifact presentation, full Shorts/thumbnails/metadata integration, resource profiling, packaging, and final POC end-to-end acceptance. It passes a server-approved selected project into the same WU3A use cases and does not defer first functional album/track MP4 generation or first real-album human playback until WU6.

Shorts composition and advanced compilation motion/effects remain deferred to an explicitly approved later slice. They are not silently assigned to WU3A by the existence of older product-design examples.

## 15. Approved resolution of the eight implementation decisions

The album-project boundary, `output/` root, and all eight choices below are approved requirements. Implementation is authorized for a subsequent implementation pass under the normal exact plan/report gate; this documentation pass does not add schemas or application code.

### Decision 1 — source, request, and result contracts

**Approved decision:** implement the three video contracts below plus the render-report contract defined in Section 6.2:

1. `video-manifest-v1.schema.json`, discriminator `format: "wrld-video-album/1.0"`, for `<album-project>/video_manifest.json`.
2. `video-export-request-v1.schema.json`, discriminator `contract_version: "video-export-request/1.0"`, for one requested album or track artifact.
3. `video-export-result-v1.schema.json`, discriminator `contract_version: "video-export-result/1.0"`, for the structured verified outcome.
4. `render-report-v1.schema.json`, discriminator `schema_version: "wrld-render-report/1.0"`, for the project-level artifact catalog assembled from verified results.

The source manifest requires exactly these semantic groups while allowing separately reviewed extension fields:

- `album`: stable `id`, `title`, `artist`, and `channel`.
- `visual`: required project-relative `background`; optional project-relative `cover` and `thumbnail`.
- `tracks`: nonempty ordered objects with stable `id`, unique positive `number`, `title`, and project-relative `audio`; optional stable-ID clip definitions are preserved for WU4/WU6 but ignored by WU3A rendering.
- `render`: `profile_id`, initially `youtube-1080p30-v1`.

The export request contains only `contract_version`, `target`, and `profile_id`. `target` is exactly `{"kind":"album"}` or `{"kind":"track","track_id":"..."}`. The trusted album-project path is an interface/composition argument, not serialized into the portable request. Album exports always produce the derived chapter/report artifacts; no request flag can disable verification.

The result requires `contract_version`, `job_id`, `attempt_id`, terminal `state`, normalized `target`, `request_digest`, ordered `artifacts`, `timeline` (album only), `warnings`, and timestamps. Every artifact records `kind`, project-relative `path`, SHA-256, byte size, verification state, and measured media properties where applicable. It contains no publishing prose or upload state.

Compatibility: `manifest-v2.schema.json` remains the completed WU1 structural subset and is not renamed. Historical `wrld-video-album/0.1-draft` inputs receive an explicit diagnostic adapter only; it may map exact fields but must reject missing stable IDs, nonexistent paths, or unsupported settings rather than infer them. The current *Echoes of Asia* source was manually migrated and validates as `wrld-video-album/1.0`; this does not authorize automatic migration or rewriting of another draft. Unknown draft fields are preserved in the source and never silently dropped by a rewrite.

**Rationale:** separates portable project configuration, one immutable render request, and factual results while preserving WU1/WU2 contracts. **Affected:** Docs 03, 10, 14, 21, 28, 31, 32, and 38; schemas/fixtures belong to the subsequent implementation pass.

### Decision 2 — supported output profile

**Approved decision:** expose exactly one WU3A allowlisted profile, `youtube-1080p30-v1`:

- MP4 container; 1920×1080; constant 30/1 fps.
- H.264 via the verified software encoder, High profile, `yuv420p`, CRF 18, `medium` preset, BT.709 signaling, and `+faststart`.
- AAC-LC, 48 kHz, stereo, 192 kbit/s.
- Source audio normalized in job-owned staging to 48 kHz stereo PCM before concatenation; no loudness, EQ, dynamics, crossfade, or musical processing.

Configuration means selecting a checked-in profile ID, not arbitrary codec flags. Additional resolutions/frame rates/encoders require new allowlisted profile IDs and regression evidence; hardware encoders are outside WU3A.

**Rationale:** one deterministic CPU baseline minimizes portability and verification risk while satisfying the approved H.264/AAC 1080p target. Compatibility: the current draft manifest's 1920×1080/30/H.264/AAC values map to this profile only if all other migration checks pass. **Affected:** Docs 05, 06, 08, 12, 13, 20, 34–35, and 38.

### Decision 3 — image fitting

**Approved decision:** apply orientation, decode alpha over opaque black, preserve aspect ratio, scale to fit within 1920×1080, and symmetrically pad remaining pixels with black. Never stretch or crop. Upscaling is allowed with the approved FFmpeg scaler and recorded in the report. An exact 1920×1080 image passes through without geometry change.

The manifest's `visual.background` is required for WU3A; `cover` and `thumbnail` are not silent fallbacks. Blurred fill, smart crop, generated backgrounds, and user-selectable fit modes remain later features.

**Rationale:** deterministic and content-preserving for arbitrary aspect ratios; the current acceptance background remains exact. Compatibility: square cover art gains letterboxing instead of losing content. **Affected:** Docs 05, 08, 12, 18, 22, and 38.

### Decision 4 — timeline and chapters

**Approved decision:** decode/normalize each ordered track to 48 kHz stereo PCM and derive boundaries from cumulative decoded sample counts. Internal offsets remain rational sample counts. Album duration is the sum of normalized samples; individual-track duration is that track's normalized sample count.

For YouTube text, floor each exact chapter start toward zero to the preceding whole second so a label never starts after the audio transition. Format UTF-8/LF as `MM:SS Title` below one hour and `H:MM:SS Title` at/above one hour; the first line is `00:00 <title>`. Replace embedded CR/LF in titles with a single space. `chapters.txt` contains only ordered chapter lines plus a final LF. The exact rational/sample offsets and displayed integer seconds also appear in `render_report.json`.

Do not embed chapters into MP4 in WU3A. Embedded chapters would create a second representation and require player/container compatibility policy; revisit only through a later profile/contract version.

**Rationale:** sample-derived truth with conservative YouTube labels and one authoritative timeline. Compatibility: WU5 consumes the text/report and never re-probes. **Affected:** Docs 05, 06, 12, 19, 26, 38, and WU5 specifications.

### Decision 5 — naming, layout, collision, replacement, and reuse

**Approved decision:** use the Section 6.1 tree and these deterministic names:

- Album: `output/album/<safe-album-title>.mp4` (acceptance: `output/album/Echoes of Asia.mp4`).
- Track: `output/tracks/<NN> - <safe-track-title>.mp4`, with two-digit manifest track number.
- Future Short: `output/shorts/<stable-short-id>.mp4` (reserved for WU6).
- Metadata: the four fixed filenames in Section 6.1; WU3A creates only `chapters.txt` and `render_report.json`.

`safe-title` is Unicode NFC, trimmed, with control characters and Windows-invalid filename characters `< > : " / \ | ? *` replaced by `_`, repeated whitespace collapsed to one space, and trailing spaces/dots removed. Windows reserved basenames and empty results are rejected rather than guessed. Case-insensitive/canonical collisions are validation errors.

Existing validated media with the same path and matching request/input/tool fingerprint is reused after verification. A missing/invalid/mismatched fingerprint or different content at the target path fails with `OUTPUT_EXISTS`; WU3A has no implicit replace and no force-overwrite option. Attempt staging never overwrites a final. `render_report.json` is an atomically revisioned artifact catalog: add/reuse entries by project-relative artifact path, preserve prior nonconflicting entries/history, and reject stale revision or conflicting identity. `chapters.txt` is reused only for the identical album timeline fingerprint; otherwise an existing file is a collision. A future work unit may introduce an explicit controlled replacement operation only through a separately approved recoverable contract.

**Rationale:** predictable human-readable paths, safe reruns, and uploader discovery through the result/report rather than filename inference. Compatibility: title changes naturally produce a new path; existing files are never silently destroyed. **Affected:** Docs 05, 08, 10–14, 19, 21, 30, 35, and 38.

### Decision 6 — supported headless interface

**Approved decision:** add one package entry point with these exact forms:

```powershell
.\.venv\Scripts\python.exe -m wrld_video_studio video-export --album-project "C:\path\to\album" --target album --profile youtube-1080p30-v1
.\.venv\Scripts\python.exe -m wrld_video_studio video-export --album-project "C:\path\to\album" --target track --track-id "stable-track-id" --profile youtube-1080p30-v1
```

Optional `--ffmpeg-path` and `--ffprobe-path` override the existing verified discovery/configuration policy and must be supplied together as absolute paths. There is no `--output`, arbitrary encoder-argument, replace, upload, or frontend option. The command validates, submits through application services, runs/reconciles the one local worker synchronously, treats Ctrl+C as cooperative cancellation, prints a sanitized JSON result plus human summary, and exits nonzero unless the requested artifact is completed and verified.

**Rationale:** ordinary PowerShell usability without a parallel render script or repository-location assumption. Compatibility: reuses current package/import boundaries and WU2 process ownership; exact console formatting may evolve without changing the JSON result schema. **Affected:** README, Docs 02, 07, 09, 13–14, 21, 32, 38, and future CLI tests.

### Decision 7 — *Echoes of Asia* title/art mismatch

**Approved decision and resolution:** validate the current user-corrected files. Read-only inspection confirmed that the current 1920×1080 video background visibly identifies *Echoes of Asia*, so the historical mismatch is resolved. The application must still fail normal validation if the manifest-selected file is missing, unsupported, or changed; it must never alter pixels, rename the album, or infer intent automatically.

**Rationale:** prevents publishing a technically valid but semantically wrong artifact. Compatibility: source files remain untouched. **Affected:** Docs 05, 12, 38 and the eventual human-acceptance record.

### Decision 8 — generated title typography

**Approved decision:** defer generated title typography entirely. WU3A renders the selected background as supplied after only the Decision 3 geometry operation. Text already baked into source pixels remains visible; WU3A does not inspect, replace, or overlay it.

**Rationale:** delivers the requested basic static-video capability without introducing font packaging, escaping, layout, or preview/final parity scope. Compatibility: later title/effect work must use a new approved render profile/contract and preserve WU3A static behavior. **Affected:** Docs 01, 04–05, 08, 12, 18, 22, 37, and 38.

### Approval state

All eight decisions are **APPROVED**. The contract-decision gate is closed and the current implementation candidate follows them. The separate Echoes source-manifest preparation gate is resolved by the user's manual migration and read-only validation. Real album/track rendering plus human review remain acceptance gates; the application must still reject and never silently repair invalid source manifests.

## 16. Required implementation sequence

1. **Phase 1 — contract implementation:** inspect actual source/contracts, implement the approved Section 15 decisions and fixed project-local `output/` boundary, check in the approved schemas/fixtures, and prove schema/application agreement. Do not modify the real album manifest during this phase.
2. **Phase 2 — timeline and planning:** secure project-relative source resolution, probes, normalization plan, ordered timeline, chapters, album/track immutable plans, portability/containment tests, and unit/contract tests.
3. **Phase 3 — renderer and lifecycle:** static-image H.264/AAC encoder behind ports; reuse job, admission, staging, verification, cancellation, and recovery; real synthetic integrations.
4. **Phase 4 — headless interface:** approved CLI/programmatic adapter and ordinary-PowerShell documentation; no frontend dependency.
5. **Phase 5 — regression and CI:** complete suites, Windows/Ubuntu media gates, fault injection, full decode, and independent lifecycle review.
6. **Phase 6 — real album acceptance:** using the manually migrated and schema-valid current source manifest, validate the corrected artwork, render *Echoes of Asia*, automate probe/decode/chapter checks, complete human playback review, and record evidence.

Stop and report after each approved phase. Do not commit, push, or begin any successor unit without its separate authorization; Doc 39 now identifies WU3B as the next planned unit.
