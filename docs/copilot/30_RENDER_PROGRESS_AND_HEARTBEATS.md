# 30 — Render progress, heartbeat and reconnection (v1.7 normative)

## Job status contract
Expose `GET /api/jobs/{job_id}` as the POC polling endpoint (exact route to be locked at WU1 contract review). Return stable `job_id`, `status` (`queued|running|cancel_requested|cancelled|failed|completed`), `phase`, `progress_percent` nullable, `created_at`, `updated_at`, `last_heartbeat_at` nullable, `error` nullable, and output verification summary when completed. Timestamps are UTC ISO-8601. Server owns status; client never writes it. Poll every 2 seconds while visible/active; pause/reduce polling when page hidden. Requests have bounded timeout and abort on unmount. UI network state (`connected|reconnecting|disconnected`) is separate from backend job state. No invented progress percentages when FFmpeg cannot report them.

## Recovery semantics
A missed poll or network timeout **does not** mean a job failed. Display `Connection lost — checking status` and retry with bounded exponential backoff (2s, 4s, 8s, 15s cap). On reconnection reconcile from authoritative job snapshot; do not resubmit automatically. Backend heartbeat is updated while work is alive; if heartbeat is stale, show `Possibly stalled` and require backend confirmation before retry/cancel. Do not mark completed until validated artifacts are atomically promoted. Existing one-worker job scheduler and safe retry rules in docs 11/21 apply. Cancellation is requested and acknowledged, not assumed instantaneous.

## Tests
Fake clock: heartbeat freshness, stalled warning, missed poll, reconnection, monotonic UI progress, restart reconciliation, cancellation acknowledgement, failed render and validated completion. Backend integration: worker process interruption, partial cleanup and retry idempotency. No standalone telemetry dashboard or distributed monitoring stack.

## Work-unit allocation

WU3A reuses the durable internal job status, heartbeat, progress, cancellation and recovery semantics for its headless album/track entry point. It does not approve the proposed browser polling route. WU6 locks the render-job HTTP contract and implements polling/reconnection UI over the same application state; it must not introduce a second job-state model.

Under approved Doc 38 Decisions 1 and 5, WU3A completion results expose stable artifact IDs and album-project-relative artifact paths and merge a verified result into `output/metadata/render_report.json` only after atomic promotion. Progress/status storage and diagnostic logs remain application-managed state, not published files under the album project's `output/` tree. WU6 consumes the catalog rather than inferring target identity from filenames.
