# 49 — WU4 template-based Editor Creation contract proposal

**Status (2026-10-31): IMPLEMENTED CANDIDATE; AUTOMATED VERIFICATION COMPLETE; MANUAL BROWSER ACCEPTANCE PENDING.**

**Phase 4 supersession (2026-11-02):** This document remains the historical authority for Creation v2 visual-field semantics, geometry, dependency recovery, and v1→v2 migration. Its live shared-template dependency and shared-edit workflow applies only to v2/v3 compatibility. Revised [Doc 50](50_WU4_EDITOR_AVAILABILITY_AND_TEMPLATE_ASSIGNMENT_UX_PROPOSAL.md) is the specific authority for Creation v4 composition-owned settings, reusable presets, v3→v4 migration, and cleanup. Where the documents conflict about ownership or Editor workflow, Doc 50 controls v4 and future Phase 4B behavior.

This document records the approved design rationale for the smallest durable contract needed for a template-based visual Editor. The implementation candidate now includes the additive production schema, generated client, explicit migration, version-aware backend persistence, and browser authoring preview described below. It does not add a Creation-template renderer or modify any WU3 rendering contract. Docs 31 and 41–48 remain controlling for their approved scope. The four WU4 UX follow-up refinements already present in the working tree are preserved.

Implementation status:

- `contracts/schemas/creation-state-v2.schema.json` is the executable strict v2 schema; the v1 schema remains unchanged and readable.
- The existing Creation GET/PUT boundary accepts v1 and v2, retains explicit Save and optimistic revision checks, and permits only the deterministic explicit v1-to-v2 upgrade.
- The Review Editor supports Album, Single, and Short targets; project-local shared templates; Customize copy; secure imported-image dependencies and recovery; typed controls; approximate image/audio preview; undo/redo; and revision-safe Save.
- Automated contract, backend, frontend, type, lint, generated-contract, and production-build checks have passed. Manual browser, responsive-layout, keyboard, reduced-motion, and visual-quality acceptance remains pending.
- Final rendering, authoritative portrait output, renderer parity, advanced composition, and other WU5–WU8 capabilities remain deferred.

## 1. Scope and authority

The proposal extends the durable Creation document rather than reviving the manifest-specific `wrld-editor-state/1.0` document. The proposed new document identity is `wrld-creation-state/2.0`; `wrld-creation-state/1.0` remains readable and unchanged.

Approved product direction represented here:

- one continuous still-image background for a video;
- template editing, not a timeline;
- no background switching, splicing, keyframes, live genre inheritance, layers, titles, procedural sources, or imported-video sources;
- 16:9 authoring for Album and Single targets and 9:16 authoring for Short targets;
- project-local shared templates with an explicit copy-on-write **Customize** action;
- approximate browser previews until a separately approved renderer mapping passes parity review.

Creation remains a planning document. WU6 owns authoritative render-plan/profile integration, WU7 owns advanced layered composition, and WU8 owns imported video and clip playlists. Historical WU3 contracts and artifacts are not modified.

## 2. Proposed durable shape

The following remains an illustrative design excerpt rather than the executable schema itself. The implementation adds the corresponding `creation-state-v2.schema.json` and leaves the v1 schema unchanged.

```jsonc
{
  "contract_version": "wrld-creation-state/2.0",
  // all v1 envelope fields remain
  "visual_templates": [
    {
      "visual_template_id": "visual-template-7fa4...",
      "label": "Portrait visual",
      "canvas": { "aspect_ratio": "9:16" },
      "background_image": {
        "asset_id": "asset-opaque-id",
        "expected_sha256": "<64 lowercase hex characters>"
      },
      "geometry": {
        "fit_mode": "cover",
        "focal_x": 0.5,
        "focal_y": 0.5
      },
      "camera": { "mode": "bounded", "max_zoom": 1.04 },
      "visualizer": { "enabled": true, "bar_count": 24, "opacity": 0.65 },
      "progress": { "enabled": true },
      "color_treatment": {
        "mode": "custom",
        "hex": "#416E9D",
        "intensity": 0.18
      }
    }
  ],
  "albums": [{
    // all v1 album fields remain
    "visual_template_id": null
  }],
  "singles": [{
    // all v1 Single fields remain
    "visual_template_id": "visual-template-landscape"
  }],
  "shorts": [{
    // all v1 Short fields remain
    "visual_template_id": "visual-template-portrait"
  }]
}
```

`visual_templates` is a required array in v2. `visual_template_id` is a required nullable field on every album plan, Single, and Short. `null` means that target has no visual template yet; it never means “inherit.” A referenced template whose `background_image` is `null` is an incomplete draft, not a solid-color or implicitly selected background.

All template IDs use the existing stable-ID constraints and share the document-wide uniqueness namespace with album-plan, assignment, Single, and Short IDs. References must resolve within the same Creation document and project. No template contains a filesystem path, URL, recording identity, target identity, approval, or renderer profile.

### 2.1 Proposed definitions

```jsonc
{
  "$defs": {
    "visualTemplateRef": {
      "oneOf": [{ "$ref": "#/$defs/id" }, { "type": "null" }]
    },
    "visualTemplate": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "visual_template_id", "label", "canvas", "background_image",
        "geometry", "camera", "visualizer", "progress", "color_treatment"
      ],
      "properties": {
        "visual_template_id": { "$ref": "#/$defs/id" },
        "label": { "type": "string", "minLength": 1, "maxLength": 128 },
        "canvas": {
          "type": "object",
          "additionalProperties": false,
          "required": ["aspect_ratio"],
          "properties": { "aspect_ratio": { "enum": ["16:9", "9:16"] } }
        },
        "background_image": {
          "oneOf": [
            { "type": "null" },
            {
              "type": "object",
              "additionalProperties": false,
              "required": ["asset_id", "expected_sha256"],
              "properties": {
                "asset_id": { "$ref": "#/$defs/id" },
                "expected_sha256": { "$ref": "#/$defs/sha256" }
              }
            }
          ]
        },
        "geometry": {
          "type": "object", "additionalProperties": false,
          "required": ["fit_mode", "focal_x", "focal_y"],
          "properties": {
            "fit_mode": { "enum": ["contain", "cover"] },
            "focal_x": { "type": "number", "minimum": 0, "maximum": 1 },
            "focal_y": { "type": "number", "minimum": 0, "maximum": 1 }
          }
        },
        "camera": {
          "type": "object", "additionalProperties": false,
          "required": ["mode", "max_zoom"],
          "properties": {
            "mode": { "enum": ["static", "bounded"] },
            "max_zoom": { "type": "number", "minimum": 1, "maximum": 1.05 }
          }
        },
        "visualizer": {
          "type": "object", "additionalProperties": false,
          "required": ["enabled", "bar_count", "opacity"],
          "properties": {
            "enabled": { "type": "boolean" },
            "bar_count": { "type": "integer", "minimum": 8, "maximum": 64 },
            "opacity": { "type": "number", "minimum": 0.1, "maximum": 1 }
          }
        },
        "progress": {
          "type": "object", "additionalProperties": false,
          "required": ["enabled"],
          "properties": { "enabled": { "type": "boolean" } }
        },
        "color_treatment": {
          "oneOf": [
            {
              "type": "object", "additionalProperties": false,
              "required": ["mode"], "properties": { "mode": { "const": "none" } }
            },
            {
              "type": "object", "additionalProperties": false,
              "required": ["mode", "hex", "intensity"],
              "properties": {
                "mode": { "const": "custom" },
                "hex": { "type": "string", "pattern": "^#[0-9A-Fa-f]{6}$" },
                "intensity": { "type": "number", "minimum": 0, "maximum": 0.6 }
              }
            }
          ]
        }
      }
    }
  }
}
```

The compact authoring fields intentionally do not copy WU3's landscape pixel geometry, camera path, easing, analysis windows, glow, player overlay, or renderer settings. A later WU6 adapter must either map these values to an approved renderer generation or report the target non-renderable. It may not fill missing render decisions silently.

## 3. Canvas and geometry semantics

The canvas is a normalized rectangle with width:height equal to the declared aspect ratio; it does not select a pixel resolution or output profile. Album plans and Singles may reference only 16:9 templates. Shorts may reference only 9:16 templates. Sharing is therefore limited to targets with the same aspect ratio. A future “copy to another aspect” action must create a new template and require geometry review; it is not a shared reference.

Focal coordinates are measured after normal display-orientation decoding: `(0,0)` is top-left, `(1,1)` is bottom-right, and the default for each axis is `0.5`. Scaling is uniform and may scale up or down; stretching is forbidden. Decoded alpha is composited over opaque black.

For source dimensions `Iw × Ih` and canvas dimensions `Cw × Ch`:

- **Contain:** `s = min(Cw/Iw, Ch/Ih)`.
- **Cover:** `s = max(Cw/Iw, Ch/Ih)`.
- In both cases, `Rw = Iw*s`, `Rh = Ih*s`, `x = (Cw-Rw)*focal_x`, and `y = (Ch-Rh)*focal_y`.
- The scaled image is placed at `(x,y)` and clipped to the canvas.
- With Contain, positive unused space is opaque black padding. Focal values align the image within that unused axis; they do not crop it.
- With Cover, negative unused space is crop overflow. Focal `0`, `0.5`, and `1` align the source's left/top, center, and right/bottom edges respectively.

Geometry is required even when `background_image` is null. This preserves fit and focal choices independently from source identity and makes typed geometry authoritative immediately. New templates begin with `contain`, `focal_x: 0.5`, and `focal_y: 0.5`.

`camera.mode = static` applies no camera transform, but `max_zoom` remains stored as an inactive value so enabling motion later does not discard a prior choice. `bounded` records only the approved authoring intent and maximum zoom, never exceeding 1.05×. It does not define a WU3 camera path, cycle, easing, or return policy. Browser movement is an approximation; an authoritative trajectory remains a WU6 renderer-contract decision.

## 4. Image dependency validation and recovery

A non-null background references exactly one asset in the current project's inventory by `asset_id` and the strong SHA-256 selected by the user. PNG, JPEG, and safe single-frame WebP may be authored because the existing secure image endpoint can inspect them. This does not make WebP, portrait output, Cover fitting, or asset-ID selection renderable by current WU3 profiles.

### 4.1 Save rules

1. Schema, unique identities, reference existence, and target/template aspect compatibility are validated first.
2. Creating or replacing a background requires an inventoried, non-excluded image that is present, strongly verified, safe single-frame PNG/JPEG/WebP, and whose current SHA-256 equals `expected_sha256` immediately before commit.
3. A newly linked target may not adopt a template whose dependency is currently missing, changed, unsupported, or excluded. The user must recover/replace/restore it first.
4. An already-saved target/template/background relationship is preserved when a later scan marks the image missing, changed, unsupported, or excluded. If the submitted candidate leaves that relationship unchanged, unrelated Creation edits may still be saved; the stale configuration is not removed or rewritten.
5. Changing an expected fingerprint is an explicit **Accept changed image** operation. It requires fresh strong verification of the current asset and invalidates approvals for every linked Single or Short because pixels may change.
6. Exclusion is a selection preference. New/replacement pickers omit excluded images, but exclusion never deletes or nulls an existing dependency. Restoring the asset in Import or replacing the dependency clears the condition.
7. A missing image may be recovered by restoring/relinking the same stable asset identity and matching fingerprint, or replaced explicitly with another safe image. No same-name or same-content substitution is automatic.
8. Backend validation remains authoritative. The browser never submits paths or URLs and cannot convert a thumbnail identity into a dependency identity.

The stale-unchanged exception in rule 4 is deliberate: it preserves the saved visual configuration and permits unrelated work while still preventing a new stale dependency. Existing v1 audio-dependency rules remain unchanged.

### 4.2 Derived issues

Issues are read-view annotations, not persisted fields, are excluded from `state_digest`, and are stripped from PUT payloads as in the current Creation service. Each visual issue carries `code`, nullable `visual_template_id`, nullable `asset_id`, nullable `relative_path`, nullable expected/observed SHA-256 values, and one or more affected target `{kind,id,status}` records. Template and asset identities are null for a target-level legacy-settings issue that has no typed template or image dependency. Proposed codes are:

- `VISUAL_SOURCE_REQUIRED`: a referenced template has `background_image: null`;
- `VISUAL_SOURCE_MISSING`;
- `VISUAL_SOURCE_CHANGED`;
- `VISUAL_SOURCE_EXCLUDED`;
- `VISUAL_SOURCE_UNSUPPORTED`;
- `LEGACY_VISUAL_SETTINGS_UNMAPPED`.

Missing/changed/unsupported conditions disable authoritative render eligibility, not inspection of the stored configuration. Excluded is a warning and selection-state mismatch, not proof that the file is unsafe. The UI must offer Restore in Import, Locate/Relink where the current asset flow supports it, Accept changed image, or Replace background as applicable.

## 5. Sharing, editing, and approval behavior

- Any number of active or archived same-aspect targets may reference one template. Archived targets retain their reference and count as users of that template.
- A pixel-affecting shared edit updates the one template and therefore every linked target in a single Creation change. Before applying it, the UI lists active and archived targets and requests explicit confirmation when more than one target is linked.
- A confirmed pixel-affecting edit clears `approved` and sets `customized: true` on every linked Single and Short, including archived ones. Album plans have no corresponding v1 approval/customization fields. A label-only edit warns that the label is shared but does not invalidate approvals.
- Switching, adding, or removing a target's template reference invalidates only that target's approval and marks that Single/Short customized.
- **Customize** deep-copies the complete template with a new stable ID and user-visible copy label, then repoints only the selected target. No inheritance or live link remains. Because the copied configuration is byte-equivalent, the copy action alone preserves approval; the first pixel-affecting edit to the copy invalidates it normally.
- Customize, shared edit, link/unlink, and Accept changed image each compute one complete next Creation state and enter local history as one undoable change.
- Unreferenced templates are retained. There is no automatic garbage collection. A later UI may explicitly delete an unreferenced template after confirmation; referenced-template deletion is invalid.
- Explicit Save, expected revision, save ID, canonical digest, read-after-write reconciliation after an indeterminate commit, dirty navigation guards, and local unsaved undo/redo retain their current semantics.

## 6. Revision-safe v1 migration

Migration is an explicit Save/Upgrade operation, not a GET side effect, startup rewrite, rescan effect, or inventory migration. A v2-capable client may construct an in-memory candidate from v1, but the existing v1 document remains authoritative until a PUT to the existing Creation save boundary succeeds with the expected v1 revision. One successful migration increments the revision once, uses one new save ID, recomputes the canonical digest, and atomically publishes v2. Retry uses the existing save-ID/digest reconciliation rules.

The transformation is deterministic and idempotent:

1. Preserve project ID, all album plans, assignments, Singles, Shorts, recording dependencies, target IDs, assignment IDs, order, archived states, excerpt ranges, origins, review flags, customization flags, approvals, preferred duration, and every generic `settings` JSON value and key/value structure exactly. Storage may retain its existing canonical serialization; preservation does not mean retaining insignificant source-file whitespace.
2. Add `visual_templates: []` and `visual_template_id: null` to every target.
3. Do not infer, select, or assign a background image.
4. Album plans and Singles receive no inferred template. Generic settings on them remain untouched.
5. Classify every active or archived Short's `settings.effects` using Section 6.1. For absent effects or a valid flat WU4 object, create one independent 9:16 template with `background_image: null`, typed geometry, and the mapped effective WU4 settings. Do not deduplicate equal configurations; automatic sharing would change independent-edit semantics.
6. The migration template ID is `visual-template-` plus the first 32 lowercase hex characters of SHA-256 over UTF-8 `project_id + "\0" + short_id + "\0wrld-creation-state/2.0"`. This makes retries stable without reusing a target identity.
7. The migration label is the first 128 characters of `Short visual ` followed by the stable Short ID. Labels need not be unique and are never identity.
8. If a deterministic template ID collides with any existing document identity, migration aborts atomically with `CREATION_STATE_INVALID`; it never chooses a random replacement on retry.
9. A historical nested or unknown effect dialect remains structurally unchanged, receives no typed template, retains `visual_template_id: null`, and produces a target-level `LEGACY_VISUAL_SETTINGS_UNMAPPED` issue. It never blocks migration of unrelated targets.
10. A clearly flat but invalid WU4 object aborts migration before any write with existing `CREATION_STATE_INVALID` plus the Short ID, `settings.effects` path, and validation reason. Values are never clamped or silently reinterpreted.

### 6.1 Deterministic effect-dialect classifier and mapping

When present, `settings.effects` must be a JSON object, not null, an array, or another JSON type. Numeric values must be finite. Classification is deterministic:

1. **Absent:** the `effects` key does not exist. Map the complete current effective WU4 defaults.
2. **Valid flat WU4:** the object contains only the recognized flat keys in the table below, and each present value has the required type and range. An empty object is valid. Merge it over the complete current defaults, then map the effective result.
3. **Historical nested or unknown dialect:** the value is a JSON object but contains an unrecognized key or a recognized key expressed as a nested object/array rather than the flat WU4 type. Preserve it unchanged, leave the Short's template reference null, and report `LEGACY_VISUAL_SETTINGS_UNMAPPED`. Do not attempt to infer its semantics.
4. **Clearly flat but invalid:** the object contains only recognized flat keys and at least one flat scalar has the wrong primitive type, a non-finite numeric value, or an out-of-range value. Reject the migration atomically with the diagnostic described in step 10 above.
5. **Invalid container:** a present `effects` value that is not a JSON object rejects migration with the same precise diagnostic. It is malformed data rather than an unknown object dialect.

The recognized flat key set is exactly `camera`, `zoom`, `bars`, `barCount`, `barOpacity`, `progress`, `tint`, `tintIntensity`, `positionX`, and `positionY`. Original `settings`, including the complete effects object and every unknown legacy value, is deep-copied unchanged regardless of whether a typed template is created.

Current Short effects are interpreted exactly as the current Editor does: absent recognized keys use its existing effective defaults, while present flat values must satisfy the ranges below.

| Current key | Effective default | v2 mapping |
| --- | ---: | --- |
| `camera` | `true` | Boolean; `true` → `camera.mode = bounded`; `false` → `static` |
| `zoom` | `1.04` | Finite number 1–1.05 → `camera.max_zoom` in both modes |
| `bars` | `true` | `visualizer.enabled` |
| `barCount` | `24` | `visualizer.bar_count`; integer 8–64 |
| `barOpacity` | `0.65` | `visualizer.opacity`; finite number 0.1–1 |
| `progress` | `true` | `progress.enabled` |
| `tint` | `#416E9D` | `color_treatment.mode = custom`, `hex = tint` |
| `tintIntensity` | `18` | Finite number 0–60; `color_treatment.intensity = tintIntensity / 100` |
| `positionX` | `50` | Finite number 0–100; `geometry.focal_x = positionX / 100` |
| `positionY` | `50` | Finite number 0–100; `geometry.focal_y = positionY / 100` |

Every mapped migration template uses `geometry.fit_mode: contain`. Its focal coordinates come from the merged effective `positionX/Y` values, so centered defaults become `0.5/0.5`. Typed geometry is authoritative as soon as migration succeeds; the v2 Editor never reads legacy settings later to recover fit or focal position. A static camera still stores the merged effective zoom.

Legacy `settings.treatment` and every other generic setting are preserved but not interpreted by this migration. A Short containing `settings.treatment` receives `LEGACY_VISUAL_SETTINGS_UNMAPPED` because no preset or genre mapping may be invented; the issue carries the mapped template ID when one exists and otherwise leaves it null. Other generic settings are not assumed to be visual solely because they are unknown. Migration itself preserves existing approvals because it either reifies current effective flat WU4 behavior or preserves an unknown dialect without reinterpretation; subsequent user-created or edited visual configuration follows Section 5 approval invalidation.

Add Missing Singles and bulk `+ All`/`− All` continue to operate on target objects exactly as now. A newly created or restored target does not acquire a visual template implicitly. Restoring an archived target restores its existing template reference.

### 6.2 Compatibility, Upgrade, and authority after migration

- A v2-aware reader accepts v1 and v2. Loading v1 does not construct or apply a migration candidate, change local history, or mark the workspace dirty.
- An explicit **Upgrade Creation document** action constructs the deterministic candidate, presents any unmapped legacy diagnostics, and submits the upgrade through the existing Creation Save boundary with the current expected revision and a new save ID. The document remains v1 unless that atomic Save succeeds.
- A client that supports only v1 must treat a v2 `contract_version` as unsupported and enter a read-only/reload-required state. It must not drop `visual_templates`, remove references, down-convert, or attempt a v1 save. No new public API error is required by this proposal; implementation must use the existing error envelope if a server response is needed and must not invent a new error code without separate contract approval.
- After v2 is saved, the referenced typed visual template is the sole visual-authoring authority. Preserved `settings.effects`, `settings.treatment`, and unknown legacy values are opaque compatibility data: the v2 Editor neither merges from nor dual-writes them. This prevents a stale legacy object from overriding a typed template.
- The migration-created template captures the current effective Short effect behavior once. Later typed template edits do not rewrite the preserved legacy settings. Removing a template reference does not reactivate legacy visual settings.
- `wrld-editor-state/1.0` remains a readable historical/manifest-specific document only. Creation v2 neither dual-writes it nor treats it as live inheritance. Any already-imported stable Short identity, range, settings, or approval remains represented through the Creation migration rules above.
- Existing Creation v1 documents may remain v1 indefinitely. Project scans, exclusions, Add Missing Singles, and Review navigation do not force an upgrade.
- A v1 document with a missing or changed audio dependency remains v1 until the user completes the existing Relink or Accept changed source recovery flow. Upgrade does not weaken the current v1 audio-dependency validation rule.
- A project has one authoritative Creation document generation at a time; side-by-side v1 and v2 writable copies are forbidden. The existing project key, revision compare-and-swap, save ID, and digest reconciliation select the winner.

## 7. Preview and renderer boundary

| Capability | Browser authoring behavior | Authoritative render status |
| --- | --- | --- |
| Image picker/inspection | Existing secure thumbnail and original-image endpoints; PNG/JPEG/single-frame WebP only | Asset-ID template input is not wired to WU3 |
| Background preview | Full secure image response after capability check; no source path exposure | No current Creation-template renderer |
| Contain/Cover/focal geometry | Implement the Section 3 formulas in CSS/canvas and label the complete preview **Approximate** | WU3 retains its approved manifest-backed contain/black-pad behavior only |
| Camera | Approximate bounded pan/zoom, never advertised as a WU3 path | WU6 mapping/profile decision required |
| Visualizer bars | Clearly approximate/decorative unless backed by approved observations; do not fabricate analyzer data | Current WU3 analysis remains available only through its own contracts |
| Progress | May follow the active browser audio position; Short preview is relative to its excerpt | Sample-accurate Album/Single/Short mapping requires WU6 approval |
| Short excerpt audio | Existing secure audio endpoint, capability check, one active playback controller, selected start/end stop boundary | Audio audition is not a render preview |
| Portrait 9:16 | Responsive browser canvas | No claim of current WU3 portrait output |
| Render Preview | Unavailable with a truthful reason for this contract generation | Phase 3/WU6 integration remains deferred |

Browser decoding, color management, timing, bar response, and camera interpolation may differ from FFmpeg. The visible approximation label remains present even when normalized geometry matches the contract.

## 8. Verification requirements

The implementation candidate includes focused coverage for the following requirements. These remain regression obligations for subsequent changes:

### Contract and backend

- v1 remains valid and unchanged; valid/invalid v2 fixtures cover every typed union, bound, unknown property, duplicate ID, dangling reference, and aspect mismatch.
- v1→v2 migration is atomic, deterministic, idempotent, revision-safe, and preserves all identities, ordering, archival state, approvals, settings, unknown values, and Short ranges.
- Exact absent/flat/historical/invalid dialect classification; default merging; finite numeric validation; target-level unmapped warnings; and no background inference.
- Typed fit/focal geometry and inactive maximum zoom survive migration without later reads from legacy settings.
- New/replacement image validation requires same-project safe image identity and fresh matching SHA-256; paths, URLs, cross-project IDs, animation, malformed and unsupported media fail.
- Missing/changed/excluded saved dependencies remain stored; unchanged stale relationships permit unrelated saves; new stale links fail; Accept changed image invalidates all affected approvals.
- Shared edits, Customize copies, archived references, no automatic cleanup, and document-wide ID uniqueness.
- Revision conflict and indeterminate-commit reconciliation remain byte-for-byte compatible with current behavior.

### Frontend

- 16:9 and 9:16 target restrictions, exact Contain/Cover/focal geometry, black padding, and narrow responsive layout.
- Shared-use impact warning includes archived targets; one confirmed edit creates one undo entry and invalidates only required approvals.
- Customize creates one independent stable template, preserves the source template and byte-equivalent approval, then isolates subsequent edits.
- Missing/changed/excluded/unsupported recovery actions and no silent default selection.
- Approximation and unavailable-render labels are always visible and accessible.
- Capability-aware image and audio controls, one active audio preview, Short excerpt end handling, cancellation/unmount safety, keyboard operation, focus visibility, and dirty-navigation protection.
- Existing Add Missing Singles, bulk operations, album ordering, tab restoration, Save/conflict, and project-switch regressions remain passing.

## 9. Implemented footprint

The implementation follows this bounded footprint:

1. Add `contracts/schemas/creation-state-v2.schema.json`, v2 valid/invalid fixtures, generated `frontend/src/api/generated/creation-state-v2.ts`, and contract checks. Do not alter v1.
2. Update `backend/src/wrld_video_studio/domain/wu4.py`, `application/project_workspace.py`, and the version-aware document validation/composition in `infrastructure/project_document_store.py` and `interfaces/http/app.py`. Keep the current Creation GET/PUT route and storage/revision protocol.
3. Extend existing WU4 backend contract/unit/integration tests; do not modify WU3 rendering.
4. Adapt `frontend/src/api/types.ts` and the existing Creation load/save adapter to read v1 and v2 and explicitly migrate only on Save.
5. Evolve `frontend/src/features/review/EditorWorkspace.tsx` and `CompositionPreview.tsx`; add at most one focused template-editor/resource-picker component if keeping those files readable. Reuse current secure asset URLs, audio-preview controller, StudioState tab/guard behavior, Creation history, and accessible controls.
6. Extend the existing Editor/Creation/App tests and styles. No new runtime dependency or state-management system is justified.

## 10. Approved new-template defaults and readiness

Newly created templates use these approved neutral defaults:

- `background_image: null`;
- `geometry.fit_mode: contain`;
- `geometry.focal_x: 0.5` and `geometry.focal_y: 0.5`;
- `camera.mode: static` with `camera.max_zoom: 1.04` retained as the inactive bounded-motion starting value;
- `visualizer.enabled: false`, with `bar_count: 24` and `opacity: 0.65` retained as inactive values;
- `progress.enabled: false`;
- `color_treatment.mode: none`.

These defaults apply only to brand-new templates. Migrated Shorts use the deterministic effective WU4 mapping in Section 6.1 and are never reset to neutral defaults.

No contract decision blocks the current implementation candidate. Renderer mapping, authoritative camera trajectory, portrait output, and parity acceptance are deliberately deferred capabilities, not gaps to fill in WU4. Manual browser acceptance is still required before this candidate is considered accepted.

## 11. Creation v4 and revised Doc 50 authority

[Doc 50](50_WU4_EDITOR_AVAILABILITY_AND_TEMPLATE_ASSIGNMENT_UX_PROPOSAL.md) now authorizes the additive strict `wrld-creation-state/4.0` generation. Every v4 composition owns a complete `visual_configuration`; nullable `source_visual_template_id` is historical provenance and never resolves pixels. The deterministic v3→v4 migration copies this document's complete concrete-template visual field set into each active and archived composition without changing effective visuals or approvals. Dangling references and null references without another complete authoritative configuration reject atomically rather than receiving invented defaults.

Sections 2–4 continue to define the visual field shapes, geometry, background dependency semantics, and approximation boundary reused by both templates and v4 composition configurations. Sections 5 and the shared-reference portions of Sections 8–10 are historical v2/v3 compatibility requirements, not the active v4 ownership model. V4 approval, template-library, cleanup, compatibility, and future Editor workflow rules are defined only by Doc 50.

WU3 rendering remains unchanged. WU6 owns authoritative v4 renderer admission and mapping and must read composition-owned settings rather than provenance or historical template references.
