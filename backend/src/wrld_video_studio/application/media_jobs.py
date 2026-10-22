from __future__ import annotations

import hashlib
import math
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from wrld_video_studio.application.ports.media import (
    ArtifactStore,
    ArtifactVerifier,
    Clock,
    IdFactory,
    JobEventSink,
    JobRepository,
    MediaProber,
    SyntheticEncoder,
)
from wrld_video_studio.application.ports.render_coordination import (
    RenderAdmissionCancelled,
    RenderAdmissionCoordinator,
)
from wrld_video_studio.domain.jobs import (
    InputFingerprint,
    JobEvent,
    JobState,
    JobStatus,
    RenderPlan,
    RenderSnapshot,
    create_snapshot,
    utc_timestamp,
)
from wrld_video_studio.domain.media_errors import (
    IndeterminateMediaCommitError,
    MediaInfrastructureError,
)


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class UuidFactory(IdFactory):
    def new_id(self) -> str:
        return str(uuid.uuid4())


class MediaJobs:
    def __init__(
        self,
        repository: JobRepository,
        *,
        clock: Clock | None = None,
        id_factory: IdFactory | None = None,
    ) -> None:
        self.repository = repository
        self.clock = clock or SystemClock()
        self.id_factory = id_factory or UuidFactory()

    def submit(
        self,
        request: Mapping[str, Any],
        source_root: str | Path,
        renderer_version: str,
        *,
        force: bool = False,
    ) -> tuple[RenderSnapshot, JobStatus]:
        normalized = dict(request)
        input_paths = normalized.get("inputs")
        if not isinstance(input_paths, list) or not input_paths:
            raise MediaInfrastructureError("INVALID_REQUEST", "At least one relative input is required.")
        inputs = tuple(
            InputFingerprint(relative_path=relative, sha256=self._fingerprint(source_root, relative))
            for relative in input_paths
        )
        digest_snapshot = create_snapshot(
            job_id="digest-only",
            attempt_id="digest-only",
            created_at=utc_timestamp(self.clock.now()),
            renderer_version=renderer_version,
            request=normalized,
            inputs=inputs,
        )
        existing = self.repository.find_by_request_digest(digest_snapshot.request_digest)
        if existing is not None and not force:
            return existing
        job_id = existing[0].job_id if existing is not None else self.id_factory.new_id()
        snapshot = create_snapshot(
            job_id=job_id,
            attempt_id=self.id_factory.new_id(),
            created_at=utc_timestamp(self.clock.now()),
            renderer_version=renderer_version,
            request=normalized,
            inputs=inputs,
        )
        status = JobStatus.queued(snapshot, self.clock.now())
        self.repository.create(snapshot, status)
        return snapshot, status

    def retry(self, job_id: str, source_root: str | Path) -> tuple[RenderSnapshot, JobStatus]:
        previous, status = self.repository.get(job_id)
        if status.status not in {JobState.FAILED, JobState.CANCELLED}:
            raise MediaInfrastructureError("INVALID_RETRY", "Only failed or cancelled jobs may be retried.")
        for fingerprint in previous.inputs:
            current = self._fingerprint(source_root, fingerprint.relative_path)
            if current != fingerprint.sha256:
                raise MediaInfrastructureError(
                    "SOURCE_CHANGED", "Input changed since the original job snapshot."
                )
        snapshot = create_snapshot(
            job_id=job_id,
            attempt_id=self.id_factory.new_id(),
            created_at=utc_timestamp(self.clock.now()),
            renderer_version=previous.renderer_version,
            request=previous.request,
            inputs=previous.inputs,
        )
        queued = JobStatus.queued(snapshot, self.clock.now())
        self.repository.create(snapshot, queued)
        return snapshot, queued

    @staticmethod
    def _fingerprint(root: str | Path, relative_path: str) -> str:
        root_path = Path(root).resolve()
        posix = PurePosixPath(relative_path)
        windows = PureWindowsPath(relative_path)
        if (
            posix.is_absolute()
            or windows.is_absolute()
            or windows.drive
            or ".." in posix.parts
            or ".." in windows.parts
        ):
            raise MediaInfrastructureError("INVALID_INPUT_PATH", "Input path must be relative and contained.")
        path = (root_path / Path(*posix.parts)).resolve(strict=False)
        try:
            path.relative_to(root_path)
        except ValueError as error:
            raise MediaInfrastructureError("INVALID_INPUT_PATH", "Input path escapes source root.") from error
        if not path.is_file():
            raise MediaInfrastructureError("ASSET_NOT_FOUND", "Input file does not exist.")
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as error:
            raise MediaInfrastructureError("STORAGE_ERROR", "Could not fingerprint input file.") from error
        return digest.hexdigest()


class RenderWorker:
    def __init__(
        self,
        repository: JobRepository,
        prober: MediaProber,
        encoder: SyntheticEncoder,
        verifier: ArtifactVerifier,
        artifacts: ArtifactStore,
        source_root: str | Path,
        *,
        admission: RenderAdmissionCoordinator,
        event_sink: JobEventSink | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.repository = repository
        self.prober = prober
        self.encoder = encoder
        self.verifier = verifier
        self.artifacts = artifacts
        self.source_root = Path(source_root).resolve()
        self.admission = admission
        self.event_sink = event_sink
        self.clock = clock or SystemClock()
        self._lock = threading.Lock()
        self._control_lock = threading.Lock()
        self._cancel_events: dict[tuple[str, str], threading.Event] = {}
        self._startup_reconciled = False

    def run_next(self) -> tuple[RenderSnapshot, JobStatus] | None:
        if not self._lock.acquire(blocking=False):
            return None
        try:
            with self.repository.worker_lock():
                if not self._startup_reconciled:
                    self._reconcile_locked()
                    self._startup_reconciled = True
                claimed = self.repository.claim_next()
                if claimed is None:
                    return None
                snapshot, running = claimed
                token = threading.Event()
                identity = (snapshot.job_id, snapshot.attempt_id)
                with self._control_lock:
                    self._cancel_events[identity] = token
                    try:
                        if self._current_status(snapshot).status is JobState.CANCEL_REQUESTED:
                            token.set()
                    except BaseException:
                        self._cancel_events.pop(identity, None)
                        raise
                started = time.monotonic()
                self._emit(snapshot, "worker", "started", started)
                try:
                    try:
                        with self.admission.acquire_wu2(token):
                            if token.is_set():
                                return snapshot, self._finish_cancelled(snapshot, started)
                            return self._execute(snapshot, running, token, started)
                    except RenderAdmissionCancelled:
                        return snapshot, self._finish_cancelled(snapshot, started)
                except IndeterminateMediaCommitError:
                    self._startup_reconciled = False
                    raise
                finally:
                    with self._control_lock:
                        self._cancel_events.pop(identity, None)
        finally:
            self._lock.release()

    def request_cancel(self, job_id: str, attempt_id: str | None = None) -> JobStatus:
        with self._control_lock:
            while True:
                snapshot, status = (
                    self.repository.get_attempt(job_id, attempt_id)
                    if attempt_id is not None
                    else self.repository.get(job_id)
                )
                with self.repository.publication_lock(job_id, status.attempt_id):
                    snapshot, status = self.repository.get_attempt(job_id, status.attempt_id)
                    if attempt_id is None and self.repository.get(job_id)[1].attempt_id != status.attempt_id:
                        continue
                    if status.status in {JobState.CANCEL_REQUESTED, JobState.COMPLETED}:
                        return status
                    if status.status is JobState.QUEUED:
                        updated = status.transition(JobState.CANCELLED, self.clock.now())
                        event_name = "cancelled_before_start"
                    elif status.status in {JobState.RUNNING, JobState.VALIDATING}:
                        updated = status.transition(JobState.CANCEL_REQUESTED, self.clock.now())
                        event_name = "cancel_requested"
                    else:
                        raise MediaInfrastructureError(
                            "INVALID_CANCELLATION", "Job is not cancellable in its current state."
                        )
                    try:
                        saved = self.repository.update_status(updated, status.revision)
                    except MediaInfrastructureError as error:
                        if error.code == "REVISION_CONFLICT":
                            continue
                        raise
                    token = self._cancel_events.get((job_id, status.attempt_id))
                    if token is not None:
                        token.set()
                    self._emit(snapshot, "cancel", event_name, time.monotonic())
                    return saved

    def reconcile(self) -> list[tuple[RenderSnapshot, JobStatus]]:
        with self.repository.worker_lock():
            return self._reconcile_locked()

    def _reconcile_locked(self) -> list[tuple[RenderSnapshot, JobStatus]]:
        reconciled: list[tuple[RenderSnapshot, JobStatus]] = []
        for snapshot, _initial_status in self.repository.all_attempts():
            with self.repository.publication_lock(snapshot.job_id, snapshot.attempt_id):
                snapshot, status = self.repository.get_attempt(snapshot.job_id, snapshot.attempt_id)
                if status.status not in {
                    JobState.RUNNING, JobState.VALIDATING, JobState.CANCEL_REQUESTED
                }:
                    continue
                recovered = self._reconcile_attempt(snapshot, status)
                if recovered is not None:
                    reconciled.append(recovered)
        return reconciled

    def _reconcile_attempt(
        self, snapshot: RenderSnapshot, status: JobStatus
    ) -> tuple[RenderSnapshot, JobStatus] | None:
        if status.status not in {
            JobState.RUNNING, JobState.VALIDATING, JobState.CANCEL_REQUESTED
        }:
            return None
        plan = self._plan(snapshot)
        final = self.artifacts.resolve_final(plan.output_relative_path)
        expected = self._expected(plan)
        try:
            self._verify_fingerprints(snapshot)
            self.verifier.verify(final, expected)
            if status.status is JobState.CANCEL_REQUESTED and not self.artifacts.has_promotion_record(
                snapshot.job_id, snapshot.attempt_id, final
            ):
                raise MediaInfrastructureError(
                    "PROMOTION_ORDER_UNKNOWN",
                    "A valid final exists without durable evidence that promotion preceded cancellation.",
                )
            if status.status is JobState.RUNNING:
                validating = status.transition(JobState.VALIDATING, self.clock.now())
                status = self.repository.update_status(validating, status.revision)
            next_state = JobState.COMPLETED
            reason = (
                "verified_promotion_receipt_preceded_cancellation"
                if status.status is JobState.CANCEL_REQUESTED
                else "verified_promoted_artifact_reconciled"
            )
        except MediaInfrastructureError as error:
            next_state = (
                JobState.CANCELLED
                if status.status is JobState.CANCEL_REQUESTED and error.code != "PROMOTION_ORDER_UNKNOWN"
                else JobState.FAILED
            )
            reason = error.code
            self.artifacts.cleanup_owned(snapshot.job_id, snapshot.attempt_id)
        updated = status.transition(
            next_state,
            self.clock.now(),
            error=None if next_state is JobState.COMPLETED else {
                "code": "RECOVERABLE_INTERRUPTION",
                "message": reason,
            },
        )
        saved = self.repository.update_status(updated, status.revision)
        self._emit(snapshot, "recovery", reason, time.monotonic())
        return snapshot, saved

    def _execute(
        self,
        snapshot: RenderSnapshot,
        status: JobStatus,
        token: threading.Event,
        started: float,
    ) -> tuple[RenderSnapshot, JobStatus]:
        try:
            plan = self._plan(snapshot)
            source = self._source_path(snapshot, plan)
            input_probe = self.prober.probe(source)
            if input_probe.duration_seconds is None or input_probe.duration_seconds <= 0:
                raise MediaInfrastructureError("INVALID_INPUT", "Synthetic audio must have a positive probed duration.")
            if not any(stream.codec_type == "audio" for stream in input_probe.streams):
                raise MediaInfrastructureError("INVALID_INPUT", "Synthetic input has no audio stream.")
            self._verify_fingerprints(snapshot)
            final = self.artifacts.resolve_final(plan.output_relative_path)
            expected = self._expected(plan)
            if final.exists():
                self.verifier.verify(final, expected)
                try:
                    validating = self._transition_current(snapshot, JobState.VALIDATING)
                    completed = validating.transition(JobState.COMPLETED, self.clock.now(), progress_percent=100)
                    self.repository.update_status(completed, validating.revision)
                except Exception as error:
                    raise IndeterminateMediaCommitError(
                        "A verified final artifact exists but completion status could not be persisted.",
                        {"job_id": snapshot.job_id, "attempt_id": snapshot.attempt_id},
                    ) from error
                self._emit(snapshot, "render", "matching_verified_artifact_reused", started)
                return snapshot, completed

            staged = self.artifacts.stage_path(
                snapshot.job_id, snapshot.attempt_id, plan.output_relative_path
            )
            if token.is_set():
                return snapshot, self._finish_cancelled(snapshot, started)
            self.encoder.encode(
                plan,
                source,
                staged,
                token,
                heartbeat=lambda: self._heartbeat(snapshot),
                progress=lambda percent: self._record_progress(snapshot, percent),
            )
            command = getattr(self.encoder, "last_sanitized_command", None)
            if command:
                self._emit(snapshot, "process", "ffmpeg_command", started, command=command)
            if token.is_set():
                self.artifacts.cleanup_owned(snapshot.job_id, snapshot.attempt_id)
                return snapshot, self._finish_cancelled(snapshot, started)
            self._verify_fingerprints(snapshot)
            current = self._current_status(snapshot)
            if current.status is JobState.CANCEL_REQUESTED:
                self.artifacts.cleanup_owned(snapshot.job_id, snapshot.attempt_id)
                return snapshot, self._finish_cancelled(snapshot, started)
            validating = self._transition_current(snapshot, JobState.VALIDATING)
            if validating.status is JobState.CANCEL_REQUESTED:
                self.artifacts.cleanup_owned(snapshot.job_id, snapshot.attempt_id)
                return snapshot, self._finish_cancelled(snapshot, started)
            self.verifier.verify(staged, expected)
            if token.is_set():
                self.artifacts.cleanup_owned(snapshot.job_id, snapshot.attempt_id)
                return snapshot, self._finish_cancelled(snapshot, started)
            with self._control_lock, self.repository.publication_lock(
                snapshot.job_id, snapshot.attempt_id
            ):
                current = self._current_status(snapshot)
                if token.is_set() or current.status is JobState.CANCEL_REQUESTED:
                    self.artifacts.cleanup_owned(snapshot.job_id, snapshot.attempt_id)
                    return snapshot, self._finish_cancelled(snapshot, started)
                self._verify_fingerprints(snapshot)
                promoted = False
                try:
                    self.artifacts.promote(staged, plan.output_relative_path)
                    promoted = True
                    self._emit(snapshot, "artifact", "verified_artifact_promoted", started)
                    completed = self._transition_current(
                        snapshot, JobState.COMPLETED, progress_percent=100
                    )
                    self._emit(snapshot, "worker", "completed", started)
                except Exception as error:
                    if not promoted:
                        raise
                    raise IndeterminateMediaCommitError(
                        "Artifact was promoted but completion status could not be persisted.",
                        {"job_id": snapshot.job_id, "attempt_id": snapshot.attempt_id},
                    ) from error
            return snapshot, completed
        except IndeterminateMediaCommitError:
            raise
        except MediaInfrastructureError as error:
            current = self._current_status(snapshot)
            if current.status is JobState.CANCEL_REQUESTED and error.code == "PROCESS_CANCELLED":
                self.artifacts.cleanup_owned(snapshot.job_id, snapshot.attempt_id)
                return snapshot, self._finish_cancelled(snapshot, started)
            if current.status in {JobState.RUNNING, JobState.VALIDATING, JobState.CANCEL_REQUESTED}:
                failed = current.transition(
                    JobState.FAILED,
                    self.clock.now(),
                    error=error.to_dict(),
                    commit_state=error.commit_state,
                )
                saved = self.repository.update_status(failed, current.revision)
            else:
                saved = current
            self._emit(snapshot, "worker", "failed", started, error.to_dict())
            self.artifacts.cleanup_owned(snapshot.job_id, snapshot.attempt_id)
            return snapshot, saved

    def _finish_cancelled(self, snapshot: RenderSnapshot, started: float) -> JobStatus:
        while True:
            current = self._current_status(snapshot)
            if current.status is JobState.RUNNING:
                updated = current.transition(JobState.CANCEL_REQUESTED, self.clock.now())
            elif current.status is JobState.CANCEL_REQUESTED:
                updated = current.transition(JobState.CANCELLED, self.clock.now())
            else:
                return current
            try:
                saved = self.repository.update_status(updated, current.revision)
            except MediaInfrastructureError as error:
                if error.code == "REVISION_CONFLICT":
                    continue
                raise
            if saved.status is JobState.CANCELLED:
                self._emit(snapshot, "worker", "cancelled_and_reaped", started)
            return saved

    def _transition_current(
        self,
        snapshot: RenderSnapshot,
        state: JobState,
        *,
        progress_percent: float | None = None,
    ) -> JobStatus:
        while True:
            current = self._current_status(snapshot)
            if state is JobState.VALIDATING and current.status is JobState.CANCEL_REQUESTED:
                return current
            if current.status is JobState.CANCEL_REQUESTED and state is JobState.COMPLETED:
                self._emit(snapshot, "cancel", "verified_promotion_completed_before_cancel_ack", time.monotonic())
            updated = current.transition(state, self.clock.now(), progress_percent=progress_percent)
            try:
                return self.repository.update_status(updated, current.revision)
            except MediaInfrastructureError as error:
                if error.code == "REVISION_CONFLICT":
                    continue
                raise

    def _current_status(self, snapshot: RenderSnapshot) -> JobStatus:
        return self.repository.get_attempt(snapshot.job_id, snapshot.attempt_id)[1]

    def _heartbeat(self, snapshot: RenderSnapshot) -> None:
        current = self._current_status(snapshot)
        if current.status is JobState.CANCEL_REQUESTED:
            raise MediaInfrastructureError("PROCESS_CANCELLED", "Cancellation was accepted by another worker.")
        if current.status not in {
            JobState.RUNNING,
            JobState.VALIDATING,
            JobState.CANCEL_REQUESTED,
        }:
            return
        updated = current.heartbeat(self.clock.now())
        try:
            self.repository.update_status(updated, current.revision)
        except MediaInfrastructureError as error:
            if error.code != "REVISION_CONFLICT":
                raise

    def _record_progress(self, snapshot: RenderSnapshot, progress_percent: float) -> None:
        while True:
            current = self._current_status(snapshot)
            if current.status not in {JobState.RUNNING, JobState.VALIDATING}:
                return
            updated = current.report_progress(progress_percent, self.clock.now())
            try:
                self.repository.update_status(updated, current.revision)
                return
            except MediaInfrastructureError as error:
                if error.code != "REVISION_CONFLICT":
                    raise

    def _plan(self, snapshot: RenderSnapshot) -> RenderPlan:
        request = snapshot.request
        try:
            if request["kind"] != "synthetic-proof":
                raise ValueError("kind")
            plan = RenderPlan(
                snapshot=snapshot,
                output_relative_path=request["output_relative_path"],
                duration_seconds=float(request["duration_seconds"]),
                width=int(request["width"]),
                height=int(request["height"]),
                frame_rate=int(request["frame_rate"]),
                tone_hz=int(request.get("tone_hz", 440)),
                duration_tolerance_seconds=float(request["duration_tolerance_seconds"]),
                video_codec=request["video_codec"],
                audio_codec=request["audio_codec"],
                pixel_format=request["pixel_format"],
            )
            if (
                not math.isfinite(plan.duration_seconds)
                or plan.duration_seconds <= 0
                or not math.isfinite(plan.duration_tolerance_seconds)
                or plan.duration_tolerance_seconds < 0
                or plan.width <= 0
                or plan.height <= 0
                or plan.frame_rate <= 0
                or plan.tone_hz <= 0
                or (plan.video_codec, plan.audio_codec, plan.pixel_format)
                != ("h264", "aac", "yuv420p")
            ):
                raise ValueError("invalid synthetic proof settings")
            return plan
        except (KeyError, TypeError, ValueError) as error:
            raise MediaInfrastructureError("INVALID_RENDER_PLAN", "Synthetic proof request is incomplete.") from error

    def _source_path(self, snapshot: RenderSnapshot, plan: RenderPlan) -> Path:
        inputs = [item for item in snapshot.inputs if item.relative_path == plan.snapshot.request.get("inputs", [None])[0]]
        if not inputs:
            raise MediaInfrastructureError("INVALID_JOB", "Synthetic input is not fingerprinted in snapshot.")
        source = (self.source_root / Path(*PurePosixPath(inputs[0].relative_path).parts)).resolve()
        try:
            source.relative_to(self.source_root)
        except ValueError as error:
            raise MediaInfrastructureError("INVALID_INPUT_PATH", "Input escaped configured source root.") from error
        return source

    def _verify_fingerprints(self, snapshot: RenderSnapshot) -> None:
        for item in snapshot.inputs:
            current = MediaJobs._fingerprint(self.source_root, item.relative_path)
            if current != item.sha256:
                raise MediaInfrastructureError("SOURCE_CHANGED", "Input changed since snapshot creation.")

    @staticmethod
    def _expected(plan: RenderPlan) -> dict[str, Any]:
        return {
            "video_codec": plan.video_codec,
            "audio_codec": plan.audio_codec,
            "pixel_format": plan.pixel_format,
            "width": plan.width,
            "height": plan.height,
            "duration_seconds": plan.duration_seconds,
            "duration_tolerance_seconds": plan.duration_tolerance_seconds,
            "frame_rate": plan.frame_rate,
            "snapshot_digest": plan.snapshot.snapshot_digest,
        }

    def _emit(
        self,
        snapshot: RenderSnapshot,
        phase: str,
        event: str,
        started: float,
        error: Mapping[str, Any] | None = None,
        command: tuple[str, ...] | None = None,
    ) -> None:
        if self.event_sink is None:
            return
        elapsed = int(max(0, time.monotonic() - started) * 1000)
        self.event_sink.emit(
            JobEvent(
                timestamp=utc_timestamp(self.clock.now()),
                job_id=snapshot.job_id,
                attempt_id=snapshot.attempt_id,
                phase=phase,
                event=event,
                elapsed_ms=elapsed,
                error=error,
                command=command,
            )
        )
