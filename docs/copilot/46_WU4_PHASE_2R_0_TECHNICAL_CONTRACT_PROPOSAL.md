# 46 — WU4 Phase 2R technical contracts

**Status: APPROVED TECHNICAL CONTRACT (2026-10-29); PHASE 2R.1–2R.3 IMPLEMENTATION AUTHORIZED, ACCEPTANCE PENDING.** The user approved the architecture, contract identifiers, migration model, identity rules, scan lifecycle, secure-resource model, runtime separation, session-only handoff and WU6 solid-background ownership, with the refinements finalized below. Executable schemas and implementation candidates now exist in the uncommitted working tree; this document remains contract authority, not acceptance evidence.

## 1. Goals and non-goals

This contract adds a project registry and asset-inventory layer in front of the existing strict album/render adapters. It preserves opaque project identity, trusted-root containment, source immutability, revision-safe private storage, current WU3 request identities and existing editor relationships.

It does not make arbitrary assets valid render inputs, rewrite manifests, create a second renderer or media-job scheduler, persist WU6 render plans, implement WU5 metadata, or implement WU7/WU8 rendering.

## 2. Contract set

The following identifiers are approved:

| Contract | Approved identifier | Purpose |
| --- | --- | --- |
| Project registry | `wrld-project-catalog/2.0` | Stable project identity and trusted-root-relative location |
| Project inventory | `wrld-project-inventory/1.0` | Transactional scan revision and discovered assets |
| Scan status | `wrld-project-scan/1.0` | Bounded asynchronous scan attempt/status |
| Asset capability | embedded versioned object | Machine-readable support and reason codes |
| Legacy Import handoff | `wrld-import-handoff/1.0` | Readable session compatibility for the earlier workflow/selection transfer |
| Current Import handoff | `wrld-import-handoff/2.0` | Project identity plus observed inventory/preference revisions; not a render plan |
| Project preferences | `wrld-project-preferences/1.0` | Revisioned stable-asset exclusions separate from inventory |
| Creation state | `wrld-creation-state/1.0` | Revisioned album/Single/Short planning and strong dependencies |
| API error | existing `wrld-api-error/1.0` where sufficient | Preserve the Phase 1 public error envelope |

The existing `wrld-project-catalog/1.0`, `wrld-album-read/1.0`, `wrld-editor-state/1.0`, manifest schemas and WU3 request/result contracts remain readable and unchanged.

## 3. Project registry v2

### 3.1 Project record

Each record contains:

- `project_id`: existing or newly generated opaque stable ID. It is not derived from a path, filename, album ID or content hash.
- `root_id`: server-configured trusted-root identity.
- `relative_path`: normalized portable path from the trusted root to the project boundary.
- `active`: catalog membership state, preserving Phase 1 soft removal.
- registration/update timestamps for diagnostics only, never identity or render reuse.
- `enrichment`: optional status containing recognized manifest format and manifest-owned album ID. The album ID is not project identity.
- current committed inventory revision and last scan status when available.

Public responses expose no absolute paths. Root display information remains server-controlled and must not reveal private filesystem prefixes.

### 3.2 Boundary and overlap policy

**Approved initial rule:** two active projects may not resolve to the same canonical directory or to ancestor/descendant directories. Relinking applies the same rule. Reject with a typed conflict and identify only the conflicting opaque project ID. This restriction simplifies authorization, duplicate discovery and rescan ownership. A later catalog version may support explicit nested projects; the v2 schema must not encode the restriction as a permanent identity invariant.

### 3.3 Versioned migration

Migration from catalog v1 to v2 is approved as follows:

1. Read and validate the complete v1 catalog under the existing private store lock.
2. Produce a complete v2 candidate without changing any `project_id`, `root_id`, `relative_path`, active state or timestamps.
3. Move each v1 `album_id` into optional manifest enrichment; do not use it as the v2 project key.
4. Resolve each active boundary using existing secure containment rules. A missing project remains registered but unavailable; a boundary escape or overlap blocks migration with diagnostics and no partial write.
5. Atomically publish the v2 document with a migration marker containing source contract version and source document digest. Retain one immutable recoverable pre-migration document in private state through Phase 2R acceptance. Phase 2R.1 never deletes it; any later cleanup requires an explicit maintenance operation outside automatic startup/migration.
6. Leave editor-state documents unchanged because their `project_id` remains stable. Album-backed editor state remains available through the manifest-enrichment adapter.
7. Repeating migration with the same v1 digest is idempotent. A partially or indeterminately committed migration is resolved using the existing read-after-write/revision rules.

**Unavoidable change:** catalog records no longer require `album_id`. Consumers that assumed every project has an album must use enrichment status or the album endpoint. Compatibility endpoints remain additive rather than changing existing album payloads into nullable hybrids.

## 4. Asset inventory and identity

### 4.1 Inventory envelope

An inventory is keyed by `project_id` and contains:

- monotonically increasing `inventory_revision`;
- opaque `scan_id` and completion time;
- project-boundary identity used for the scan;
- scan-policy version;
- complete asset records and complete diagnostics;
- aggregate counts by media kind and status.

Only a completed scan publishes a new inventory revision. Cancellation, timeout, crash or fatal boundary failure leaves the previous revision authoritative.

### 4.2 Asset record

- `asset_id`: persisted opaque ID independent of filename, absolute path and content hash.
- `relative_path`: current portable path within the project.
- `kind`: `audio`, `image`, `video`, or `unknown` after probing.
- `presence`: `present` or `missing`.
- `fingerprint`: SHA-256 algorithm/version, strong digest, byte length, verification state and the scan/operation that last computed it.
- `observation`: securely read file size, nanosecond modification time where available, and platform file identity where available. These are change-detection hints only and never authoritative reuse, replacement or render evidence.
- safe media properties: detected media/container/codec, duration where applicable, audio sample/channel data, image/video dimensions, pixel format/frame-rate data where applicable.
- probe outcome and sanitized diagnostic code.
- capability object with support state and reason for each operation.

No public inventory returns resolved absolute paths or raw FFprobe output.

### 4.3 Two-stage fingerprinting

Scanning uses an approved two-stage strategy:

1. **Observation stage:** securely reopen/stat each candidate inside the project boundary and compare its non-authoritative observation tuple with the last committed inventory. A matching tuple may avoid immediate rehash/probe during this inventory scan. The previous strong digest is carried forward with `verification_state: carried_forward`, not represented as freshly verified.
2. **Strong-verification stage:** compute SHA-256 from a securely opened regular-file handle whenever the asset is new, the observation changed, a previous hash/probe was incomplete, a carried-forward asset is first served as a resource, a relink is proposed or confirmed, the user explicitly verifies the asset, a composition dependency is saved/revalidated, or an immutable render snapshot is prepared. Hashing reads to EOF and validates the pre/post secure-handle observation; replacement during hashing fails with `ASSET_CHANGED_DURING_VERIFICATION`.

Metadata observations may optimize scan work but must never independently authorize asset replacement, relinking, dependency freshness, ETag identity for a newly observed representation, verified-artifact reuse, or rendering. Existing WU3 request/source fingerprinting remains mandatory and independently recomputes or validates the strong source evidence required by its contracts.

An unchanged observation plus a carried-forward hash may keep an asset listed and avoid invalidating an unrelated draft. Before an asset becomes or remains a saved composition dependency, its current strong SHA-256 must be verified. The inventory records `verified` versus `carried_forward` so consumers cannot confuse the two states.

### 4.4 Rescan identity rules

- Same relative path and same strong fingerprint: preserve `asset_id`.
- Same relative path and changed fingerprint: preserve `asset_id` as the logical registered slot, record a new observed fingerprint, and mark dependent drafts stale until reviewed. A composition snapshot continues carrying the fingerprint it selected.
- Missing path: preserve the asset record and ID with `presence: missing`; never delete dependent edits automatically.
- Same content at a different path: create a relink candidate but do not merge automatically. User-confirmed relink may preserve the old `asset_id` only when no conflicting live asset uses the target path.
- Duplicate content at different paths: distinct asset IDs.
- A new unrelated asset changes the inventory revision but does not change dependency fingerprints for existing compositions.

## 5. Recursive discovery

### 5.1 Security and traversal

- Open and validate the project boundary through the existing trusted-root resolver.
- Reject a project root that is a symlink, junction or reparse point.
- Do not follow directory or file links/reparse points. Record a scoped diagnostic and skip the entry.
- Revalidate canonical containment when opening each file for hash/probe/resource access; directory enumeration alone is not authorization.
- Treat source replacement between observation and secure open as a typed changed-source result.
- Never traverse into another active registered project boundary under a future policy that permits nesting.

### 5.2 Exclusions

Mandatory exclusions are the project-local `output/`, `.wrld-staging/`, `.wrld-cache/`, and `.git/` trees plus files named `Thumbs.db`, `desktop.ini`, or `.DS_Store`. Directory matching is by complete path segment and is case-insensitive on Windows. File-name matching follows the host filesystem's case behavior. Hidden files are not excluded merely for being hidden. Administrators may add exclusion segments/names in server configuration but cannot remove the mandatory exclusions for an active contract version. Exclusions are reported through the scan-policy version, never supplied as arbitrary client paths.

### 5.3 Approved configurable budgets

Initial defaults, all server-configurable and reported in scan status:

- maximum 20,000 visited entries;
- maximum directory depth 32 beneath the project boundary;
- maximum scan wall time 10 minutes;
- maximum two concurrent metadata probes per scan;
- maximum one concurrent strong-content hash per scan;
- one active scan per project and at most two active scans process-wide;
- 30-second bounded probe timeout per file;
- immediate cancellation checks between directory entries and before/after hash or probe operations.

Administrator configuration may raise these values only to the hard ceilings below:

- 100,000 visited entries;
- depth 64;
- 60 minutes wall time;
- four concurrent probes per scan;
- two concurrent strong hashes per scan;
- four active scans process-wide, still one per project;
- 120 seconds per probe.

Client requests cannot override budgets. A controlled retry uses the same scan-creation endpoint with `retry_of_scan_id`; the server records the current administrator-selected policy/version. Raising a limit requires server configuration, not an HTTP-supplied number.

Fatal scan-limit diagnostics are:

- `SCAN_ENTRY_LIMIT_EXCEEDED`;
- `SCAN_DEPTH_LIMIT_EXCEEDED`;
- `SCAN_WALL_TIME_EXCEEDED`;
- `SCAN_CAPACITY_EXCEEDED` when process-wide or per-project scan capacity rejects creation;
- `SCAN_POLICY_INVALID` when administrator values exceed hard ceilings or are internally inconsistent;
- `SCAN_CANCELLED` for acknowledged cooperative cancellation.

A per-file probe timeout records `MEDIA_PROBE_TIMEOUT` on that asset and may still publish a complete inventory containing the failed probe result. It is not a partial inventory: every visited entry is represented or diagnosed. Fatal scan-limit, cancellation, crash, boundary, revision-conflict or policy errors publish no candidate inventory and preserve the previous committed revision.

### 5.4 Transaction and recovery

The scanner writes attempt-owned temporary state in private application storage, never inside source directories. It builds a complete candidate snapshot and atomically promotes it under an expected inventory revision. Concurrent rescans for one project are rejected. A scan whose expected revision is stale must not overwrite the winner. Startup marks abandoned scan attempts interrupted and removes only their recorded temporary state; it does not alter the last committed inventory.

## 6. Media capability matrix

Capability values are `supported`, `unsupported`, or `indeterminate`, each with a stable reason code. The backend reports `server_stream`; the frontend derives `browser_audition` from that capability plus runtime `canPlayType` and actual decode success. The backend never claims universal browser support.

| Media | Discover/probe | Server resource | Browser operation | Authoritative render |
| --- | --- | --- | --- | --- |
| WAV: `wav` container with one positive-duration audio program; PCM `u8`, `s16le`, `s24le`, `s32le`, or `f32le` is the Phase 2R audition allowlist | Yes | Range stream as `audio/wav` | Runtime conditional | Existing WU3 behavior unchanged; only approved manifest/request decides renderability |
| MP3: `mp3` container and MP3 audio codec | Yes | Range stream as `audio/mpeg` | Runtime conditional | Unsupported by current WU3 source contract |
| FLAC: `flac` container and FLAC audio codec | Yes | Range stream as `audio/flac` | Runtime conditional | Unsupported by current WU3 source contract |
| M4A: ISO-BMFF/M4A container with AAC audio and no ordinary video stream; attached cover art is allowed and ignored for audition | Yes | Range stream as `audio/mp4` | Runtime conditional | Unsupported by current WU3 source contract |
| M4A/MP4 with ALAC or another audio codec | Discover/probe with diagnostic | Unsupported initially | Unsupported initially | Unsupported by current WU3 source contract |
| PNG, JPEG, single-frame WebP | Yes, subject to image limits | Bounded original inspection plus derived thumbnail | Inspection/thumbnail | PNG/JPEG remain renderable only through existing approved WU3 manifest/request; WebP is not a WU3 source |
| Animated PNG/WebP or multi-frame image | Discover/probe with `IMAGE_ANIMATION_UNSUPPORTED` | Unsupported | Unsupported | Unsupported |
| MP4 with an ordinary video stream | Technical discovery/probe only | No Phase 2R video-content endpoint | Deferred | Imported-video composition is WU8; current WU3 output support is not input support |
| Unknown/unsupported | Inventory with diagnostic where safe | None | None | None |

Extensions are discovery hints only. FFprobe/signature/container evidence must agree with the allowlist before a capability is `supported`. Multiple ordinary audio programs, non-finite/non-positive duration, embedded executable/script content, malformed headers, or contradictory container/codec evidence produce `MEDIA_UNSUPPORTED` or `MEDIA_MALFORMED` without failing the whole scan. Phase 2R performs no audition transcoding.

### 6.1 Image safety limits

The approved initial image limits are:

- source encoded size at most 256 MiB for image inspection/thumbnail decoding;
- width and height each from 1 through 32,768 pixels;
- at most 50,000,000 decoded pixels;
- exactly one display frame; animation/multiple frames are unsupported;
- 30-second thumbnail decode/process timeout;
- at most 512 MiB process-private thumbnail cache, at most 5,000 entries, and at most 16 MiB per encoded thumbnail;
- `small`: contain within 256×256 pixels;
- `large`: contain within 1024×1024 pixels;
- preserve aspect ratio and alpha where present; never crop, stretch or upscale;
- thumbnail output is deterministic PNG with `Content-Type: image/png`.

Original image resources are served only when signature/probe and allowlisted MIME agree: PNG as `image/png`, JPEG as `image/jpeg`, and single-frame WebP as `image/webp`. Every response uses `X-Content-Type-Options: nosniff`. SVG, TIFF, GIF, PSD, raw-camera formats and unknown image types may be inventoried as unsupported but are not decoded or served in Phase 2R.

Thumbnail generation uses the existing owned-process/toolchain abstraction with bounded timeout and sanitized diagnostics; it does not invoke a shell or create files in the source project. Malformed input, decompression-limit violations, timeout, nonzero decoder exit, oversized output or inconsistent output metadata records a typed asset diagnostic (`MEDIA_MALFORMED`, `IMAGE_DECODE_LIMIT_EXCEEDED`, `MEDIA_PROBE_TIMEOUT`, or `THUMBNAIL_INVALID`) and publishes no cache entry. It does not fail an otherwise complete inventory.

## 7. Secure media access

The following additive route shapes are approved for the Phase 2R implementation contract:

- `GET /api/v1/projects/{project_id}/inventory`
- `POST /api/v1/projects/{project_id}/inventory-scans`
- `GET /api/v1/projects/{project_id}/inventory-scans/{scan_id}`
- `DELETE /api/v1/projects/{project_id}/inventory-scans/{scan_id}` for cooperative cancellation
- `GET|HEAD /api/v1/projects/{project_id}/assets/{asset_id}/audio`
- `GET|HEAD /api/v1/projects/{project_id}/assets/{asset_id}/image`
- `GET /api/v1/projects/{project_id}/assets/{asset_id}/thumbnails/{variant}`

Resource rules:

- Resolve by `project_id` and `asset_id`, never by a client-provided filesystem path.
- Reopen through secure containment. Observation changes force strong re-verification. A carried-forward fingerprint is strongly reverified before the first resource response so ETag/content identity never relies on metadata observations alone. Later responses may reuse that verified digest only while the secure observation remains unchanged; relinking, dependency freshness, rendering and artifact reuse still apply their own mandatory strong-verification rules.
- Reuse Phase 1 single-range, ETag, If-Range, HEAD, invalid-range 416 and close-on-disconnect behavior for audio. Multiple ranges are rejected rather than returned as multipart ranges.
- Use allowlisted MIME types and `nosniff`; never serve unknown files through a generic content endpoint.
- Image originals are streamed only for the approved PNG/JPEG/WebP formats and limits. Thumbnails are derived into a private least-recently-used cache keyed by verified source SHA-256, decoder identity/version and fixed variant.
- Thumbnail variants, decode limits and cache budgets are exactly those in Section 6.1. Cache eviction removes only cache-owned entries and never source files.
- Do not expose raw FFprobe stderr, absolute paths or private cache locations.
- No MP4 content endpoint is part of Phase 2R.2.

## 8. Rescan, editor state and dependency fingerprints

Inventory revision answers “what the project contains now.” A composition dependency fingerprint answers “what this saved draft selected.” They are intentionally different.

The additive Creation reference stores `asset_id`, expected strong fingerprint and output-instance role. Saving an unrelated new asset increments inventory revision without invalidating that draft. A selected asset that becomes missing or whose fingerprint changes marks only dependent drafts stale. It never substitutes a same-name or same-content asset automatically.

Concurrent behavior:

- Rescan publishes through inventory revision compare-and-swap.
- Editor Save continues using editor revision compare-and-swap.
- Editor Save validates referenced assets against the current inventory immediately before commit.
- A concurrent rescan that changes a selected dependency yields a typed 409/stale-dependency response; a rescan affecting only unrelated assets does not.
- An indeterminate commit is resolved with the existing save-ID/read-after-write strategy.

The exact additive editor-state schema for asset references belongs to Phase 2B and remains pending; Phase 2R.1 must not rewrite existing editor documents.

## 9. Import handoff and production-plan boundary

Phase 2R.3 now creates `wrld-import-handoff/2.0`, containing only project ID plus the observed inventory and preference revisions. Review resolves all present, non-excluded assets from those server-owned documents. Import does not choose an output workflow, order recordings or construct a render plan. The earlier v1 workflow/ordered-audio document remains readable frontend compatibility input but is not emitted by the current Import UI.

The handoff exists only in the active frontend session and is not an immutable render request, approval record or batch job. Durable `wrld-creation-state/1.0` separately stores album ordering and independent Single/Short drafts through revision-safe persistence, so saved Creation work survives refresh/restart without repeating Import selection. It records asset identity and expected strong content fingerprint; changed or missing dependencies remain visible and block a new save until reviewed.

WU6 owns authoritative render-plan generation, deduplication, queueing and batch execution. Creation drafts are planning records and never promises that an unimplemented renderer exists.

## 10. Runtime separation

**Approved architecture:** construct a WU4 Import runtime from trusted project roots, private state, registry/inventory schemas, secure resolver and bounded probe/thumbnail tool services without requiring preview artwork registrations or a configured preview renderer. The top-level FastAPI composition may optionally attach the existing WU3 preview runtime and must share established admission when preview/render work is enabled.

Inventory scanning uses an application-scoped bounded scan coordinator, not `RenderWorker`, because it does not own a media render job or output artifact. This coordinator is not a second render scheduler: it supports only inventory scans, one active scan per project, bounded process-wide concurrency, cooperative cancellation and lifespan reconciliation. The existing FFprobe/process runner and Windows process ownership are reused for probe subprocesses.

## 11. Solid-background ownership

**Approved ownership:** WU4 may persist a solid-color background as a composition draft after the Phase 2B versioned composition contract is approved. WU6 owns the first additive authoritative solid-color render profile/generation because WU6 owns final render planning and profile support. WU7 remains focused on advanced layered/parallax/procedural composition. Until the WU6 renderer exists:

- Import never requires artwork;
- Review may show solid color only as draft/approximate behavior;
- authoritative preview/render capability is `unsupported` with a reason;
- WU3 image-backed profiles and identities remain unchanged.

## 12. Compatibility and breaking changes

Preserved:

- current project IDs, active/removal state and root-relative locations;
- existing editor documents keyed by project ID;
- Phase 1 album, validation, WAV and editor endpoints for manifest-backed projects;
- Phase 2A components/tests, subject to replacing temporary adapters incrementally;
- WU3 manifest schemas, render requests, output namespaces, artifacts and acceptance history;
- trusted-root containment, reparse rejection, immutable sources and private revisioned storage.

Approved compatibility changes for Phase 2R implementation:

- catalog v2 makes album enrichment optional;
- frontend project models can no longer assume every project has album/tracks/artwork;
- Import runtime can start without preview/artwork configuration;
- new inventory/resource contracts and scan lifecycle are additive;
- automatic backend-error-to-demo fallback must be removed from production mode.

No existing public payload is silently changed to use nullable fields. New project/inventory endpoints are additive, while existing album endpoints remain valid only for enriched manifest-backed projects and return a typed unavailable/not-found error otherwise.

### 12.1 Frontend/backend contract conformance

Versioned JSON Schemas are the source of truth for public request/response documents. Phase 2R uses a pinned development-only `json-schema-to-typescript` generator where the schema maps faithfully to TypeScript. Generated files live under a dedicated `frontend/src/api/generated/` directory, are committed, and are not hand-edited.

The frontend provides:

- `contracts:generate` to regenerate types from the approved schemas;
- `contracts:check` to regenerate in a temporary location and fail on a diff;
- TypeScript compile-time use of the generated request/response types;
- shared valid/invalid JSON fixtures validated by backend schema tests and consumed by frontend adapter tests;
- handwritten application/view models only outside the generated directory, with explicit adapter tests.

No runtime state-management or schema-validation framework is introduced solely for this purpose. Runtime response validation may be added later only if concrete failure evidence justifies it. If a schema feature cannot be represented faithfully by the pinned generator, the contract check must fail and require an explicit adapter/test; it must not silently fall back to divergent handwritten transport types.

## 13. Phase acceptance criteria

### Phase 2R.1 — registry, inventory and rescan

- v1→v2 migration preserves every existing project ID and editor-state relationship or aborts atomically with diagnostics.
- Safe empty, manifestless, audio-only, image-only and manifest-backed directories register under trusted roots.
- Same/overlapping active boundaries follow the approved policy.
- Recursive discovery cannot escape through traversal, replacement, symlink, junction or reparse points.
- Budgets and cancellation leave the previous inventory intact and no task/temp state orphaned.
- Two-stage fingerprinting avoids unnecessary hashes while fresh strong SHA-256 remains mandatory for relink, saved dependencies and render snapshots.
- Every fatal budget outcome emits its approved typed diagnostic; an administrator-configured retry records its predecessor and policy version and never publishes the failed candidate.
- Manifest enrichment preserves existing normalized album behavior without rewriting sources.
- Rescan preserves asset IDs under the approved rules and represents missing/changed assets explicitly.
- Existing Phase 1 and WU3 regressions pass unchanged.

### Phase 2R.2 — secure media resources

- Capability responses distinguish discovery, probe, server streaming, browser support, thumbnail, preview and render support.
- Audio Range/HEAD/ETag/disconnect behavior is verified for every approved format.
- Image inspection and deterministic `small`/`large` PNG thumbnails enforce the exact source, dimension, pixel, timeout, entry and cache-byte limits in Section 6.1.
- Changed/replaced source files fail safely instead of serving stale identity.
- Unsupported/unknown/video assets cannot be fetched through a generic file endpoint.
- Responses expose no absolute paths, raw diagnostics or private state locations.

### Phase 2R.3 — functional Import UI

- The retained Phase 2A UI can browse approved roots, register/remove/relink projects, display inventory/diagnostics, rescan and cancel where supported.
- Empty and no-artwork projects have useful states and can proceed only to truthful supported workflows.
- Manifest enrichment is shown as optional provenance, not a separate mode.
- Real backend errors remain visible; demo mode is explicit and isolated.
- All present, non-excluded project assets carry into Review through the v2 handoff without becoming WU6 render plans.
- The Import handoff is session-only; saved Creation state restores independently without requiring workflow or ordered-track selection in Import.
- Frontend contracts are checked against backend schemas/fixtures; accessibility and stale-response behavior are tested.
- Existing Import/Review components and tests are preserved or deliberately migrated with evidence.

## 14. Approval closure and later gates

The Phase 2R.0 decisions listed in the former proposal are approved and finalized in this document. No unresolved product/contract choice blocks preparation of a Phase 2R.1 implementation plan.

The later Functional Import authorization satisfied the Phase 2R.1–2R.3 implementation gate. Implementation candidates now exist in the uncommitted working tree, but this contract record does not itself constitute acceptance evidence. Acceptance still requires the scoped automated results and integrity report from that implementation pass.

Later gates remain intentionally open:

- Motion-preview HTTP and any additional durable visual-composition/editor schema beyond the approved Creation document remain separately gated.
- WU6 must separately approve the solid-color renderer profile, identity, verification and output compatibility contract.
- WU8 retains imported-video playback/composition contracts.
- Administrator deployment values may be lowered within the approved limits without a schema change; raising a value above a hard ceiling requires a new contract version or explicit amendment.

## 15. Consolidated WU4 additive contracts (v2.7)

The later consolidated authorization adds three strict schemas without mutating the Phase 2R contracts above:

- `wrld-project-preferences/1.0` stores only revisioned project-level exclusion identities and a canonical state digest; inventory remains technical truth.
- `wrld-import-handoff/2.0` carries project identity, inventory revision and preferences revision. It deliberately removes workflow and ordered-audio selection. V1 remains accepted by the frontend adapter for existing sessions.
- `wrld-creation-state/1.0` stores revisioned album plans/assignments, independent Single/Short instances, archived state, strong expected source hashes, Short ranges and draft settings. Read views add nonpersisted `SOURCE_MISSING`/`SOURCE_CHANGED` issues rather than deleting drafts.

These documents use the existing revision-safe private storage pattern, JSON Schema-to-TypeScript generator and opaque resource identities. Creation initialization preserves existing manifest-backed primary Short IDs and editor decisions where a matching inventoried source asset exists. No inventory, source manifest, render request or media file is rewritten.

### 15.1 Post-audit implementation status

The current uncommitted candidate persists scan-attempt documents beneath private application state and reconciles `queued`, `running` and `cancel_requested` attempts after restart. Retries retain predecessor identity and policy; interrupted work cannot remain falsely running. This is implementation status, not an acceptance claim.

Creation initialization also re-runs the approved legacy-primary adapter when a later inventory makes an eligible matching source available. Existing Short IDs, ranges, settings and approvals are preserved; reconciliation is idempotent and never replaces an existing Creation Short.

The frontend performs one read-after-write after `COMMIT_INDETERMINATE` and confirms only an exact save ID, candidate revision and state digest. Any mismatch becomes `COMMIT_UNRESOLVED`; revision conflicts remain explicit. V1 Import handoffs are labeled session-only compatibility input, while the v2 handoff and durable Creation document remain authoritative.

No schema version changed for these corrections. Additive HTTP behavior is limited to trusted-root asset relinking; catalog v2, inventory v1, preferences v1, handoff v1/v2 and Creation v1 remain compatible.

