# 23 — v1.5 Batch YouTube Metadata Editor (normative)

## Screen layout
Metadata screen has **Table / Detail** toggle. Default Table for batches (compilation + all Shorts), Detail for long descriptions, chapter review and single-output validation. Both views edit the same client draft store keyed by stable output IDs.

### Table wireframe (desktop)
```text
┌──────────────┬──────────────────────────────────────────────────────────────────────────────────┐
│ WRLD STUDIO  │ Metadata review         [Table ●] [Detail]       4 unsaved edits                 │
│ Import       │ [Search title/ID] [Filter errors] [Select all] [Bulk tags] [Bulk visibility]     │
│ Review       │ ┌───┬──────────┬──────────────────────────┬────────────────────┬───────┬────────┐ │
│ Metadata     │ │ □ │ Output   │ Title (inline editable)  │ Tags (inline)      │ Vis.  │ Status │ │
│ Render       │ │ □ │ Album    │ [WRLD-FI Compilation]    │ [lofi, chill]      │Private│ ✓      │ │
│              │ │ □ │ T01-S01  │ [Lantern | Short 01]     │ [lofi, short]      │Private│ ⚠ link │ │
│              │ │ □ │ T01-S02  │ [Lantern | Short 02]     │ [lofi, short]      │Private│ ✓      │ │
│              │ └───┴──────────┴──────────────────────────┴────────────────────┴───────┴────────┘ │
│              │ [Open detail] [Validate all] [Save draft] [Continue to Render]                    │
└──────────────┴──────────────────────────────────────────────────────────────────────────────────┘
```

## Editing behavior
- Columns: checkbox, stable output ID, type, title, tags, visibility, validation badge; description snippet with **Edit detail** action (not a huge multiline grid cell). Use accessible native inputs; horizontal scroll on small screens.
- Bulk actions apply **only to explicitly selected IDs** and require confirmation for destructive/overwriting actions. Safe operations: append/remove tags, set visibility, prepend/append title text; never overwrite every description silently. Provide preview of affected IDs and undo before save.
- Inline edits update draft state immediately but **not** the backend until Save. Preserve edits when switching Table ↔ Detail or filtering. Track dirty IDs, support discard with confirmation, and show per-row errors.
- Save uses expected revision; on 409 retain unsaved changes, show server revision, and require explicit reload/merge. Generated defaults are never mutated.
- Validate title ≤100 Unicode code points, description ≤5000 Unicode code points, configured tags total limit (YouTube current guidance: 500 characters with comma/quote accounting; centralize and verify at API integration), and safe UTF-8 export. Emoji, accents, punctuation and newline cases are mandatory fixtures. Duplicate titles warn; unresolved URL placeholders block publish-ready export but may remain draft.
- All fields must be accessible via keyboard and labeled; avoid keyboard traps in table navigation. Responsive layout switches to cards/detail editing on narrow widths.

## Tests
- React Testing Library: filtering, selection, bulk action confirmation, inline edits, dirty tracking, Table↔Detail preservation, revision conflicts.
- Playwright: import → color change → Short selection → Metadata Table batch edit → Detail description → validate → mock render → inspect output status. Test Unicode, title/description bounds, tags limit, escaping, unresolved placeholders, and CSV formula injection. No real publishing or fake upload success.
