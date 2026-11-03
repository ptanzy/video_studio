# 51 — WU5 Metadata Contract

**Status:** APPROVED — AUTHORITATIVE FOR WU5. The user approved this contract and its two schemas on November 2, 2026, with the clarifications recorded in Section 17. Implementation remains subject to repository verification and must not begin WU6.

**Authority boundary:** The identifiers, fields, generation rules, routes, diagnostics, and replacement semantics below are normative for WU5. Docs 19, 23, 24, 26, 31, 38, and 41–43 remain compatible context; this newer specific contract resolves their WU5 ambiguities. Creation v4, WU3A rendering, and WU6 ownership remain unchanged.

## 1. Purpose and authority

WU5 provides a project-scoped Metadata workspace for YouTube publishing content attached to Creation v4 Albums, Singles, and Shorts. It separates editable drafts from immutable source facts and from the portable approved export. It does not render media, publish to YouTube, create upload state, modify source manifests, or change Creation visual settings or approvals.

This contract reconciles:

- Doc 19's generated-draft, override, chapter, validation, approval, and export requirements;
- Doc 23's Table/Detail editing, explicit Save, bulk impact confirmation, and conflict behavior;
- Docs 24 and 26's source precedence, provenance, deterministic offline generation, and non-overwrite rules;
- Doc 38's project boundary, portable output, verified chapter artifact, and strict WU3A ownership;
- Creation v4's multiple stable Album, Single, and Short identities; and
- the existing project-scoped HTTP and `ProjectDocumentStore` conventions.

The illustrative `docs/examples/metadata_contract.example.json` is not a schema. Its unapproved templates, genre values, platform preferences, URLs, rights fields, and analyzer fields are not silently adopted.

## 2. Approved decision table

| Previously unresolved choice | Recommended resolution | Status |
| --- | --- | --- |
| Editable state identity | `wrld-youtube-metadata-editor/1.0` | Approved |
| Portable export identity | `wrld-youtube-metadata/1.0` | Approved |
| Storage ownership | Separate project-local revisioned metadata document; never embed in Creation v4 | Approved |
| Target identity | `album:<album_plan_id>`, `single:<single_id>`, `short:<short_id>` plus typed target object | Approved |
| Target scope | Every active and archived Creation v4 Album, Single, and Short; orphaned state retained | Approved |
| Older Creation versions | Read-only Upgrade Required state; no metadata initialization before Creation v4 | Approved |
| Draft initialization | Explicit initialization; no write-on-GET and no automatic production migration | Approved |
| Later target changes | Explicit revision-safe reconcile; never overwrite existing target content | Approved |
| Editable fields | Title, description, tags, hashtags, publishing artist/channel, credits, links, visibility, pinned comment, optional release association and related-video URL | Approved |
| Source facts | Joined read-only from catalog, inventory, normalized album read, Creation v4, and WU3A; not duplicated as editable truth | Approved |
| Visibility | `private`, `unlisted`, or `public`; initial value `private` | Approved |
| Chapter timing | Immutable WU3A timing; labels editable; no WU5 probing or timeline calculation | Approved |
| Arbitrary Creation Album plans | Editable, but Album approval/export requires a proven WU3A-equivalent chapter source | Approved |
| Placeholder allowlist | `{{chapters}}` for Albums; `{{compilation_url}}` for Singles/Shorts | Approved |
| Approval | Explicit per target; SHA-256 fingerprint over export-affecting metadata and authoritative source basis | Approved |
| Export selection | Explicit target-key selection; all-or-nothing for that selected set | Approved |
| Existing export | No silent overwrite; compare-and-swap replacement using existing SHA-256 | Approved |
| Legacy root draft | Never auto-import; require a separately supported adapter, preview, selected mapping, and explicit import | Approved |

## 3. Two distinct contracts

### 3.1 Private editor state

The approved private schema is:

`contracts/schemas/youtube-metadata-editor-v1.schema.json`

Its contract identifier is `wrld-youtube-metadata-editor/1.0`. The document lives in application-owned project state at `<state-root>/youtube-metadata/`, through the existing revisioned `ProjectDocumentStore` and `OverrideStore` pattern. It is not written into the project directory, source manifest, Creation state, or output tree.

The top level contains:

| Field | Type | Meaning |
| --- | --- | --- |
| `contract_version` | constant | `wrld-youtube-metadata-editor/1.0` |
| `project_id` | stable ID | Internal project UUID; must match the requested project |
| `revision` | integer ≥ 1 | Optimistic document revision |
| `save_id` | stable ID | Idempotent Save identity |
| `generation_version` | constant | `wrld-youtube-metadata-draft/1.0` |
| `creation_basis` | object | Creation v4 revision and state digest last explicitly reconciled |
| `targets` | array | Stable target drafts in Creation order, followed by orphans |
| `state_digest` | SHA-256 | Existing document-store integrity convention |

The editor state contains no undo history, UI selection, filter, dirty flag, or browser-session state. Undo/redo remains client-local and explicit Save remains controlling.

### 3.2 Portable export

The approved portable schema is:

`contracts/schemas/youtube-metadata-v1.schema.json`

Its contract identifier is `wrld-youtube-metadata/1.0`. The only destination is:

`output/metadata/youtube_metadata.json`

It contains approved resolved content, stable source references, chapter provenance, optional verified artifact references, and approval evidence. It does not contain editor revision/save IDs, field origins, stale/orphaned targets, undo history, validation cache, UI fields, or unresolved placeholders.

## 4. Target identity and lifecycle

### 4.1 Canonical keys

The exact target keys are:

- Album: `album:<album_plan_id>`
- Single: `single:<single_id>`
- Short: `short:<short_id>`

The suffix is the literal Creation v4 stable ID. The accompanying typed reference is one of:

```json
{"kind":"album","album_plan_id":"album-plan-1"}
{"kind":"single","single_id":"single-1"}
{"kind":"short","short_id":"short-1"}
```

The service validates that the key and typed reference agree. It rejects duplicate keys, duplicate typed identities, a key/type mismatch, or an identity not conforming to Creation's stable-ID grammar.

### 4.2 Lifecycle

Each editor target has one lifecycle value:

- `active`: the matching Creation v4 target is active.
- `archived`: the matching Creation target exists and is archived.
- `orphaned`: metadata exists but the matching target no longer exists in the current Creation document.

Creation v4 archives rather than deletes through normal UI operations. `orphaned` nevertheless protects data from manual document changes, future versions, or imported state.

Policy:

- Archiving does not delete content or clear approval.
- Archived and orphaned targets are excluded from export selection.
- Restoring the same stable ID restores the same metadata and approval, subject to current dependency validation.
- A new stable ID receives a new deterministic draft during explicit reconciliation.
- Reordering changes display/export ordering but never identities or content.
- An identity change is a new target plus an orphan; content is never silently reassigned.

### 4.3 Creation basis and target fingerprints

`creation_basis` detects whether reconciliation is needed; it does not make visual changes relevant to metadata approval. Each target additionally stores:

- `creation_target_fingerprint`: canonical SHA-256 of metadata-relevant target identity, ordered recording references, expected audio hashes, label, and explicit release association inputs. It excludes `visual_configuration`, `source_visual_template_id`, visual approval, customization flags, and archive status.
- `source_metadata_fingerprint`: canonical SHA-256 of normalized source facts actually used to initialize supplied/generated fields plus the generation version.
- `chapter_source_fingerprint`: canonical chapter-text SHA-256 for Album targets, otherwise null.

Changing pixels never invalidates metadata approval. Changing source recording identity, expected audio bytes, a source fact used in content, a selected release association, or authoritative chapters does.

## 5. Field ownership and exact fields

Every editable field uses the private envelope:

```json
{"value":"Example","origin":"generated","source_fingerprint":"<sha256-or-null>"}
```

`origin` is exactly `generated`, `supplied`, or `edited`. Approval is target-level and is not a fourth field origin. An edit changes only that field to `edited` with a null source fingerprint. The service never changes an edited field during reconciliation or regeneration.

### 5.1 Common publishing fields

| JSON field | Value type/default | Authority and editing | Validation | Portable export |
| --- | --- | --- | --- | --- |
| `title` | string, default below | Supplied source, deterministic generator, then user edit | Required for approval/export; ≤100 Unicode code points | `metadata.title` |
| `description` | string, default below | Supplied source, deterministic generator, then user edit | ≤5,000 Unicode code points after placeholder resolution | resolved `metadata.description` |
| `tags` | string array, default `[]` | Supplied source or user | Unique by NFC+casefold comparison; aggregate serialized cost ≤500 | `metadata.tags` |
| `hashtags` | string array | Supplied/generated/user | Each begins `#`, contains no whitespace or second `#`, unique by NFC+casefold | `metadata.hashtags` |
| `artist_name` | string | Supplied normalized album/track fact, then user publishing override | Required; 1–200 code points | `metadata.artist_name` |
| `channel_name` | string | Supplied normalized channel fact, then user publishing override | Required; 1–200 code points | `metadata.channel_name` |
| `credits` | `{role,name}[]`, default `[]` | Supplied exact credits or user; roles remain free text | Nonempty role/name; duplicate pair warning | `metadata.credits` |
| `links` | `{key,label,url}[]`, default `[]` | Supplied exact non-related links or user | Unique key; absolute HTTP(S) URI syntax; no network request | `metadata.links` |
| `visibility` | enum, default `private` | User publishing choice | `private`, `unlisted`, or `public` | `metadata.visibility` |
| `pinned_comment` | string or null, default null | Supplied or user | Null or 1–5,000 code points; placeholders resolved before export | `metadata.pinned_comment` |
| `release_album_plan_id` | ID or null | Explicit static association; never live inheritance | Album target must be null; Single/Short ID must name an existing Album target and be active for approval/export | `metadata.release_album_plan_id` |
| `related_video_url` | URI string or null | User or supplied source; authoritative value for `{{compilation_url}}` | Album and Single default null; absolute HTTP(S) URI syntax; no network request | `metadata.related_video_url` |

Publishing `artist_name` and `channel_name` are editable copies with provenance. Editing them never mutates the normalized album read or source manifest.

### 5.2 Type-specific references

Album export additionally contains:

- `album_plan_id`;
- ordered `assignments` with `assignment_id`, `asset_id`, and `expected_sha256`;
- authoritative chapters and chapter-source fingerprint; and
- optional verified Album media/thumbnail references.

Single and Short export additionally contain:

- their `single_id` or `short_id`;
- `recording.asset_id` and `recording.expected_sha256`; and
- optional verified media/thumbnail references.

Short range, visual configuration, visual provenance, and visual approval are not publishing metadata and are not duplicated in either WU5 contract.

### 5.3 Tags counting

Tags remain separate strings; stored spelling and order are preserved. For the 500-character approval limit:

1. Count Unicode code points, not UTF-8 bytes or UTF-16 code units.
2. A tag containing whitespace costs its code-point length plus two quote characters.
3. Tags without whitespace cost their code-point length.
4. Add one comma separator between adjacent tags.
5. Commas, double quotes, CR, and LF inside a tag are validation errors rather than silently escaped.

Generated/supplied tags are deduplicated by `NFC(tag).casefold()` while preserving the first spelling and order. User-entered duplicates are reported and never silently removed during Save.

## 6. Deterministic initialization and draft generation

Draft generation is offline and uses no AI, network call, filename inference, analyzer fabrication, license claim, release-date inference, or URL fabrication.

### 6.1 Source precedence

For each field:

1. Preserve an existing edited field.
2. Preserve every field of a target with a current or stale approval until an explicit user refresh decision.
3. Use an explicitly supported supplied `publishing_source` field when an approved adapter maps it.
4. Otherwise use the exact generator below.

Initialization stores the result. Later source changes produce diagnostics and a reconcile preview; they do not mutate existing content on GET, scan, import, or Creation Save.

### 6.2 Exact generated templates

No smart quotes or localized punctuation are inserted. Newlines are LF.

Album:

- Title: the Creation v4 Album `label` exactly.
- Description with authoritative chapters: `{album_title}\n\n{{chapters}}`.
- Description without an authoritative chapter source: `{album_title}`.
- Hashtags: `[]`.

Single:

- Title: the normalized canonical track title only when the Single asset maps by verified project-relative audio identity and SHA-256 to exactly one normalized track; otherwise empty.
- Description: `{track_title}` when the title is known; otherwise empty.
- Hashtags: `[]`.

Short:

- Title: `{track_title} #Shorts` when a unique normalized track title is known; otherwise empty.
- Description: `{track_title}\n\nWatch the full compilation: {{compilation_url}}` when the title is known; otherwise empty.
- Hashtags: `["#Shorts"]`.

Common defaults:

- Tags: supplied tags in source order; otherwise `[]`. No genre or aesthetic tag is inferred.
- Artist and channel: exact normalized supplied values when available; otherwise empty and validation-required.
- Credits and links: supplied exact supported values; otherwise `[]`.
- Visibility: `private`.
- Pinned comment and related-video URL: null.
- Release association for a Single/Short: the sole active Album plan containing the same `asset_id` when exactly one such plan exists; otherwise null. This is a one-time generated value, not live inheritance.

### 6.3 Placeholder rules

The only placeholders are literal, case-sensitive tokens:

- `{{chapters}}`: Album description or pinned comment only; resolves to the effective chapter lines joined by LF.
- `{{compilation_url}}`: Single/Short description or pinned comment only; resolves from that target's `related_video_url`.

Unknown `{{...}}` tokens are errors. An unresolved allowed token may be saved in a draft but blocks approval, preview eligibility, and export. Portable export contains resolved text only.

### 6.4 Regeneration

Regeneration is preview-first and field-selective. It may replace only fields whose current origin is `generated` and whose user explicitly selected refresh. It never overwrites `edited` fields, any target carrying approval evidence, or supported `supplied` fields without explicit per-field confirmation. One accepted regeneration is one revisioned document update.

## 7. Approval, validation, and staleness

### 7.1 Derived states

The UI states are derived, not stored as mutable enums:

- **Draft:** no current successful validation fingerprint.
- **Validated:** current candidate has no error diagnostics and its validation fingerprint matches.
- **Approved:** `approval.approved_fingerprint` equals the current approval fingerprint and dependencies are current.
- **Stale approval:** approval evidence exists but content, source basis, chapter basis, or target identity no longer matches.
- **Export eligible:** active, approved, not stale/orphaned, placeholder-free, and valid for the selected export.

Validation results are not durable truth. They are recomputed from the current candidate and dependencies.

### 7.2 Approval fingerprint

The approval fingerprint is lowercase SHA-256 over compact canonical JSON with recursively lexicographic object keys, array order preserved, UTF-8 encoding, and no insignificant whitespace. The fingerprint input is:

```json
{
  "algorithm":"wrld-youtube-metadata-approval/1.0",
  "target_key":"short:short-1",
  "target_reference":{},
  "creation_target_fingerprint":"...",
  "source_metadata_fingerprint":"...",
  "chapter_source_fingerprint":null,
  "resolved_metadata":{},
  "effective_chapters":null
}
```

It includes every resolved common metadata field, stable recording/assignment references, release association, and effective chapter entry. It excludes editor revision/save ID, lifecycle, array position, visual configuration, visual/template provenance, Creation visual approval, undo state, validation timestamps, and artifact paths populated later from verified render reports.

Approving stores exactly:

```json
{"approved_fingerprint":"<sha256>","approved_at":"2026-11-02T00:00:00Z"}
```

Approval requires zero errors. Approval and unapproval are explicit revisioned editor-state Saves. Metadata approval never changes Creation approval.

### 7.3 Approval invalidation

- Any exported-content edit makes approval stale.
- A relevant supplied/generated source-fingerprint change makes approval stale but preserves content.
- A recording or ordered Album assignment identity/hash change makes approval stale.
- A current chapter source or label change makes Album approval stale.
- Archive/restore alone preserves approval; archive prevents export.
- Reordering target cards alone preserves approval.
- Visual-only Creation changes preserve approval.
- Adding verified media/thumbnail artifact references preserves content approval; export preview separately validates those references.

### 7.4 Diagnostics

Every diagnostic is:

```json
{
  "code":"TITLE_REQUIRED",
  "severity":"error",
  "target_key":"single:single-1",
  "field":"/content/title/value",
  "message":"A title is required for approval and export.",
  "details":{}
}
```

`target_key` and `field` may be null only for document/export-wide diagnostics. Stable initial codes:

Errors: `TITLE_REQUIRED`, `TITLE_TOO_LONG`, `DESCRIPTION_TOO_LONG`, `TAGS_TOO_LONG`, `TAG_INVALID`, `HASHTAG_INVALID`, `IDENTITY_REQUIRED`, `PLACEHOLDER_UNKNOWN`, `PLACEHOLDER_UNRESOLVED`, `TARGET_REFERENCE_INVALID`, `SOURCE_REFERENCE_CHANGED`, `CHAPTER_SOURCE_REQUIRED`, `CHAPTER_SOURCE_STALE`, `CHAPTER_ENTRY_INVALID`, `APPROVAL_REQUIRED`, `APPROVAL_STALE`, `ARTIFACT_REFERENCE_CHANGED`.

Warnings: `DUPLICATE_TITLE`, `DUPLICATE_TAG`, `DUPLICATE_CREDIT`, `ARCHIVED_TARGET`, `ORPHANED_TARGET`, `SOURCE_METADATA_CHANGED`, `CHAPTERS_NOT_YOUTUBE_ELIGIBLE`, `ARTIFACT_UNAVAILABLE`, `GENERATED_FIELD_REFRESH_AVAILABLE`.

Warnings do not block approval/export unless another explicit error applies. Duplicate titles remain warnings.

## 8. Chapter authority

### 8.1 Authoritative dependency

WU5 never probes audio or computes offsets. It consumes a narrow read-only `AuthoritativeChapterSource` adapter backed by WU3A's existing sample timeline and `chapters_text` policy. The adapter returns ordered `track_id`, floored `start_seconds`, source label, canonical LF chapter text, and its SHA-256.

When a verified `output/metadata/chapters.txt` and matching `wrld-render-report/1.0` chapters artifact exist, their artifact SHA-256 is also recorded. The canonical text SHA must match the adapter output. A mismatch is `CHAPTER_SOURCE_STALE`; WU5 does not choose one silently.

Current `wrld-render-report/1.0` does not require a typed timeline inside `history[].result`; parsing `chapters.txt` alone loses stable track IDs. The narrow adapter is therefore an implementation dependency. It reuses WU3A's existing timeline domain service and does not create a second algorithm or new artifact.

### 8.2 Creation Album-plan limitation

WU3A's current timeline is authoritative for the normalized manifest Album, while Creation v4 can hold multiple arbitrary Album plans. An Album plan receives a chapter source only when its ordered assignments map one-to-one by verified audio identity/SHA-256 to the normalized WU3A track sequence. Duplicate, omitted, added, or reordered assignments are not canonical-equivalent.

Non-equivalent plans remain editable but receive `CHAPTER_SOURCE_REQUIRED` and cannot be approved/exported as Album metadata. Defining a renderer/timeline for arbitrary Creation v4 Album plans remains WU6. WU5 must not pre-empt that decision.

### 8.3 Editing and serialization

- `track_id` and `start_seconds` are read-only.
- Labels are editable, max 200 code points, without CR/LF.
- The first timestamp must be zero; timestamps must be strictly increasing.
- Fewer than three entries or any adjacent interval under ten seconds produces `CHAPTERS_NOT_YOUTUBE_ELIGIBLE`, not a timing rewrite.
- Effective lines use WU3A formatting: `MM:SS label` below one hour or `H:MM:SS label` at/above one hour, LF separators, final LF in the canonical block.
- `{{chapters}}` resolution removes the final LF before embedding in description text.
- Source changes retain old labels and approval, mark them stale, and require an explicit reconcile preview. Labels may be offered for carry-forward only by identical stable `track_id`; timestamp changes still require confirmation.

## 9. Portable export

### 9.1 Top level and ordering

The exact top-level fields are:

```json
{
  "contract_version":"wrld-youtube-metadata/1.0",
  "project_id":"project-uuid",
  "revision":1,
  "content_fingerprint":"<sha256>",
  "albums":[],
  "singles":[],
  "shorts":[]
}
```

Within each type, selected targets follow current Creation v4 order. The export includes only explicitly selected, active, approved, current targets. Empty type arrays are valid. Archived and orphaned targets never appear.

`content_fingerprint` uses the same canonical JSON rules over each selected target's stable/type-specific references, resolved `metadata`, chapter-source fingerprint, and effective chapters. It excludes top-level contract version/revision, the fingerprint field itself, artifact references, approval timestamps, and approval wrapper objects. Reapproval or later verified-artifact discovery may therefore change export bytes without changing publishing-content identity.

The export revision is a portable materialization revision:

- first successful export is 1;
- byte-equivalent content reuses the existing file and revision without rewriting;
- an explicitly authorized different replacement is previous revision + 1.

### 9.2 Entry content

Each entry contains its canonical target key, type-specific stable references, resolved `metadata`, optional verified `media` and `thumbnail` references, and approval fingerprint/time. Album entries additionally contain ordered assignments, `chapter_source_sha256`, and effective chapters.

Artifact references are either null or `{path,sha256}`. Paths must be forward-slash project-relative references beginning `output/`; no drive, username, library root, source path, repository path, or browser-supplied filesystem path is permitted. Null is a warning, not an error, because metadata may be prepared before WU6 renders media.

### 9.3 Selection and atomicity

Export requests carry an explicit nonempty unique list of target keys. The selected set is all-or-nothing: one ineligible target prevents any file write. An empty selection is invalid. Unselected targets remain untouched in editor state and absent from that materialization.

Portable JSON is UTF-8 without BOM, two-space indentation, LF line endings, schema field order, `ensure_ascii=false`, and one final LF. Fingerprint canonicalization is compact and key-sorted as defined above; display serialization and fingerprint serialization are deliberately distinct.

## 10. Collision and replacement

Export is a separate explicit operation and does not mark targets approved.

1. Preview validates the saved editor revision and selected keys, resolves placeholders/artifacts, reads any existing export, and returns the exact proposed document, bytes SHA-256, content fingerprint, predicted export revision, diagnostics, and existing-file SHA-256 if present.
2. Execute repeats all validation under the project boundary and requires the preview fingerprint.
3. If no destination exists, `replace_existing` must be false and the file is atomically published.
4. If a byte-equivalent owned export exists, execution reports verified reuse without rewriting.
5. If different bytes exist, execution fails unless `replace_existing=true` and `expected_existing_sha256` exactly matches the current file.
6. A schema-valid file with another project ID, unsupported version, invalid JSON, or unrecognized ownership is never replaced by this v1 operation.
7. Write a uniquely named owned staging file in `output/metadata/`, flush and validate it, then use same-volume atomic replacement. On any failure, remove only the owned staging file and preserve the previous destination byte-for-byte.

No export operation changes source files, Creation, editor state, render report, chapters, or upload state.

## 11. Approved project-scoped API

All responses use the existing `wrld-api-error/1.0` envelope. Request-validation failures are structured and never expose absolute paths. The base is:

`/api/v1/projects/{project_id}/youtube-metadata`

### 11.1 Editor state

| Method/path | Request | Success | Side effects |
| --- | --- | --- | --- |
| `GET /youtube-metadata` | none | Editor document | None; 404 if not initialized |
| `POST /youtube-metadata/initialize` | `{save_id, creation_revision, creation_state_digest}` | Revision-1 editor document, 201 | Creates only when absent and Creation v4 basis matches |
| `PUT /youtube-metadata` | `{expected_revision, save_id, state}` | Saved editor document | One atomic revision-safe Save |

Initialization fails with 409 if state exists or the supplied Creation basis is stale. It never upgrades Creation or imports legacy metadata.

### 11.2 Validation and approval

`POST /youtube-metadata/validate`

Request:

```json
{"state":{},"mode":"draft","target_keys":["album:album-plan-1"]}
```

`mode` is `draft`, `approval`, or `export`. `target_keys` may be null for all targets. The response contains `valid`, canonical per-target approval fingerprints when computable, and ordered diagnostics. It is read-only and may validate an unsaved candidate.

Approval itself is an ordinary PUT of a candidate whose `approval` equals the server-computed current fingerprint. The backend rejects a client-invented or stale fingerprint atomically.

### 11.3 Reconciliation

| Method/path | Behavior |
| --- | --- |
| `POST /youtube-metadata/reconcile-preview` | Read-only diff against current Creation/source/chapter state; reports new, archived, restored, orphaned, stale, and refreshable fields |
| `POST /youtube-metadata/reconcile` | `{expected_revision,save_id,preview_fingerprint,actions}`; applies the confirmed complete candidate as one document revision |

Default actions add new targets and update lifecycle/order. Refreshing any existing field, carrying a chapter label, or importing a changed supplied value must be individually represented in `actions`. Missing actions never imply overwrite.

### 11.4 Export

`POST /youtube-metadata/export-preview`

```json
{"expected_revision":4,"target_keys":["album:album-plan-1","short:short-1"]}
```

Returns the exact proposed portable document, eligibility, diagnostics, preview fingerprint, proposed bytes SHA-256, predicted export revision, and current destination SHA-256/null. No write.

If the selected set is ineligible, no schema-valid portable document exists because every portable entry requires genuine approval evidence. In that case preview returns `METADATA_VALIDATION_FAILED` with ordered diagnostics in the existing error envelope; it must not fabricate approval evidence or timestamps merely to populate a transient `document`. The success response's `eligible` value is therefore always true and remains explicit for transport compatibility.

`POST /youtube-metadata/exports`

```json
{
  "expected_revision":4,
  "target_keys":["album:album-plan-1","short:short-1"],
  "preview_fingerprint":"<sha256>",
  "replace_existing":false,
  "expected_existing_sha256":null
}
```

Returns the portable document plus `path`, `sha256`, `byte_size`, `revision`, and `reused`. It writes only after all checks succeed.

### 11.5 Exact transient payloads

These transport wrappers are approved API shapes, not additional persisted document contracts.

Validation response:

```json
{
  "contract_version":"wrld-youtube-metadata-validation/1.0",
  "mode":"approval",
  "valid":false,
  "target_fingerprints":[{"target_key":"short:short-1","approval_fingerprint":null}],
  "diagnostics":[]
}
```

Diagnostics use the exact shape in Section 7.4 and are ordered by current target order, then field JSON pointer, severity (`error` before `warning`), and code.

Reconcile-preview request:

```json
{
  "expected_revision":4,
  "refresh_fields":[{"target_key":"single:single-1","field":"title"}],
  "carry_chapter_labels":[{"target_key":"album:album-plan-1","track_id":"track-1"}]
}
```

`field` is one of the twelve common content field names from Section 5.1. Mandatory identity/lifecycle/order reconciliation is always included; the two arrays request optional overwrites only. The response is:

```json
{
  "contract_version":"wrld-youtube-metadata-reconcile-preview/1.0",
  "editor_revision":4,
  "creation_revision":9,
  "preview_fingerprint":"<sha256>",
  "changes":[{"kind":"add_target","target_key":"short:short-2","field":null}],
  "candidate":{},
  "diagnostics":[]
}
```

`changes[].kind` is exactly `add_target`, `archive_target`, `restore_target`, `orphan_target`, `reorder_target`, `refresh_field`, `refresh_chapter_source`, or `carry_chapter_label`. Execute reconciliation repeats `expected_revision`, `save_id`, the two selection arrays, and `preview_fingerprint`; success returns the saved editor document directly.

Export-preview response:

```json
{
  "contract_version":"wrld-youtube-metadata-export-preview/1.0",
  "editor_revision":4,
  "eligible":true,
  "preview_fingerprint":"<sha256>",
  "proposed_sha256":"<sha256>",
  "predicted_export_revision":1,
  "existing_sha256":null,
  "document":{},
  "diagnostics":[]
}
```

Execute-export response:

```json
{
  "contract_version":"wrld-youtube-metadata-export-result/1.0",
  "path":"output/metadata/youtube_metadata.json",
  "sha256":"<sha256>",
  "byte_size":1234,
  "revision":1,
  "reused":false,
  "document":{}
}
```

The preview fingerprint covers editor revision, selected keys in request order, current target approval fingerprints, resolved artifact references, proposed bytes SHA-256, predicted export revision, and existing destination SHA-256/null. Any change makes execution fail rather than silently rebuilding a different export.

### 11.6 Approved stable error codes

- 404: `METADATA_STATE_NOT_FOUND`, `METADATA_TARGET_NOT_FOUND`
- 409: `CREATION_UPGRADE_REQUIRED`, `METADATA_ALREADY_INITIALIZED`, `REVISION_CONFLICT`, `SOURCE_CHANGED`, `METADATA_RECONCILE_STALE`, `METADATA_EXPORT_PREVIEW_STALE`, `METADATA_EXPORT_EXISTS`, `METADATA_EXPORT_CHANGED`, `METADATA_EXPORT_OWNERSHIP_UNKNOWN`
- 422: `METADATA_STATE_INVALID`, `METADATA_VALIDATION_FAILED`, `METADATA_APPROVAL_INVALID`, `METADATA_EXPORT_SELECTION_INVALID`
- 500: existing `COMMIT_INDETERMINATE`, `STORAGE_ERROR`, `INTERNAL_ERROR`
- 503: existing `PROJECT_UNAVAILABLE`

## 12. Initialization, existing projects, and legacy material

### 12.1 Existing and new projects

- Metadata initialization requires an available project and Creation v4.
- GET never creates state.
- Import/scan does not create metadata because registration may be manifestless and no Creation targets may yet exist.
- The explicit initialize operation creates deterministic drafts for all current active and archived targets.
- A later import-to-metadata convenience trigger may call the same application use case only after an approved lifecycle specifies when Creation v4 exists; it cannot be a separate generator.

This narrows Doc 41's older “generate on successful import” direction to the current Creation-owned target model without inventing targets during Import.

### 12.2 New or changed compositions

- GET and Creation Save may report reconciliation needed but never rewrite metadata.
- Reconcile adds missing stable targets, updates lifecycle, and orders current targets by Creation order.
- Existing values and approval evidence are preserved.
- Source changes produce stale diagnostics and refresh choices.
- Orphans remain last in stable prior order until an explicit delete operation is separately approved; v1 has no destructive metadata deletion route.

### 12.3 Legacy/root metadata

The known root-level draft identity `wrld-youtube-publishing/0.1-draft` has no approved checked-in schema or adapter fixture. V1 therefore does not auto-read or map it.

A future legacy import requires:

1. a consented representative fixture and approved adapter;
2. server-owned bounded read under the project boundary;
3. schema/version recognition;
4. a read-only mapping preview with per-field provenance and unmapped fields;
5. explicit target and field selection; and
6. one revision-safe metadata-state Save.

The source file is never moved, rewritten, renamed, or deleted. Unsupported or ambiguous legacy content produces a diagnostic and no mutation.

## 13. Representative examples

The examples abbreviate SHA-256 values as repeated characters only for readability; production fixtures must use valid computed values.

### 13.1 Album editor target

```json
{
  "target_key":"album:album-plan-1",
  "target":{"kind":"album","album_plan_id":"album-plan-1"},
  "lifecycle":"active",
  "basis":{
    "creation_target_fingerprint":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "source_metadata_fingerprint":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "chapter_source_fingerprint":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  },
  "content":{
    "title":{"value":"Echoes of Asia","origin":"generated","source_fingerprint":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
    "description":{"value":"Echoes of Asia\n\n{{chapters}}","origin":"generated","source_fingerprint":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
    "tags":{"value":[],"origin":"generated","source_fingerprint":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
    "hashtags":{"value":[],"origin":"generated","source_fingerprint":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
    "artist_name":{"value":"WRLD-FI","origin":"supplied","source_fingerprint":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
    "channel_name":{"value":"WRLD-FI","origin":"supplied","source_fingerprint":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
    "credits":{"value":[],"origin":"generated","source_fingerprint":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
    "links":{"value":[],"origin":"generated","source_fingerprint":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
    "visibility":{"value":"private","origin":"generated","source_fingerprint":null},
    "pinned_comment":{"value":null,"origin":"generated","source_fingerprint":null},
    "release_album_plan_id":{"value":null,"origin":"generated","source_fingerprint":null},
    "related_video_url":{"value":null,"origin":"generated","source_fingerprint":null}
  },
  "chapters":{
    "source":{"source_kind":"verified_artifact","canonical_text_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","artifact_path":"output/metadata/chapters.txt","artifact_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","render_report_revision":2},
    "entries":[{"index":0,"track_id":"track-1","start_seconds":0,"source_label":"First Light","label":{"value":"First Light","origin":"generated","source_fingerprint":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"}}]
  },
  "approval":null
}
```

### 13.2 Single and Short target differences

```json
{
  "single":{
    "target_key":"single:single-1",
    "title":"First Light",
    "description":"First Light",
    "hashtags":[],
    "recording_asset_id":"asset-audio-1",
    "release_album_plan_id":"album-plan-1"
  },
  "short":{
    "target_key":"short:short-1",
    "title":"First Light #Shorts",
    "description":"First Light\n\nWatch the full compilation: {{compilation_url}}",
    "hashtags":["#Shorts"],
    "recording_asset_id":"asset-audio-1",
    "release_album_plan_id":"album-plan-1"
  }
}
```

The abbreviated example is explanatory, not a third schema.

### 13.3 Portable export excerpt

```json
{
  "contract_version":"wrld-youtube-metadata/1.0",
  "project_id":"9bb056bb-6325-429e-963e-a3d4f2edd77d",
  "revision":1,
  "content_fingerprint":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
  "albums":[],
  "singles":[{
    "target_key":"single:single-1",
    "single_id":"single-1",
    "recording":{"asset_id":"asset-audio-1","expected_sha256":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"},
    "metadata":{"title":"First Light","description":"First Light","tags":[],"hashtags":[],"artist_name":"WRLD-FI","channel_name":"WRLD-FI","credits":[],"links":[],"visibility":"private","pinned_comment":null,"release_album_plan_id":"album-plan-1","related_video_url":null},
    "media":null,
    "thumbnail":null,
    "approval":{"fingerprint":"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff","approved_at":"2026-11-02T00:00:00Z"}
  }],
  "shorts":[]
}
```

## 14. WU5 implementation checklist after approval

1. Promote the approved schemas into `contracts/schemas/` and generate TypeScript transports.
2. Add schema and representative contract fixtures, including empty and Unicode content.
3. Add a metadata `ProjectDocumentStore` under a distinct state partition.
4. Implement deterministic initialization, reconciliation preview/apply, validation, approval fingerprinting, and export preview/execute as application services.
5. Implement the narrow WU3A-backed chapter-source adapter without probing or duplicating timeline math.
6. Wire project-scoped FastAPI routes and existing error envelope/status mapping.
7. Add client functions and a Metadata Table/Detail workspace using the existing project selection and navigation guard.
8. Preserve local undo/redo and explicit revision-safe Save; keep filters/selections session-local.
9. Add source-fact read-only panels and per-field provenance.
10. Add confirmation for bulk edits, bulk approval, reconciliation, and export replacement.
11. Update Shell truthfully from unavailable only when the real backend capability exists.
12. Update Docs 07, 16, 19, 23, 26, 31, 41–43, README and CHANGELOG only as required to record the approved implementation and evidence.

## 15. Focused testing checklist

### Contracts and domain

- Both schemas accept representative Album/Single/Short documents and reject unknown fields.
- Key/reference agreement, unique identities, lifecycle, ordering, stable IDs, and Creation v4 basis.
- 99/100/101-code-point titles and 4,999/5,000/5,001-code-point resolved descriptions.
- Unicode, emoji, quotes, apostrophes, CR/LF, JSON round-trip, and deterministic canonical fingerprints.
- Exact 499/500/501 tag costs; whitespace quoting; comma/quote/control rejection; casefold duplicate warning.
- Placeholder allowlist, unknown placeholder, unresolved compilation URL, and chapter substitution.
- Generated/supplied/edited precedence and field-selective regeneration.
- Visual-only changes do not stale approval; source/content/chapter changes do.
- Archive/restore preserves content; orphan and new-target reconciliation never reassign identities.

### Chapters

- Exact WU3A timeline and chapter-text reuse without FFprobe.
- Verified artifact match/mismatch, missing render report, source preview, and canonical-equivalence admission.
- Non-equivalent Creation Album plan blocked without changing it.
- Label edit with immutable timestamp, reorder/change staleness, stable-track carry-forward confirmation.
- Fewer than three/under-ten-second warnings without rewritten timing.

### Persistence and API

- Explicit initialization, duplicate initialization, Creation precondition mismatch, and non-v4 rejection.
- Save/reload, idempotent save ID, stale revision, atomic schema rejection, and commit-indeterminate recovery.
- Reconcile preview/apply fingerprint race and one-revision atomicity.
- Validate unsaved candidate without persistence.
- Approval fingerprint server verification and stale approval preservation.
- Error-envelope status/code/details and no absolute path leakage.

### Export

- Explicit selected-set all-or-nothing eligibility.
- Active approved inclusion; archived/orphaned/unapproved/stale exclusion diagnostics.
- Deterministic ordering, UTF-8/LF, final LF, escaping, and byte/content fingerprints.
- First write, byte-identical reuse, collision rejection, expected-SHA replacement, changed-race rejection, invalid/foreign destination preservation, and staging cleanup.
- No source, Creation, render-report, chapters, or upload-state mutation.
- Artifact references are verified, portable, optional, and never inferred from filenames.

### Frontend

- Table/Detail shared draft store, selection/filtering, dirty target count, undo/redo, and navigation guard.
- Album/Single/Short selection, archived/orphaned filters, empty states, and large catalogs.
- Read-only source facts and editable publishing fields.
- Character/tag counters, inline diagnostics, provenance, stale approval, and accessibility.
- Bulk operation impact preview/confirmation and one undo entry.
- Save conflict retains unsaved edits; export replacement requires explicit confirmation.
- WU1–WU4 regression, including Creation v4 visuals/templates/approvals remaining byte-for-byte unchanged.

## 16. Approved decisions

The November 2, 2026 approval accepts:

1. Accept the two contract identifiers and proposal schemas.
2. Accept all Creation v4 Albums, Singles, and Shorts as metadata targets rather than the older compilation-plus-Short scope.
3. Accept the literal minimal templates, `#Shorts` default, placeholder allowlist, and empty default tags.
4. Accept editable publishing artist/channel copies, free-text credit roles, and the proposed visibility enum.
5. Accept static one-time release association by unique Album membership.
6. Accept the tag counting algorithm.
7. Accept target-level approval and the exact fingerprint boundary.
8. Accept the WU3A chapter-source adapter and the block on non-canonical Album plans until WU6.
9. Accept explicit initialization/reconciliation instead of write-on-GET or import-time mutation.
10. Accept selected-set all-or-nothing export and compare-and-swap replacement.
11. No automatic legacy import. A representative `wrld-youtube-publishing/0.1-draft` fixture and adapter remain a separate later decision.

## 17. Approval clarifications

The approval additionally locks these interpretations:

1. Doc 51 is authoritative for WU5, and both schemas participate in the normal production-schema/generated-type workflow.
2. All Creation v4 Albums, Singles, and Shorts are metadata targets.
3. Source metadata, editable publishing metadata, and Creation visual settings remain separate authorities.
4. Noncanonical Album plans remain editable and saveable. Only chapter-dependent approval/export is blocked until WU6 supplies a verified mapping.
5. Publishing URLs, credits, identities, and timestamps are never invented. Unresolved placeholders block approval/export until resolved or explicitly removed.
6. Initialization, reconciliation, Save, approval, and export remain explicit and revision-safe.
7. Legacy drafts and production project data are never modified automatically.

## 18. Implementation candidate and verification record

The November 3, 2026 working tree implements the approved WU5 contract as an uncommitted candidate. The two approved schemas are in the production schema/generated-type workflow. Backend application services and project-scoped routes implement explicit initialization, revision-safe Save, validation, server-verified target approval, preview-confirmed reconciliation, and selected-set atomic export with compare-and-swap replacement. The React Metadata workspace provides shared Table/Detail editing, provenance, immutable WU3A timestamps with editable labels, local undo/redo, dirty-navigation protection, explicit Save, per-target approval, reconciliation confirmation, and export confirmation.

No implementation path automatically imports a legacy draft or initializes production data. No WU6 render orchestration was added.

Verification evidence from the implementation session:

- Backend full non-FFmpeg regression against the final candidate: 1,161 passed, 10 environment-specific skips, 55 FFmpeg-marked tests deselected, 3 deprecation warnings.
- Final focused WU5/schema/shared-store regression after the last hardening changes: 10 passed.
- Frontend full regression: 110 passed.
- TypeScript typecheck, ESLint, generated-contract drift check, production Vite build, Python compile, and `git diff --check`: passed.
- The FFmpeg-marked media suites were not rerun because WU5 does not change renderer behavior; the full non-FFmpeg suite retains WU1–WU4 coverage. Manual browser acceptance remains separate from this implementation record.
