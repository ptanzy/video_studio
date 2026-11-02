# Render lifecycle, atomic publication, and recovery — v1.1

## WU3A application

WU3A applies these safety goals through the already implemented WU2 lifecycle in Docs 34–35 and the actual source/tests; those implementation records control where this older conceptual state vocabulary differs. Album and individual-track export must use the same repository, immutable snapshots, owned-process cancellation, attempt staging, verification, promotion, and restart reconciliation. WU3A must not create a parallel lifecycle or weaken cleanup/publication guarantees.

## State machine
- Each artifact: `pending -> running -> validating -> completed`; `running/validating -> failed|cancelled`; `failed|cancelled -> pending` on explicit retry. Job-level status is derived from artifact states and may be `partial`.
- One active FFmpeg render process by default; previews run only when no conflicting heavy render is active, or are explicitly queued. No distributed workers in POC.
- Job identity: deterministic input fingerprint + config digest; attempt ID: unique per run. Each attempt logs correlation fields `job_id`, `attempt_id`, `artifact_id`, `phase`.

## Safe rendering
1. Validate manifest, overrides, source inputs and destination safety; compute frozen snapshot.
2. Plan deterministic artifact paths; write `job_snapshot.json` and initial job state atomically. Use separate writable state from source files.
3. Render each artifact into a unique temporary path on the **same filesystem** as destination (correct extension/container, e.g. `.partial.mp4`), never straight to final.
4. Check FFmpeg exit status; probe actual media; decode representative frames and audio; compare against expected contract.
5. Only after successful validation atomically replace/promote the temp artifact to final. On Windows, close handles before promotion.
6. Write completed state/report atomically **after** successful promotion. A crash between promotion and state write is reconciled by validating the final artifact at restart.

## Retry and cancellation
- At startup, reconcile any `running` or `validating` entries: inspect finals, validate and compare fingerprints; mark complete only if valid and matching, otherwise queue rerender. Orphaned temp artifacts are quarantined or deleted only if owned by this job and older than a documented threshold; never delete source WAVs, artwork, or unrelated files.
- A completed valid artifact with matching fingerprint is reused by default. Changed config or input produces new identity; old outputs are not silently considered current. Approved WU3A Decision 5 has no force-rebuild/replace option: a different existing final yields `OUTPUT_EXISTS`. A future replacement workflow requires separate approval and controlled recoverable semantics.
- FFmpeg subprocess cancellation: request graceful termination, wait bounded interval, then kill process tree if needed; wait/reap; clean owned temp artifacts; record cancelled. Test on Windows and Linux. UI cancellation must not falsely claim completion.
- Disk full, permission errors, missing FFmpeg, corrupt inputs, malformed output, and unexpected process exit must leave old valid finals intact and report actionable errors.
- Cleanup rules: owned temp paths only; never glob/delete arbitrary files. On failure preserve logs and report; temp artifacts may be retained behind an opt-in debug flag.

## Logging
- JSON Lines logs remain in the configured application-managed job/state area, not the album's published `output/` artifact tree, with UTC timestamp, level, event, job_id, attempt_id, artifact_id, elapsed_ms and error category; redact or avoid secrets. Store bounded FFmpeg stderr tail plus optional owned full stderr file. Human-readable diagnostics can identify the job log without exposing it through public responses. No network telemetry required.
- Report records planned/actual duration, codec, frame size/rate, input/output fingerprints, elapsed time, validation checks, retry count, and warnings.

## Dry-run
- Dry-run validates input, probes media, computes planned outputs and estimated disk requirements, and shows command plans without encoding. It must not mark artifacts completed or fabricate media files.
