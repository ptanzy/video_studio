# Render lifecycle, atomic publication, and recovery — v1.1

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
- A completed valid artifact with matching fingerprint is reused by default. Changed config or input produces new identity; old outputs are not silently considered current. An explicit force-rebuild option may replace outputs safely.
- FFmpeg subprocess cancellation: request graceful termination, wait bounded interval, then kill process tree if needed; wait/reap; clean owned temp artifacts; record cancelled. Test on Windows and Linux. UI cancellation must not falsely claim completion.
- Disk full, permission errors, missing FFmpeg, corrupt inputs, malformed output, and unexpected process exit must leave old valid finals intact and report actionable errors.
- Cleanup rules: owned temp paths only; never glob/delete arbitrary files. On failure preserve logs and report; temp artifacts may be retained behind an opt-in debug flag.

## Logging
- JSON Lines file per attempt under `output/logs/`, with UTC timestamp, level, event, job_id, attempt_id, artifact_id, elapsed_ms and error category; redact or avoid secrets. Store bounded FFmpeg stderr tail plus optional full stderr file. Human-readable UI errors link to job log. No network telemetry required.
- Report records planned/actual duration, codec, frame size/rate, input/output fingerprints, elapsed time, validation checks, retry count, and warnings.

## Dry-run
- Dry-run validates input, probes media, computes planned outputs and estimated disk requirements, and shows command plans without encoding. It must not mark artifacts completed or fabricate media files.
