# 34 — WU2 media infrastructure baseline (v1.9 authoritative)

## Authority and approval
This document is the proposed WU2 contract for user approval. It supersedes contradictory WU2 scope in earlier documents, not the WU1 foundation or the product's later visual/render specifications. WU1 is assumed merged into `master`. Implement on `feature/wu2-media-infrastructure`. Do not alter `legacy_v2/` or overwrite existing WU1 code. Before implementation, inspect the actual WU1 source and adapt interfaces to it; stop if WU1 public contracts conflict with this specification.

## WU2 boundary
Implement a headless local media and render-job infrastructure with a **single active local worker**, durable job records, FFprobe-based input/output inspection, an FFmpeg subprocess adapter, safe artifact staging/promotion, cancellation and recovery. WU2 produces a **synthetic-media proof-of-infrastructure render** only (for example, an FFmpeg-generated solid-color test video with generated tone or silent audio), NOT the album compilation or Shorts renderer. This test artifact is not a user-facing product deliverable.

Out of scope: React UI, waveform regions, thumbnails, typography, mood mapping, color grading, bars, pan/zoom, chapter metadata, real album concatenation, Short extraction, Analyzer integration, upload, service host/HTTP routes, distributed scheduling, Redis, database, Docker, cloud. Do not make arbitrary defaults for those areas.

## Approved layers and interfaces
- `domain`: pure typed `JobState`, `ArtifactState`, `RenderSnapshot`, `MediaProbe`, `RenderPlan`, `JobEvent` and errors; no infrastructure imports.
- `application/ports`: `MediaProber`, `ProcessRunner`, `JobRepository`, `ArtifactVerifier`, `Clock`, `IdFactory`, `JobEventSink` as Protocols. Define a `RenderWorker`/use-case depending only on these ports.
- `infrastructure`: FFprobe/FFmpeg executable discovery, subprocess execution, filesystem job repository and artifact staging, JSONL event sink. Adapters must be replaceable by fakes.
- No changes to WU1 public contracts unless required for a demonstrated defect; document migrations and test them.
- Avoid introducing a second storage or locking convention if the WU1 atomic store offers a reusable primitive. Do not use WU1 override storage as the job database by renaming fields.

## Toolchain and invocation
- Discover FFmpeg and FFprobe separately via configured absolute paths or PATH; validate executable availability and version; missing tools are typed actionable errors. Do not auto-install or download binaries.
- Use argument arrays (`subprocess` with `shell=False`), no shell string concatenation; capture stderr safely and boundedly, prevent process pipe deadlocks; record sanitized command arguments. Explicit timeouts and cancellation must reap the child and descendants where supported; never kill unrelated processes.
- Input probing: FFprobe JSON with strict parse/error handling; duration must be finite and positive where applicable; capture stream index/type, codec, sample rate, channel count, dimensions, frame rate and duration as available. Preserve unknown/missing values rather than inventing them. Probe result includes source path and tool version as provenance. Never alter source WAV/artwork.
- Output validation: expected audio/video streams and positive duration, codec/container/size checks **as dictated by the synthetic test plan**, and at least one bounded decode check; nonzero FFmpeg exit or failed validation cannot mark complete.

## Frozen snapshot and job identity
- See `contracts/schemas/render-job-snapshot-v1.schema.json` and `render-job-status-v1.schema.json`. Both are deliberately narrow WU2 contracts; `request` is opaque JSON validated strictly and cannot be mutated once submitted. It is **not** the full product render request schema.
- Snapshot contains schema version, job ID, attempt ID, creation timestamp, renderer version, normalized request, declared input fingerprints and deterministic request digest. Compute digest from canonical UTF-8 JSON with sorted keys, compact separators, no NaN/Infinity; encode file fingerprints using SHA-256 content hashing for synthetic test fixtures. Use a clear separation between logical job identity and attempt identity; do not use titles or mutable track order as recording identity.
- Store snapshot before execution; job status persists separately. Status references the snapshot digest. On retry create a new attempt, preserving original immutable snapshot. Job IDs may be UUIDv4; idempotent submit with same digest should return existing compatible job unless explicit force is requested. Do not treat a digest match as sufficient to reuse an unverified artifact.
- Source changes after snapshot must fail validation before execution/promotion; no time-of-check/time-of-use promise is made for malicious concurrent source mutation, but recheck fingerprint at the execution boundary and before final completion.

## State machine and persistence
- WU2 job statuses: `queued`, `running`, `validating`, `completed`, `failed`, `cancel_requested`, `cancelled`. No `partial` status in the WU2 one-artifact synthetic proof; `partial` is reserved for later multi-artifact units.
- Allowed transitions: queued→running|cancelled; running→validating|failed|cancel_requested; validating→completed|failed|cancel_requested; cancel_requested→cancelled|failed|completed (completed only if work was verified/promoted before cancellation took effect, and log why); failed|cancelled→queued **only via explicit retry creating a new attempt**. Terminal states cannot silently mutate.
- Persist JSON status with revision and UTC timestamps using same-directory temp, fsync, atomic replace; enforce one writer per job. `progress_percent` is null when unknown; do not fabricate percent or regress known progress. Heartbeat is an observed worker timestamp, not a synthetic status update from polling.
- Worker claims at most one queued attempt; jobs may queue but never render concurrently. Crash restart reconciles `running`, `validating`, `cancel_requested`: validate any already-promoted artifact against the snapshot before marking complete; otherwise mark failed with recoverable reason and require explicit retry (no automatic destructive rerender).

## Artifact safety
- All output paths live under a configured writable output root. Reject absolute traversal and paths escaping it; refuse symlink/reparse-point escapes as far as platform APIs allow. Never write in source directories or `legacy_v2`.
- Use a unique attempt-owned staging directory **on the destination filesystem**. Render to an extension-correct temporary filename (e.g. `test.partial.mp4`), probe/decode, then promote with `os.replace` only after verification. Do not overwrite an existing validated final from a different snapshot; collision is an error. Final file must be revalidated on restart.
- Track exact owned temporary paths in the job record; cleanup only owned files. Preserve logs and errors on failure; never glob/delete arbitrary output trees. Handle disk-full, permission-denied, invalid media, missing binaries and process exit errors without reporting success.
- For post-promotion persistence failure, return an **indeterminate commit state**, reconcile from final media and snapshot on restart. Do not claim an atomic transaction across file promotion and status persistence.

## Progress, logging, cancellation
- Capture FFmpeg `-progress pipe:1` where used; parse progress keys and monotonic timestamps. A missing duration means unknown percentage. JSONL events with UTC timestamp, job_id, attempt_id, phase, event, elapsed_ms, and optional typed error; avoid raw private path/secret leakage in default UI-safe payloads.
- Cancellation sets `cancel_requested` durably, signals the process, waits a bounded grace interval, kills only the owned process tree if needed, reaps it, and records outcome. Test prestart and in-flight cancellation, including child termination. On Windows, do not assume `Popen.terminate()` alone always kills grandchildren; document supported mechanism.
- No HTTP polling endpoint in WU2. A future FastAPI adapter may expose these application use cases after its API contract is approved.

## WU2 acceptance gate
1. Unit tests for state transitions, canonical digest, immutable snapshot, revision checks, idempotency, fake ports, progress parser and cancellation races.
2. Contract tests validate positive/negative JSON fixtures for both new schemas and strict JSON round-trip; do not compare unrelated v1.5 API examples.
3. Integration tests use generated synthetic media and actual FFmpeg/FFprobe if installed; assert probe, encode, output verification, promotion, cancellation, restart reconciliation, idempotent reuse and failure handling. Tests requiring FFmpeg are marked `integration_ffmpeg` and explicitly skipped with reason when binaries are absent; CI must install them on the media-integration job.
4. Fault injection: FFmpeg nonzero exit, malformed ffprobe JSON, invalid input, bad output, permission/disk error (mock), pre/post replace failure, stale running job, crash after promotion, concurrent claim, source immutability.
5. CI runs Python 3.11 and 3.12 on Ubuntu, and Windows Python 3.12 with FFmpeg installed for at least one smoke integration. Pin test dependencies via `pyproject.toml`; do not silently install global packages.
6. No `legacy_v2` modifications; no UI/API/render effects; report exact test commands, counts, skips, paths and limitations; stop for independent review before WU3.

## Explicit deferred decisions
Full album render request and multi-artifact snapshot schema, source-file fingerprint performance optimization, product output filenames, album audio normalization, Shorts, user-facing job polling route, exact video presets, distributed locks and service deployments. These are not permission to invent product behavior during WU2.

**v2.0 roadmap note:** Doc 38 now assigns the album/individual-track product render contract, static MP4, normalization/timeline, chapter output, headless entry point, and related output settings/naming decisions to WU3A. This does not change WU2's completed synthetic-only history. Shorts, browser polling, distributed locks, and service deployment remain outside WU3A except where Doc 38 explicitly says otherwise.
