# 30 — Render progress, heartbeat and reconnection (v2.0 normative)

## Job status contract
The WU3A backend contract is `wrld-render-progress/1.0` (`contracts/schemas/render-progress-v1.schema.json`). Job state remains the authoritative `queued|running|cancel_requested|cancelled|failed|completed` lifecycle and is separate from the rendering phase. The exact phases are `preparing`, `snapshotting_sources`, `normalizing_audio`, `assembling_audio`, `encoding`, `probing_output`, `decoding_output`, `publishing_artifacts`, `publishing_report`, and `completed`.

Each durable attempt record contains job/attempt IDs, current phase, nullable phase-specific percentage, nullable current/total track counts, nullable processed/total media duration, elapsed time, nullable reliable ETA, last progress and heartbeat timestamps, and nullable failure phase/diagnostic reference. There is no weighted overall percentage. FFmpeg `progress=end` makes the encoding phase exactly 100%; verification starts a distinct phase and never implies completion. `completed` is persisted only after required encode, probe, complete decode, artifact/report publication, cleanup, and persistence work succeeds.

WU6 must expose this same model through an approved application API or event contract. The earlier illustrative `GET /api/jobs/{job_id}` path is superseded by the proposed versioned route in Doc 15 and remains unapproved until WU6 contract review. Timestamps are UTC ISO-8601. Server owns status; clients never write it. UI network state (`connected|reconnecting|disconnected`) is separate from backend job state. No layer may invent percentages or ETA.

## Recovery semantics
A missed poll or network timeout **does not** mean a job failed. Display `Connection lost — checking status` and retry with bounded exponential backoff (2s, 4s, 8s, 15s cap). On reconnection reconcile from authoritative job snapshot; do not resubmit automatically. Backend heartbeat is updated while work is alive; if heartbeat is stale, show `Possibly stalled` and require backend confirmation before retry/cancel. Do not mark completed until validated artifacts are atomically promoted. Existing one-worker job scheduler and safe retry rules in docs 11/21 apply. Cancellation is requested and acknowledged, not assumed instantaneous.

## Tests
Fake clock: heartbeat freshness, stalled warning, missed poll, reconnection, monotonic UI progress, restart reconciliation, cancellation acknowledgement, failed render and validated completion. Backend integration: worker process interruption, partial cleanup and retry idempotency. No standalone telemetry dashboard or distributed monitoring stack.

## Work-unit allocation

WU3A reuses the durable internal job status, heartbeat, cancellation and recovery semantics and adds the versioned progress record above for its headless album/track entry point. The CLI polls that record, emits throttled non-in-place progress lines to stderr, and reserves stdout for the machine-readable final JSON result. It does not approve a browser polling route. WU6 locks the render-job HTTP contract and implements polling/reconnection UI over the same application state; it must not introduce a UI-specific progress model, scheduler, or job-state model.

Under approved Doc 38 Decisions 1 and 5, WU3A completion results expose stable artifact IDs and album-project-relative artifact paths and merge a verified result into `output/metadata/render_report.json` only after atomic promotion. Progress/status storage and versioned failure diagnostics remain application-managed private state, not published files under the album project's `output/` tree. WU6 consumes the catalog rather than inferring target identity from filenames.

## WU3B progress allocation

WU3B reuses `wrld-render-progress/1.0` and the existing phases. RMS-envelope preparation may report only the existing `preparing` phase unless a separately approved additive phase is proven necessary; no client invents a percentage. Encoding completion, probe, full decode, publication, report persistence, and final completion remain distinct exactly as above. The progress graphic burned into a video is track-relative media content derived from the sample timeline and is unrelated to backend job progress, heartbeat, overall percentage, or ETA. Temporary motion previews use the same internal status/cancellation semantics but never appear as published artifacts or completed export reports.
