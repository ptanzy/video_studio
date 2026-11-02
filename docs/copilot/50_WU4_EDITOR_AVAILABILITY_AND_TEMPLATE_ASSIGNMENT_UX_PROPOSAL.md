# 50 — WU4 composition-owned visuals and reusable-template workflow

**Status (2026-11-02): PHASE 4A AND PHASE 4B IMPLEMENTED CANDIDATES; PHASE 4B AUTOMATED VERIFICATION COMPLETE. PRODUCTION MIGRATION HAS NOT BEEN PERFORMED. INTERACTIVE BROWSER ACCEPTANCE AND WU6 RENDERING REMAIN PENDING.**

This document is the specific WU4 authority for Creation v4 visual ownership and the future reusable-template workflow. It supersedes the active shared-template editing model implemented during WU4 Phases 1–3 while retaining that work as historical context.

> **Templates supply settings; compositions own settings.**

A composition is one independently configured Album, Single, or Short video output. A template is a reusable preset whose complete visual configuration can be copied into a composition. A template family is a named library grouping of three independent concrete presets: Album, Single, and Short. Provenance records which template was last applied; it is historical origin information, never a live dependency.

Docs 31 and 49 retain authority for unrelated WU4 decisions. WU3 rendering contracts remain unchanged. WU6 owns authoritative Creation-to-renderer admission and mapping.

## 1. Governing product model

Every Creation v4 Album plan, Single, and Short stores a required `visual_configuration`. That configuration contains the complete pixel-affecting authoring state:

- `canvas`, including the target aspect ratio;
- nullable background-image identity and expected fingerprint;
- fit and focal geometry;
- camera mode and retained maximum zoom;
- visualizer configuration;
- progress configuration; and
- color treatment.

The composition-owned configuration is the sole visual-authoring source of truth for that output. Editing it never changes a template or another composition.

Each composition also stores nullable `source_visual_template_id`. It records the last applied preset when known. It may remain after local edits or after the source template is deleted. It never resolves effective settings, creates inheritance, causes automatic propagation, or becomes a missing visual dependency. Whether a composition still matches its source template is derived through exact visual equivalence and is not persisted.

Reusable templates retain stable `visual_template_id`, label, and the same complete visual field set. They are library records, not composition dependencies. Deleting a template cannot alter a composition's appearance because its settings were copied at application time.

## 2. Creation v4 contract

`wrld-creation-state/4.0` is a strict additive generation. V1, v2, and v3 schemas remain unchanged.

V4 retains project identity, revision/save/digest envelope, preferred Short duration, every composition identity and collection, active/archive state, Album assignments and ordering, recording dependencies, generic settings, approvals, customization flags, visual templates, and template-family registry. It replaces each composition's live nullable `visual_template_id` with:

```jsonc
{
  "visual_configuration": {
    "canvas": { "aspect_ratio": "16:9" },
    "background_image": null,
    "geometry": { "fit_mode": "contain", "focal_x": 0.5, "focal_y": 0.5 },
    "camera": { "mode": "static", "max_zoom": 1.04 },
    "visualizer": { "enabled": false, "bar_count": 24, "opacity": 0.65 },
    "progress": { "enabled": false },
    "color_treatment": { "mode": "none" }
  },
  "source_visual_template_id": null
}
```

This excerpt illustrates field placement; the executable schema is `contracts/schemas/creation-state-v4.schema.json`.

Albums and Singles require 16:9 configurations. Shorts require 9:16 configurations. Background identity, fingerprint, geometry, camera, visualizer, progress, and treatment retain the bounds and semantics established by Doc 49. A null background remains an incomplete visual draft; it is not an inferred black, solid, generated, or automatically selected source.

V4 retains the v3 family registry and its integrity rules. A family has exactly one Album 16:9 member, one Single 16:9 member, and one Short 9:16 member. Member identities are distinct and exclusive. Independent standalone templates remain valid.

## 3. Exact visual equivalence

Visual equivalence compares canonical complete configurations and includes every pixel-affecting field: background identity and fingerprint, canvas, fit, focal coordinates, geometry, camera, visualizer, progress, color treatment, and any future field admitted by a later strict contract.

Template identity, family identity, template label, and family display name are excluded. Names, filenames, aspects alone, or apparent similarity never establish equivalence. Unknown, partial, malformed, or future visual fields make equivalence unproven; they are never silently ignored.

The same comparison governs migration verification, approval preservation, template-match display, and cleanup analysis.

## 4. Explicit v3→v4 migration

Migration is a pure deterministic candidate transformation followed by the existing explicit, optimistic revision-safe Save. It never runs on GET, scan, navigation, startup, or ordinary Save. The source document is not mutated and no production project is migrated automatically.

For every active or archived Album, Single, and Short:

1. Resolve its non-null v3 concrete `visual_template_id`.
2. Copy the template's complete visual configuration into `visual_configuration`.
3. Store the former template ID in `source_visual_template_id`.
4. Remove the live composition `visual_template_id`.
5. Preserve all other composition fields, identities, ordering, approvals, customization, and status exactly.

Templates and families are retained unchanged. Migration does not create one template per composition, select a background, synthesize defaults, repair references, invalidate approval, or rewrite unrelated settings.

### 4.1 Lossless-migration preconditions

A non-null dangling v3 template reference rejects the complete migration with a target-specific `CREATION_STATE_INVALID` diagnostic. It is never repaired or replaced.

For a null v3 template reference, migration first checks whether that composition contains another authoritative, complete visual configuration. If present and valid, it becomes the v4 owned configuration and provenance is null. If absent, migration rejects atomically with a target-specific `authoritative_visual_configuration_missing` diagnostic.

Schema-valid v3 documents can contain null template references. Such documents lack resolvable authoritative visual settings and cannot be migrated losslessly without a separate remediation decision. Phase 4A does not invent that decision.

No invalid target causes partial output or a partial Save. V1→v4 and v2→v4 are available only through the established sequential v1→v2, v2→v3, and v3→v4 migrations, with each generation transition saved explicitly. Downgrade is forbidden.

## 5. Backend validation, persistence, and approvals

The existing Creation GET/PUT route, project key, expected revision, save ID, canonical state digest, indeterminate-commit reconciliation, and explicit Save model remain unchanged.

Backend v4 validation requires:

- a complete strict owned configuration on every composition;
- target-compatible aspect ratios;
- valid template and family identities and family membership;
- valid same-project background identity and fingerprint under the existing new-versus-unchanged dependency rules; and
- nullable provenance syntax without requiring provenance resolution.

New or changed composition backgrounds and new or changed template backgrounds require current supported project images and strong matching fingerprints. An already-saved missing, changed, unsupported, or excluded relationship remains stored when unchanged so unrelated work can still be saved and reviewed. Provenance never participates in dependency validation.

Pixel-changing composition edits invalidate that Single or Short's applicable approval. Pixel-equivalent changes preserve it. Template edits, template renames, family renames, regrouping, and template deletion do not change composition pixels and therefore do not invalidate composition approvals. Applying a preset invalidates approval only when its copied configuration is not visually equivalent to the composition's prior configuration.

Archived compositions receive the same migration, preservation, validation, and cleanup protection as active compositions.

## 6. Phase 4B Editor workflow

Phase 4B implements the approved actions below for native Creation v4 documents. V1–v3 retain their historical shared-template editor until each explicit sequential upgrade Save succeeds.

### Apply Template

Copy the selected template's complete visual configuration into the selected composition and record its ID as provenance. Application replaces the complete configuration rather than merging selected fields. Confirm before replacing meaningful local edits. Existing templates and other compositions do not change.

### Edit Composition

Edit the composition-owned configuration freely. Ordinary composition editing shows no shared-template warning because no shared record is being modified. Historical provenance may remain, while exact matching is derived dynamically.

### Save Composition

Persist the current owned configuration through the existing Creation Save/revision protocol. Saving a composition never updates a reusable template implicitly.

### Update Template

Explicitly copy the current composition configuration into a clearly identified existing template. Confirm the destination and consumer-independent library impact. Existing compositions that previously used the template remain unchanged because they already own their settings.

### Save as New Template

Create a new stable reusable preset from the composition's current configuration. This action is available even when provenance is null or refers to a removed template. It does not modify the composition unless the user separately applies the new preset.

### All Three Types

Explicitly synchronize the three reusable preset members of one family. Preserve every destination template's stable identity, family role, and required aspect ratio. Transfer the complete supported visual configuration under the established cross-aspect disclosure rules. Existing compositions do not change.

## 7. Template-library and family management

The Template Library, distinct from the Composition Editor, owns these operations:

- Create Family, including creation from an explicitly typed standalone preset;
- Rename Family;
- Remove Family Grouping while retaining all three templates;
- Delete Unused Family only when all members are safe under its guarded contract;
- edit Current Type Only;
- synchronize All Three Types; and
- create, retain, rename, and explicitly delete independent standalone presets.

Family names may repeat; stable IDs remain authoritative. Families are groupings of independent presets, not inheritance graphs. There is no General member or automatic propagation. Updating or deleting a library preset never rewrites existing compositions.

The former **This Composition Only** template-copy save scope is superseded by direct composition ownership. Ordinary composition editing no longer requires Current Type Only, All Three Types, or This Composition Only save-scope selection. Current Type Only and All Three Types remain explicit template-library operations.

## 8. Legacy template inventory and cleanup

Phase 4A provides pure analysis and a separate explicitly authorized apply foundation. Phase 4B exposes its classifications, reasons, associations, equivalence groups, counts, source revision/fingerprint, explicit authorization, and stale-plan rejection in the Template Library. `REVIEW_REQUIRED` and `RETAIN` records are never promoted or removed by cleanup.

Inventory reports total, family-member, standalone, active-associated, archived-associated, provenance-only, and unreferenced templates; exact equivalence groups; likely generated artifacts; retained templates; and uncertainty.

Each template is classified:

1. **PROVEN_DISPOSABLE** — deterministic identity, exact historical migration label, composition provenance, and exact owned-configuration equivalence jointly prove that the standalone record is a generated artifact whose removal cannot change visuals.
2. **REVIEW_REQUIRED** — naming, equality, or partial history suggests redundancy but does not prove safe intent.
3. **RETAIN** — family members, unique or intentional presets, and uncertain records.

Names, lack of current use, or equality with another template never establish disposability by themselves. Family members are protected.

The cleanup plan records candidates, classifications and reasons, active and archived associations, provenance-only references, exact-equivalence groups, retained IDs, counts before/after, source revision, and exact source fingerprint. Apply requires explicit caller authorization, recomputes analysis, rejects stale revision/fingerprint plans, and removes only `PROVEN_DISPOSABLE` records atomically. It preserves owned settings, approvals, customization, family integrity, and intentional presets. Historical provenance may safely point to a removed template.

There is no cleanup on read, migration, scan, ordinary Save, or application startup.

## 9. Frontend compatibility boundary

Phase 4A generated the v4 transport type and initially installed a non-destructive compatibility block. Phase 4B replaces that block with native v4 load, edit, preview, undo/redo, explicit Save, conflict preservation, and reload support. The v4 Editor reads and writes composition-owned `visual_configuration`; reusable-template edits are separate library operations. It cannot down-convert, strip owned settings, or save v4 as v1–v3.

V1, v2, and v3 remain editable through the historical paths. V1→v2, v2→v3, and v3→v4 are separate user-confirmed revision-safe Saves; there is no automatic read migration or implicit multi-generation upgrade. V3 preflight reports active/archived counts plus resolvable, null, and dangling references. Null or dangling references require an explicit compatible-template remediation Save before preflight can succeed; no migration default is invented. Unknown future generations remain rejected. Loading any generation does not migrate it or mark it dirty.

## 10. Preview and renderer boundary

Creation v4 changes authoring authority only. WU3 renderer contracts, profiles, identities, manifests, and accepted artifacts remain unchanged and do not consume Creation templates or v4 owned settings.

WU6 must define authoritative v4 admission and mapping from each composition's `visual_configuration`—never its provenance—to supported render inputs. It must explicitly handle null/missing/changed/excluded/unsupported visual sources, Album/Single/Short aspect/output support, camera trajectory, visualizer/progress mapping, color treatment, and renderer identity. Unsupported v4 render paths must fail truthfully rather than falling back to v3 template-reference semantics.

Phase 4A does not claim v4 rendering support, portrait output, renderer parity, final Shorts, advanced layers, titles, timelines, or imported-video composition.

## 11. Preserved Editor availability behavior

The Editor continues to display Albums, Singles, and Shorts for v1–v4. A category is available only when its authoritative Creation collection contains an active target. Unavailable categories remain keyboard-focusable for explanation and use the existing `aria-disabled` wording. Initial/fallback priority remains Albums → Singles → Shorts; archived-only work remains preserved.

Creation warnings remain backend-derived, collapsed/grouped presentation annotations. A null owned background is shown as needing a background. Warnings do not block inspection, approximate preview, audio audition, undo/redo, or saving an incomplete draft. Existing explicit one-image suggestion behavior remains user-invoked and never automatic.

Creation v4 uses the same availability, warning, audio-preview, dirty-navigation, and explicit-Save behavior while keeping its composition and template editing paths separate.

## 12. Implementation status and verification obligations

### Phase 4A implemented candidate

- strict Creation v4 schema and generated transport type;
- required composition-owned settings and optional historical provenance;
- exact canonical visual equivalence;
- pure deterministic v3→v4 migration and explicit version dispatch;
- v4 validation, persistence, approval, and dependency protection;
- conservative cleanup inventory, preview plan, authorization, and stale-plan protection;
- frontend recognition with non-destructive editing block; and
- Doc 50 consolidation plus related authority amendments.

Automated evidence on 2026-11-02: 68/68 focused backend schema/migration/workspace/document-store tests passed; 85/85 frontend tests passed; generated-contract checking, both TypeScript configurations, ESLint, the production Vite build, and `git diff --check` passed. The complete FFmpeg-enabled backend suite passed 1,205 tests and skipped 10 documented Windows/POSIX-only cases, but the existing `test_real_ffmpeg_player_progress_advances_over_stationary_rail[True]` WU3 integration assertion failed at a one-pixel tolerance boundary in both full-suite runs. Its immediate isolated rerun passed. Phase 4A does not modify that renderer or test. Production data is not migration evidence.

### Phase 4B implemented candidate

- native v4 client dispatch, Creation compatibility, revision-safe Save, pending-edit conflict preservation, and future-generation rejection;
- composition-owned Album, Single, and Short controls and approximate previews, with isolated approval invalidation and undo/redo;
- role-aware Apply Template with dependency validation, no-op handling, overwrite confirmation, and historical provenance update;
- explicit Update Template, Current Type Only and All Three Types synchronization without retroactive composition changes;
- Save as New Template with stable pending identity and no automatic provenance reassignment;
- searchable/filterable Template Library with family/standalone organization, direct preset editing, usage disclosure, standalone rename/duplicate/delete, and family create/from-standalone/rename/ungroup/delete operations;
- explicit sequential older-version upgrades plus v3→v4 preflight, target-specific remediation, atomic candidate construction, and revision-safe execution;
- user-facing conservative cleanup inventory, candidate review, explicit authorization, stale-plan rejection, and removal of `PROVEN_DISPOSABLE` only; and
- preservation of the WU3/WU6 boundary: browser preview is approximate and no v4 renderer mapping is claimed.

Automated evidence on 2026-11-02: 108/108 frontend tests passed, including the required two-Short isolation/Save scenario and v4 Creation additions; generated-contract checking, both TypeScript configurations, ESLint, production Vite build, and `git diff --check` passed. The 68 focused backend schema/migration/workspace/document-store tests passed. The full backend run passed 1,190 tests and skipped 20, with six WU3A integration cases initially failing only because their documented process-local FFmpeg variables were absent; the complete 28-test WU3A file passed after supplying the approved FFmpeg/FFprobe 9.0.2 paths process-locally. The WU4 HTTP integration file passed five and skipped its documented real-media case in the full unsandboxed run. Managed-sandbox attempts were separately blocked by Windows hard-link and event-loop socket policy and are not code failures. Interactive browser acceptance remains pending; no production Creation document was migrated or modified.

## 13. Historical traceability

WU4 Phases 1–3 implemented the v2/v3 shared-concrete-template model: compositions referenced templates directly, shared edits propagated, Customize created independent copies, and family edit scopes managed shared consumers. That implementation and its automated evidence remain historically accurate.

Phase 4 intentionally supersedes that active workflow because shared concrete dependencies caused ordinary composition edits to affect other outputs and generated excessive standalone-template management. Historical v1–v3 documents remain supported; they are not silently rewritten. Earlier shared-edit, shared-consumer warning, live-reference assignment, and composition-save-scope requirements are no longer normative for v4 or Phase 4B.

Git history and Docs 49–50 prior revisions preserve the detailed implementation record. This section does not imply that the earlier model was never implemented.
