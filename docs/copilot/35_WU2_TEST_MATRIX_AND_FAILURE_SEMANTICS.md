# 35 — WU2 executable acceptance and failure semantics

## Test categories
**Pure/unit (no FFmpeg):** canonical JSON stable across mapping order; rejects NaN/Infinity/surrogates/non-string keys; snapshot digest changes with input hash/request/tool version; frozen snapshot cannot be edited through shared object references; duplicate submission returns existing job; force-retry creates a new attempt; state transition table rejects illegal transitions; progress unknown stays null; heartbeat uses injected clock; cancellation race states are documented.

**Storage/integration (no FFmpeg):** atomic status revision CAS; temp file fsync and replace; simulated exception before replace leaves prior valid state; exception after replace is indeterminate; crash recovery with valid and invalid finals; attempt-owned cleanup only; reject traversal/symlink escapes; never modify source fixtures; concurrent claims yield at most one running attempt; interrupted process cannot leave permanent writer exclusion. Reuse WU1 tests where appropriate rather than copying them.

**FFmpeg integration (tool required):** generate tiny WAV and 1–2 second synthetic MP4 under temp test root; probe stream metadata; encode with argv; decode representative output; verify codec, dimensions, duration tolerance declared by test; corrupt input fails; nonzero exit fails; executable absent gives typed error; cancellation terminates and reaps process; failure leaves previous final untouched. Keep fixtures short and CPU bounded; tests must not require user albums.

**CI:** `pytest -q` for all non-tool tests; separate marked FFmpeg integration with installed binaries. At least one Windows and one Linux media smoke test. Preserve WU1 regression suite. Add a compile/import-boundary check and `git diff --check` to final evidence.

## State and error policy
- `queued`: snapshot and initial durable state exist; worker not started.
- `running`: worker owns attempt; heartbeat may update; no final artifact is assumed.
- `validating`: FFmpeg exit success, output staged; validation pending; no final success claimed.
- `completed`: verified output promoted, persisted completion; snapshot digest matches.
- `failed`: confirmed failure, typed error, no success claim.
- `cancel_requested`: durable request; process may still run; not equivalent to cancelled.
- `cancelled`: confirmed cancellation and process cleanup; final not promoted by that attempt.
- `commit_state=indeterminate`: failure after promotion or while recording terminal status; do not retry blindly; reconcile before deciding.

## Recovery truth table
| Observed at startup | Action |
|---|---|
| Running/validating with no valid final | Mark failed/recoverable; explicit retry required |
| Running/validating with verified final matching snapshot | Reconcile completed and log recovery |
| Final exists but digest/source provenance mismatch | Never reuse; mark failed and preserve evidence |
| Cancel requested, process gone, no promoted final | Reconcile cancelled |
| Cancel requested, valid final already promoted | Reconcile completed only with verified promotion chronology and log |
| Orphaned staging | Quarantine or cleanup **only** if ownership is recorded; never delete unknown files |
| Missing executable or corrupt input | Typed failed state; no artifact promotion |

## Implementation review checklist
- No shell=True, user-input interpolation into shell commands, unbounded stderr memory, implicit ffmpeg download, or global process kill.
- No claim of atomicity across two files; no mutation of approved snapshot; no invented progress.
- Output root containment and Windows path handling covered; avoid platform-specific hidden assumptions.
- Every failure has a deterministic test or explicit unsupported-platform note.
- Independent reviewer inspects implementation and tests before merge.
