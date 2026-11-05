# 52 — WU6 Creation v4 rendering integration contract proposal

**Status (2026-11-03): APPROVED — AUTHORITATIVE FOR WU6 IMPLEMENTATION, WITH THE IDENTITY-DERIVED CAMERA AMENDMENT BELOW.**

This document is the approved machine and behavior contract for rendering Creation v4 Album, Single, and Short compositions. It is additive. Docs 31 and 38–40 continue to govern WU3/WU3A/WU3B requests, manifests, renderer generations, and accepted artifacts. Docs 49–50 govern Creation visual authoring. Doc 51 governs WU5 metadata. WU5 is never an input to rendering.

## 1. Decisions and authority

| Decision | Proposal |
|---|---|
| Authoritative composition | The selected active Creation v4 object and its owned `visual_configuration` |
| Reusable templates | Never read; `source_visual_template_id` is excluded from render fingerprints |
| Publishing metadata | WU5 state, approvals, exports, and text are never read |
| Existing renderer contracts | `video-export-request/1.0`–`4.0` and results remain unchanged |
| WU6 contracts | Additive `wrld-creation-render-*/1.0` family promoted to `contracts/schemas/` |
| Job granularity | One composition per job; selected jobs accumulate in the single FIFO queue |
| Admission | Active v4 target, present/included strongly fingerprinted sources, supported visual configuration/profile, contained destination |
| Timeline | 48,000 normalized stereo sample frames; no gaps, fades, or crossfades |
| Replacement | Reuse verified identical work; otherwise fail without compare-and-swap `replace_verified` authorization |
| Concurrency | One FFmpeg execution at a time |

The 2026-11-03 approval covers these machine decisions together and authorizes schema promotion and WU6 implementation.

## 2. Contract family

| Schema | Contract identifier | Purpose |
|---|---|---|
| `creation-render-common-v1.schema.json` | Shared definitions | Closed targets, profiles, diagnostics, timelines and artifacts |
| `creation-render-request-v1.schema.json` | `wrld-creation-render-request/1.0` | Preflight or idempotent submission request |
| `creation-render-plan-v1.schema.json` | `wrld-creation-render-plan/1.0` | Immutable server-resolved plan |
| `creation-render-preflight-v1.schema.json` | `wrld-creation-render-preflight/1.0` | Ready/blocked/replacement-required result |
| `creation-render-targets-v1.schema.json` | `wrld-creation-render-targets/1.0` | Project target inventory |
| `creation-render-job-v1.schema.json` | `wrld-creation-render-job/1.0` | Durable status and recovery |
| `creation-render-result-v1.schema.json` | `wrld-creation-render-result/1.0` | Terminal factual result |
| Embedded timeline definition | `wrld-creation-render-timeline/1.0` | Authoritative sample timeline |
| Embedded artifact definition | `wrld-creation-render-artifact/1.0` | Verified video record |

Unknown identifiers are rejected. Dispatch uses the complete literal identifier. These contracts do not reuse `video-export-request/4.0` (the WU3B player generation) or the WU2 synthetic `RenderPlan`.

## 3. Identity, fingerprints, and staleness

A target is exactly `{kind, composition_id}`. `kind` is `album`, `single`, or `short`; the ID is the existing `album_plan_id`, `single_id`, or `short_id`. Project identity comes from the trusted URL/catalog boundary and the server-derived plan. IDs are never inferred from labels, paths, assets, or WU5 keys.

Only active targets render. Archived targets remain listable and their artifacts inspectable, but preflight returns `COMPOSITION_ARCHIVED`. Album plans have no approval flag. Single/Short `approved`, `customized`, `origin`, and `review_required` are Creation facts but not render inputs. A valid whole-source Short below five seconds may render while remaining review-required and unapprovable under WU4.

Fingerprints are lowercase SHA-256 of UTF-8 RFC 8785-style canonical JSON: keys sorted by Unicode code point, array order retained, no insignificant whitespace, finite JSON numbers, and server-produced project-relative POSIX paths.

`composition_fingerprint` hashes target identity/status; Album assignment order and each assignment ID, asset ID, expected SHA-256 and duplicate acknowledgement; Single asset identity/fingerprint; Short asset identity/fingerprint and exact range; and the complete owned visual configuration. It excludes labels, provenance/template registries, opaque generic settings, approval/customization/review flags, other compositions, WU5, envelope fields, and UI state.

`visual_configuration_fingerprint` hashes only the owned configuration. `source_set_fingerprint` hashes ordered audio plus background `{kind,asset_id,observed_sha256}` tuples. `timeline_id` is `timeline-` plus SHA-256 of `{sample_rate,total_samples,entries}`. `request_fingerprint` excludes `mode`, `expected_plan_fingerprint`, `submission_id`, and the `replacement` compare-and-swap receipt; it includes `output_action`. `plan_fingerprint` hashes the complete plan except `plan_id`, `plan_fingerprint`, `request_fingerprint`, and Creation revision/state digest. Renderer contract/build plus FFmpeg and FFprobe versions are plan fields and therefore affect the fingerprint. `plan_id` is `plan-<plan_fingerprint>`.

Revision/state digest remain provenance. Preflight requires exact caller values. Submission reloads Creation and reconstructs the selected plan. An unrelated Creation revision may advance without staling a plan when the reconstructed fingerprint is identical. Relevant visual, assignment, range, source-byte, background-byte, archive, profile, renderer or destination changes return `PLAN_STALE`. Other compositions, templates, WU5, and unrelated assets do not invalidate it. Excluding a referenced source blocks fresh preflight.

## 4. Authoritative timelines

Sources normalize through the existing WU3A path to signed 16-bit little-endian PCM, 48,000 Hz, stereo. Integer sample frames are authoritative; seconds are derived as `samples / 48000`.

Albums resolve assignments in saved order. Duplicate assets remain distinct assignments. Every entry starts at source sample zero and uses the complete normalized source. Output starts at zero and then the prior exclusive end; end equals start plus count. V1 adds no silence, gap, fade, crossfade, or transition. Arbitrary/noncanonical Album plans use this timeline rather than a manifest timeline. It may later supply chapter timing, but WU6 writes no chapter publishing text.

Singles contain one complete-source entry from sample zero. There is no hidden trim, padding, or manifest clip.

Shorts contain one entry using the saved `start_sample` and `sample_count` exactly. Negative/zero values, start at/after EOF, or end beyond normalized samples return `EXCERPT_INVALID` or `EXCERPT_OUT_OF_RANGE`. WU6 never clamps, pads, loops, or invents a range. WU4's valid whole-source exception below five seconds remains intact.

## 5. Technical profiles

| Field | Album | Single | Short |
|---|---:|---:|---:|
| ID | `wrld-album-1080p30-v1` | `wrld-single-1080p30-v1` | `wrld-short-1080x1920p30-v1` |
| Dimensions | 1920×1080 | 1920×1080 | 1080×1920 |
| Video | 30 CFR; H.264 High; libx264 medium CRF 18; yuv420p; BT.709 | same | same |
| Audio | AAC-LC 192,000 bit/s; 48 kHz stereo | same | same |
| Container | MP4 fast-start | same | same |
| Verification | ±0.25 s; probe; complete decode through EOF | same | same |

The schemas close every profile field. Album/Single require matching 16:9 profiles and Short the 9:16 profile. Mismatch is `PROFILE_TARGET_MISMATCH`; unknown identity is `PROFILE_UNSUPPORTED`. New codecs, sizes, rates, or quality require a new profile contract.

## 6. Exact visual mapping

Rendering reads only `visual_configuration`. Order is orientation-aware decode → fit/focal composite over opaque black → color treatment → camera → visualizer → progress → BT.709/yuv420p output.

`16:9` selects 1920×1080 for Album/Single; `9:16` selects 1080×1920 for Short. Null background is blocking `VISUAL_SOURCE_REQUIRED`; no generated, black, template, or alternate-image fallback exists. The source must be present, included, strongly fingerprinted PNG/JPEG or inspected safe single-frame WebP. Expected and observed SHA-256 must match. Alpha composites over black.

For oriented source `Iw×Ih` and canvas `Cw×Ch`, `contain` uses `s=min(Cw/Iw,Ch/Ih)` and `cover` uses `s=max(...)`; `Rw=Iw*s`, `Rh=Ih*s`, `x=(Cw-Rw)*focal_x`, `y=(Ch-Rh)*focal_y`. The result clips to the canvas. Stretching is forbidden.

`camera.mode=static` emits no transform; stored zoom remains fingerprinted authoritative state. `bounded` chooses one deterministic direction from the ordered set `[horizontal, vertical, diagonal_down_right, diagonal_up_right]`. Compute `SHA-256(UTF-8(kind + ":" + composition_id))`, interpret the first digest byte as an unsigned integer, and select `directions[byte % 4]`. The selected direction is server-derived, included in the resolved execution mapping and covered by the plan fingerprint; it is never persisted back to Creation. The motion uses the existing smoothstep primitive with a 180-second triangular out/back cycle, saved maximum zoom, crop-bounded translation, and a final five-second return to zoom 1/origin (half the duration when total duration is below ten seconds). The final encoded frame is exactly origin. Profile dimensions parameterize the same normalized motion for portrait. Tests must cover all four remainders, repeatability, composition-kind separation, crop bounds, portrait dimensions, smoothstep timing and final origin.

Disabled visualizer emits none. Enabled maps saved count/opacity to organic RMS with white bars, bottom center, 4 px gaps, 64 px bottom margin, 1,920-sample window, 60 ms attack, 240 ms release, and glow 0.35. Zone is 640×180 landscape and 720×240 portrait. It analyzes the current output sample; Short analysis starts at its excerpt.

Disabled progress emits none. Enabled draws a non-segmented bottom line after bars: canvas width minus 128, 6 px high, 64 px side/bottom margin, white fill opacity 0.8, existing auto-contrast rail strength 0.6/opacity 0.35. Fill at output sample `n` is clamped `n/total_samples`. Album spans the assembled Album, Single its full source, Short its excerpt.

`color_treatment.mode=none` is no-op. `custom` reuses the authoritative still treatment: sRGB → linear BT.709, preserve luminance, blend chroma toward supplied sRGB HEX by intensity `[0,0.6]`, gamut-clamp, return to sRGB/BT.709. It affects the fitted background before camera, never overlays. Invalid HEX/non-finite intensity rejects.

No v1 field is ignored. Advanced layers, titles, arbitrary paths, keyframes, imported video and procedural generation remain WU7/WU8 and return `VISUAL_FEATURE_UNSUPPORTED` if presented.

## 7. Diagnostics and fallbacks

The common schema closes the diagnostic enum. Errors block; warnings do not. Preflight returns 200 with `blocked` or `replacement_required` for domain findings. Transport/catalog failures retain the standard API envelope.

Key codes are `PROJECT_UNAVAILABLE`, `CREATION_V4_REQUIRED`, `COMPOSITION_NOT_FOUND`, `COMPOSITION_ARCHIVED`, `RECORDING_MISSING/EXCLUDED/CHANGED/UNSUPPORTED`, `VISUAL_SOURCE_REQUIRED/MISSING/EXCLUDED/CHANGED/UNSUPPORTED`, `EXCERPT_INVALID`, `EXCERPT_OUT_OF_RANGE`, `FFMPEG_UNAVAILABLE`, `FFPROBE_UNAVAILABLE`, `PLAN_STALE`, `OUTPUT_EXISTS`, and `OUTPUT_REPLACEMENT_STALE`. No source, template, excerpt, profile, or prior-artifact fallback is permitted.

## 8. Jobs, cancellation, and recovery

Preflight is read-only. Submission carries `mode: submit`, the preflight plan fingerprint, and caller UUID `submission_id`. Reusing a project/submission ID with the same request returns the durable job; different content is 409. Persisted job/attempt IDs are server UUIDs. Retry retains job ID, creates an attempt, and records its predecessor.

One worker claims FIFO by creation timestamp then job ID. An active identical plan returns its job. A matching artifact is reused only after fresh verification; no FFmpeg runs. A mismatched destination collides.

Queued cancellation is immediate. Running cancellation durably records `cancel_requested`, signals the owned process tree, waits for termination, reconciles staging, then becomes cancelled or failed. Success requires probe, complete decode, fast-start, digest, atomic promotion, and report publication.

Restart reconciliation precedes new claims. It verifies promoted output/report receipts and completes provable success, cleans owned unpromoted staging when provable, or records `RECOVERY_INDETERMINATE`. It never guesses or overwrites.

### 8.1 Additive staged-video recovery amendment

The approved additive identifiers are `wrld-creation-render-recovery-request/1.0`, `wrld-creation-render-recovery-preflight/1.0`, and the embedded `wrld-creation-render-recovery-candidate/1.0`. The closed render request and preflight v1 contracts are unchanged.

Recovery preflight names only an existing project-scoped failed job and attempt; clients never submit a filesystem path. The server reconstructs the current Creation v4 plan and requires exact target, profile, renderer, plan fingerprint, staging ownership, staged SHA-256/size, inspectable MP4 structure and `wrld_request:<plan_fingerprint>` provenance. The candidate also binds the current output path and artifact-report revision. Missing, partial, changed, cross-project, wrong-attempt, nonfailed, stale-plan, incompatible-renderer/profile and ambiguous candidates block with recovery-specific diagnostics.

Submission requires a fresh candidate fingerprint, a new submission UUID and explicit output/replacement action. It creates a new job and attempt whose `retry_of_attempt_id` names the historical failed attempt. The historical job/result are immutable. Idempotent reuse requires the same submission and recovery fingerprint. A changed candidate or report revision is stale. Recovery enters the existing FIFO and skips only encoding; lightweight probe, complete decode, fast-start, duration, profile, provenance and digest verification remain mandatory. Cancellation applies during verification and never falls back to encoding.

Publication uses durable private states `none`, `verified`, `artifact_committed`, and `result_committed`. File existence alone never proves success. Restart or in-process reconciliation may complete success only when the persisted verified candidate, registered artifact identity, plan fingerprint and current final-file digest all agree. A promoted file without the registered artifact receipt is indeterminate. Replacement CAS and restoration remain unchanged.

Long decode verification updates job heartbeat without changing phase progress. Standard render admission requires staging and publication on the same filesystem volume and uses a conservative estimate of all source snapshots plus three 48 kHz stereo PCM byte equivalents: one for normalized working audio and two as bounded allowances for staged output, verification/publication work, and retained recovery material. Existing retained files already reduce reported free space. This is deliberately an admission estimate, not a precise output-size forecast. Recovery moves an existing staged file atomically on that same volume, creates no second media copy, and reserves 1 MiB of free space for durable job, artifact-report, and result records before it may enter the queue.

Failed potentially recoverable staging and replacement history are retained. Successful publication never makes unknown or unledgered files disposable. Until a per-file ownership ledger exists, automatic cleanup removes only already-empty owned directories and leaves nonempty retained storage available for explicit inspection; it never guesses that a file is disposable. Therefore cleanup may conservatively retain known intermediates after success, and operational reports must account for accumulated failed staging and private replacement history. A dedicated storage-reporting or retention-policy UI remains outside this amendment.

## 9. Artifacts, reuse, and replacement

Paths are title-independent: `output/album/<album_plan_id>.mp4`, `output/tracks/<single_id>.mp4`, and `output/shorts/<short_id>.mp4`. Canonical/case-insensitive collisions, absolute/traversing/backslash paths, links/reparse escapes, aliases, and out-of-project destinations reject.

`artifact_id` is `artifact-` plus SHA-256 of canonical `{project_id,target,plan_fingerprint,relative_path,sha256}`. Records contain factual probe fields, byte digest/size, renderer/profile identity and verification. Only verified artifacts complete jobs or qualify for reuse.

`reuse_verified_or_fail` creates missing output, reuses an exact verified artifact, or returns `OUTPUT_EXISTS`. `replace_verified` requires the preflight-observed artifact ID, file SHA-256, and report revision. Mismatch is `OUTPUT_REPLACEMENT_STALE` before encoding.

Replacement stages and verifies first. Under report CAS, the old final moves atomically to `output/.wrld-history/<artifact_id>/<sha256>.mp4`, the new final promotes, then the report publishes supersession and the new record. Pre-commit failure restores the old final during reconciliation. History is private recovery material, not a selectable/publishing artifact. Unverified files cannot be replaced. Owned partials are removed only after durable proof they were not promoted.

Older WU3A artifacts remain unchanged and are reusable only if a future additive record carries the complete WU6 plan identity; path or media digest alone is insufficient.

## 10. Project-scoped API

| Method/path | Contract and behavior |
|---|---|
| `GET /api/v1/projects/{project_id}/render-targets` | targets contract; 200, 404 unavailable, 409 missing/non-v4 Creation |
| `POST /api/v1/projects/{project_id}/render-preflights` | preflight-mode request → preflight; always 200 for domain findings; 422 malformed |
| `POST /api/v1/projects/{project_id}/render-jobs` | submit-mode request → job; 202 new, 200 idempotent/reused, 409 stale/idempotency/replacement conflict |
| `POST /api/v1/projects/{project_id}/render-recovery-preflights` | recovery preflight request → additive recovery preflight; 200 ready/blocked/replacement-required |
| `POST /api/v1/projects/{project_id}/render-recovery-jobs` | authorized recovery submit → new linked job; 202 new, 200 idempotent, 409 stale/conflict |
| `GET /api/v1/projects/{project_id}/render-jobs` | job objects newest first; exact optional `state`/`composition_id` filters |
| `GET /api/v1/projects/{project_id}/render-jobs/{job_id}` | job or 404 |
| `GET /api/v1/projects/{project_id}/render-jobs/{job_id}/result` | result; 409 nonterminal; 404 unknown |
| `DELETE /api/v1/projects/{project_id}/render-jobs/{job_id}` | 202 cancel-requested, 200 already-cancelled, 409 terminal/non-cancellable |
| `GET /api/v1/projects/{project_id}/render-artifacts/{artifact_id}` | verified artifact or 404 |
| `GET /api/v1/projects/{project_id}/render-artifacts/{artifact_id}/content` | verified MP4 200/206 with private Range support |

Bodies contain no server root. Handlers call application services and never construct plans/commands. Artifact content is served only after current project/path/digest verification. Backend disconnection remains actionable and is never converted to empty data.

## 11. Render workspace

The user selects an active composition, reviews its fixed profile, runs preflight, reviews diagnostics/collision choice, submits, monitors, cancels, reconnects, inspects a verified artifact, and renders another composition. Archived rows are inspectable but not renderable.

Unsaved Creation edits cannot render. Existing guards offer Save/discard/cancel; Save reloads the basis. Stale preflight forces rerun and is never silently regenerated at submit. Jobs reconnect by project/job ID. Failed/cancelled attempts retain diagnostics and retry requires fresh preflight. Missing binaries, outage, and indeterminate recovery remain explicit.

The artifact panel appears only for succeeded results with a freshly verified artifact. File presence, encoding completion, or 100% progress is not success. Multiple selected targets are submitted as individually reviewed idempotent jobs into the one server queue; no parallel or atomic batch wrapper exists in v1.

## 12. WU5 independence and compatibility

No WU6 service, plan, fingerprint, schema, route, test, or UI selector reads or writes WU5 editor/export state. Missing, stale, invalid, unapproved, or absent WU5 cannot affect rendering. Publishing titles, descriptions, tags, hashtags, visibility, approvals, placeholders, URLs and exports are not render fields. Future publishing may join stable identities separately.

WU3/WU3A/WU3B schemas, CLI, report entries, profiles and verification remain unchanged. WU6 adds version dispatch and artifact kinds without reinterpreting old results. Plans/jobs are private machine state, never Creation fields. Preflight, render, retry, cancel and inspect never mutate Creation.

## 13. Implementation checklist after approval

- Promote approved schemas and generated types without altering WU3 contracts.
- Add semantic parsers for arithmetic, identity agreement, target/profile compatibility and hashes.
- Build plans from catalog, inventory, preferences and Creation v4.
- Parameterize existing geometry/camera/visualizer/progress for portrait.
- Reuse normalization, process ownership, single worker, heartbeat, cancellation, verifier, staging and report CAS.
- Add replacement receipts/history and new artifact kinds.
- Register exact routes/transports and replace only the Render placeholder.
- Keep all WU5 ports/services out of the WU6 composition root.
- Verify only with disposable fixtures; never production outputs.

## 14. Focused test matrix

| Area | Required evidence |
|---|---|
| Schemas | Positive examples, unknown fields/versions, non-finite numbers, request conditionals, references |
| Identity | All types; unrelated composition/template/WU5 changes retain plan; relevant changes stale it |
| Timeline | arbitrary/reordered/duplicate Album, full Single, exact Short, arithmetic, overrun rejection |
| Profiles | exact landscape/portrait fields, target/aspect mismatch, unsupported profile |
| Visuals | fit/focal edges, alpha/black, camera start/mid/return/final, portrait bounds, bars, progress, treatment golden frames |
| Dependencies | missing/excluded/changed audio/image; PNG/JPEG/WebP; corrupt/unsupported; mid-render change |
| Jobs | idempotency, duplicate plan, FIFO one worker, phase cancellation, heartbeat, retry, restart |
| Artifacts | probe/full decode/fast-start/duration/digest, reuse, collision, stale/recoverable replacement, cleanup |
| HTTP/UI | every status, project isolation, path privacy, Range, dirty guard, archived/stale/collision/reconnect/success gating |
| Independence | render without WU5; malformed/stale WU5 no effect; WU5/Creation byte-for-byte unchanged |
| Regression | WU1–WU5 plus unchanged WU3A/WU3B requests/results/CLI |

Disposable real-FFmpeg acceptance covers one Album, Single and 9:16 Short through EOF. No production tree is used.

The staged-recovery matrix additionally covers valid recovery, stale receipts, changed bytes, wrong project/job/attempt, partial encoding, plan changes, idempotency, verification cancellation/failure, publication interruption, restart reconciliation, Windows sharing violations, disk admission, conservative retention and WU5 independence.

## 15. Approval record

The user approved the package on November 3, 2026, subject to the identity-derived bounded-camera direction above and these retained conditions:

1. The proposed identifiers, fields, and fingerprint exclusions.
2. Stable-ID output paths under `output/album`, `output/tracks`, and `output/shorts`.
3. The three technical profiles and 1080×1920 support.
4. Section 6's camera, visualizer, progress and treatment mappings.
5. One-target jobs accumulated in the single FIFO as v1 batch behavior.
6. CAS replacement and private `output/.wrld-history` recovery copies.
7. Section 10 routes and statuses.

The approved schemas may now be promoted through the production schema/generated-type workflow and WU6 may be implemented. Historical recovery artifacts are never automatically deleted. Replacement must be explicit in the UI, storage accumulation must be documented, and history storage reporting should be provided where practical without expanding into lifecycle-policy work. Production project data remains outside implementation and test scope.

On November 4, 2026, the user approved Section 8.1's additive staged-video recovery and the related heartbeat, publication reconciliation, disk-admission and conservative-retention corrections. This approval does not authorize recovery or publication of the existing 289,369,933-byte production candidate; that remains a separate manual authorization.
