# WU4 Editor Browser Acceptance Report

**Date:** 2026-11-01  
**Disposition:** **INCOMPLETE — core paths exercised; mandatory variants remain automated-only or untested**  
**Scope:** WU4 Template-Based Editor and Doc 50 Phase 1–2 UX candidate  
**Repository:** `C:\Users\ptanz\job_search\video_studio`

## 1. Executive conclusion

An isolated browser session at `http://127.0.0.1:5174/` successfully exercised the production-shaped Echoes of Asia project against a disposable copy of the application state. The session completed explicit v1-to-v2 upgrade, warning navigation, one-image template suggestion, shared-template assignment, one-step undo/redo, explicit Save, reload persistence, real-image preview controls, dirty-navigation guarding, and Short excerpt playback.

One implementation defect was confirmed: changing the selected composition while a Short excerpt was playing updated the UI but allowed the old `HTMLAudioElement` to continue audibly. The audio controller now exposes a stable stop operation, and Editor stops playback when the selected target, category, or Album track context changes. A focused regression was added. The corrected behavior was rechecked in the same disposable browser environment: switching from Short 1 to Short 2 stopped the old playback and removed the browser's active-audio indicator.

The affected Editor suite passes 15/15 and the complete frontend suite passes 52/52 when run sequentially. TypeScript, ESLint, generated-contract consistency, production build, and `git diff --check` pass. The previous backend baseline remains 1,174 passed with 10 documented host skips; backend tests were not rerun because this correction changes only frontend audio lifecycle behavior.

Manual acceptance remains incomplete. Category-availability variants, zero/multiple-image variants, Album and Single playback, missing-audio isolation, historical/invalid migration variants, two-session conflict handling, and several recovery/accessibility cases were not all exercised in a real browser. The implementation therefore is not yet recommended as manually accepted or ready to advance to Doc 50 Phase 3. Phase 3 also remains specification-only and unauthorized by Doc 50.

## 2. Environment and integrity

- Branch: `feature/wu4-composition-editor`.
- HEAD: `2b25327d14c92e0a11c94c15d0e8f891b0496bb5`.
- The pre-existing working tree was heavily dirty with the uncommitted WU4 candidate; it was preserved.
- Disposable acceptance root: `C:\Users\ptanz\AppData\Local\Temp\WRLD-WU4-Acceptance-20261031-01`.
- Browser state copy: `browser-doc50-01\state`.
- Isolated origins: frontend `http://127.0.0.1:5174/`; backend `http://127.0.0.1:8010/`.
- Browser surface: Microsoft Edge window selected explicitly by the approved Computer Use mechanism after its local origin was established.
- Source media was read from the trusted music root; only the disposable state copy was migrated and saved.
- No production Creation document, production source media, WU3 renderer contract, or production registry was modified.
- No dependency was installed. No commit, push, reset, clean, or unrelated edit was performed.

## 3. Browser-tested evidence

### Migration and persistence

- A real v1 Creation document displayed the explicit Upgrade action.
- Upgrade completed successfully and persisted `wrld-creation-state/2.0` at revision 4 in the disposable copy.
- Inspection after upgrade showed 1 Album, 12 Singles, 24 Shorts, 24 visual templates, and 24 issues.
- The 24 initial issues corresponded to the 24 Shorts; Singles had null template references.
- Stable target identities, existing generic settings, approvals, and ordering were retained in the migrated document.
- Reload did not offer Upgrade again and did not duplicate templates.

### Warnings and recovery navigation

- The warning summary was collapsed initially and reported `24 Shorts need a background`.
- Expanding it exposed individual target/template identities.
- **Edit dependency** selected the exact affected Short and Editor category.
- Creating one template reduced the unresolved count from 24 to 23 locally.
- Assigning one shared background to all active Shorts cleared the remaining warnings.
- Save and reload retained the reconciled warning state.

### Image suggestion and visual preview

- The project had exactly one eligible included image, `video_background_v1.png`.
- An existing migrated template did not receive or offer an automatic assignment.
- A newly created template remained null until the explicit **Use only included image** action was chosen.
- The actual project image then appeared in the preview; no placeholder or generated media was substituted.
- Short preview showed 9:16 portrait and **Approximate**.
- Contain visibly letterboxed the landscape image; Cover cropped it; changing focal X visibly shifted the crop.
- Bounded camera mode and retained maximum zoom were exercised.
- Album preview showed 16:9 landscape, **Approximate**, and remained usable with a null template/background.

### Shared-template assignment

- Assigning to only the current output correctly produced 0 changes and 1 no-op and disabled Apply.
- The dialog identified 13 active aspect-incompatible outputs: 1 Album and 12 Singles.
- Selecting all active Shorts produced 23 changes and 1 no-op.
- One Apply changed the complete local Creation state atomically.
- One Undo restored all 23 warnings; one Redo removed them again.
- Explicit Save and reload retained all 24 Short references to the shared template and retained the real image dependency.

### Dirty navigation and Save

- Navigating from dirty Editor to Media opened **Save Editor changes?** with Cancel, Discard, and Save & continue.
- Cancel kept the user in Editor with the dirty edit intact.
- **Save editor draft** cleared the dirty indicator.
- Reload restored the saved state.

### Audio defect and browser recheck

- Before correction, playing Short 1 and selecting Short 2 changed the new target button to Play, but the prior audio continued and Edge retained its active-audio indicator.
- After correction and hot reload, the same action stopped Short 1, Short 2 remained at Play, and the active-audio indicator disappeared.
- The exercised Short displayed and played its saved excerpt (`0:00–0:30 · 30s`).

## 4. Scenario status matrix

| Scenario | Browser-tested | Automated-only evidence | Not browser-tested | Status |
|---|---|---|---|---|
| A — category availability and fallback | Current all-active project; Albums selected after reload | Empty/archived category disabling, focusable `aria-disabled` tabs, keyboard/click blocking, first-active fallback, all-empty Creation recovery, conflict reload fallback | Browser variants for no Album, only Shorts, all empty, disabled-tab tooltip/keyboard | **PARTIAL** |
| B — warning disclosure and navigation | Collapsed count, grouped details, exact target navigation, local reconciliation, save/reload | Changed-image reconciliation and target issue logic | Missing/excluded/unsupported image recovery in browser | **PARTIAL** |
| C — eligible-image suggestion | Exactly-one case; new-template-only; explicit action; no automatic assignment | Zero and multiple eligible-image cases | Zero/multiple variants in browser | **PARTIAL** |
| D — shared assignment | Compatibility counts, no-op, 23-change shared assignment, one undo/redo, save/reload | Archived targets excluded from assignment; protected approvals and unrelated state preserved | Archived and approval cases in browser | **PARTIAL** |
| E — visual previews | Actual image, Short 9:16, Album 16:9, Contain/Cover/focal/camera/null background/Approximate | Typed setting round trip and changed-image recovery | Single preview and missing/excluded image recovery in browser | **PARTIAL** |
| F — audio previews | Short saved excerpt; target-switch defect reproduced and corrected behavior rechecked | Shared controller, excerpt boundary, capability gating, non-dirty playback | Album and Single playback; missing-audio isolation in browser | **PARTIAL — defect fixed** |
| G — guards, undo/redo, save, conflict | Dirty navigation Cancel, atomic undo/redo, explicit Save, reload persistence | 409 revision conflict and authoritative reload behavior | Real two-session browser conflict | **PARTIAL** |
| H — migration | Valid production-shaped v1 explicit upgrade, revision 4 persistence, stable identities/settings, no duplicate upgrade | Historical/unknown effects, invalid versions/values, deterministic migration, failure atomicity | Historical/invalid/failed upgrade and retry variants in browser | **PARTIAL** |

No scenario is labeled fully browser-passed when one of its requested mandatory variants was not exercised. Code inspection is not counted as browser evidence.

## 5. Confirmed defect and correction

### WU4-AUDIO-001 — stale Editor playback after target change

- **Severity:** Medium usability/lifecycle defect.
- **Expected:** changing composition, category, or Album track stops the previous preview.
- **Actual before correction:** the old audio continued after the visible selection changed.
- **Root cause:** `useAudioPreview` had an internal finish operation but did not expose it; Editor selection effects therefore could not stop the shared media element.
- **Minimal correction:** expose `stop`, invoke it when Editor playback context changes, and add a focused regression.
- **Files:**
  - `frontend/src/features/review/AudioPreview.tsx`
  - `frontend/src/features/review/EditorWorkspace.tsx`
  - `frontend/tests/EditorWorkspace.test.tsx`
- **Data/schema impact:** none. No persisted Creation field, revision behavior, template identity, approval, or API changed.
- **Browser result after correction:** pass for Short-to-Short target switching.

## 6. Automated verification

Final runs after the lint correction:

| Check | Result |
|---|---|
| Focused Editor Vitest | **15 passed / 15** |
| Complete frontend Vitest | **52 passed / 52** across 6 files |
| ESLint | **PASS**, 0 errors and 0 warnings |
| TypeScript app + node configs | **PASS** |
| Generated frontend contract consistency | **PASS** |
| Vite production build | **PASS**, 1,597 modules transformed |
| `git diff --check` | **PASS** |
| Backend baseline before this frontend-only correction | **1,174 passed, 10 skipped** |

An earlier complete frontend run was launched concurrently with TypeScript, ESLint, and the production build. Six tests exceeded Vitest's five-second timeout under that contention, while 46 passed; none failed an assertion. The same suite then passed 52/52 when run alone. That contention run is retained as a failed verification attempt, not presented as a product regression.

The npm wrapper also once emitted a Windows cache cleanup error (`Callback called more than once`) after Vitest itself had passed. Final verification used the repository's pinned local binaries and returned clean exit status 0.

## 7. Remaining acceptance limitations

The following require a future disposable browser session before manual acceptance can be complete:

1. Exercise every category-availability permutation with keyboard focus, disabled-tab description, and fallback behavior.
2. Exercise zero and multiple eligible-image suggestions in a real browser.
3. Exercise archived consumers and approval effects during shared assignment in a browser.
4. Play Album and Single audio, then verify missing-audio isolation without affecting other targets.
5. Exercise missing, changed, excluded, and unsupported image recovery end to end.
6. Perform a real two-session optimistic-revision conflict.
7. Exercise historical/unknown and invalid migration variants and a failed-upgrade retry in the browser.
8. Complete narrow-layout, keyboard-only, focus-return, reduced-motion, and console-error checks.

## 8. Final disposition and Phase 3 readiness

The tested Phase 1–2 core paths are substantially functional, and the only browser-confirmed implementation defect found in this run has a narrow verified correction. Data integrity, explicit Save, revision-safe contracts, stable identities, and WU3 boundaries were not altered.

Nevertheless, this report remains **INCOMPLETE** because mandatory browser variants remain automated-only or untested. WU4 should not yet be described as manually accepted, and this report does not recommend beginning Doc 50 Phase 3. Phase 3 independent-copy implementation and WU6 rendering remain out of scope and require separate explicit authorization after the remaining acceptance gaps are closed.
