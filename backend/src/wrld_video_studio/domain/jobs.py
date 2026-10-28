from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping

from wrld_video_studio.domain.canonical_json import canonical_json_bytes, canonical_sha256


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


class ArtifactState(StrEnum):
    PENDING = "pending"
    STAGED = "staged"
    VALIDATED = "validated"
    PROMOTED = "promoted"
    FAILED = "failed"
    CANCELLED = "cancelled"


ALLOWED_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.QUEUED: frozenset({JobState.RUNNING, JobState.CANCELLED}),
    JobState.RUNNING: frozenset(
        {JobState.VALIDATING, JobState.FAILED, JobState.CANCEL_REQUESTED}
    ),
    JobState.VALIDATING: frozenset(
        {JobState.COMPLETED, JobState.FAILED, JobState.CANCEL_REQUESTED}
    ),
    JobState.CANCEL_REQUESTED: frozenset(
        {JobState.CANCELLED, JobState.FAILED, JobState.COMPLETED}
    ),
    JobState.COMPLETED: frozenset(),
    JobState.FAILED: frozenset(),
    JobState.CANCELLED: frozenset(),
}


@dataclass(frozen=True)
class InputFingerprint:
    relative_path: str
    sha256: str

    def to_dict(self) -> dict[str, str]:
        return {"relative_path": self.relative_path, "sha256": self.sha256}


@dataclass(frozen=True)
class RenderSnapshot:
    schema_version: str
    job_id: str
    attempt_id: str
    created_at: str
    renderer_version: str
    request_digest: str
    inputs: tuple[InputFingerprint, ...]
    _request_json: bytes

    @property
    def request(self) -> dict[str, Any]:
        import json

        return json.loads(self._request_json)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "attempt_id": self.attempt_id,
            "created_at": self.created_at,
            "renderer_version": self.renderer_version,
            "request_digest": self.request_digest,
            "request": self.request,
            "inputs": [item.to_dict() for item in self.inputs],
        }

    @property
    def snapshot_digest(self) -> str:
        return canonical_sha256(self.to_dict())


def create_snapshot(
    *,
    job_id: str,
    attempt_id: str,
    created_at: str,
    renderer_version: str,
    request: Mapping[str, Any],
    inputs: tuple[InputFingerprint, ...],
) -> RenderSnapshot:
    request_bytes = canonical_json_bytes(dict(request))
    input_dicts = [item.to_dict() for item in sorted(inputs, key=lambda item: item.relative_path)]
    request_digest = canonical_sha256(
        {
            "renderer_version": renderer_version,
            "request": __import__("json").loads(request_bytes),
            "inputs": input_dicts,
        }
    )
    return RenderSnapshot(
        schema_version="1.0",
        job_id=job_id,
        attempt_id=attempt_id,
        created_at=created_at,
        renderer_version=renderer_version,
        request_digest=request_digest,
        inputs=tuple(sorted(inputs, key=lambda item: item.relative_path)),
        _request_json=request_bytes,
    )


@dataclass(frozen=True)
class JobStatus:
    schema_version: str
    job_id: str
    attempt_id: str
    snapshot_digest: str
    revision: int
    status: JobState
    created_at: str
    updated_at: str
    progress_percent: float | None = None
    last_heartbeat_at: str | None = None
    error: Mapping[str, Any] | None = None
    commit_state: str | None = None

    @classmethod
    def queued(cls, snapshot: RenderSnapshot, now: datetime | None = None) -> JobStatus:
        timestamp = utc_timestamp(now)
        return cls(
            schema_version="1.0",
            job_id=snapshot.job_id,
            attempt_id=snapshot.attempt_id,
            snapshot_digest=snapshot.snapshot_digest,
            revision=0,
            status=JobState.QUEUED,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def transition(
        self,
        next_state: JobState,
        now: datetime | None = None,
        *,
        progress_percent: float | None = None,
        heartbeat_at: str | None = None,
        error: Mapping[str, Any] | None = None,
        commit_state: str | None = None,
    ) -> JobStatus:
        if next_state not in ALLOWED_TRANSITIONS[self.status]:
            raise ValueError(f"Illegal job transition: {self.status} -> {next_state}")
        if progress_percent is not None:
            if not 0 <= progress_percent <= 100:
                raise ValueError("Progress must be within [0, 100]")
            if self.progress_percent is not None and progress_percent < self.progress_percent:
                raise ValueError("Known progress cannot regress")
        return replace(
            self,
            revision=self.revision + 1,
            status=next_state,
            updated_at=utc_timestamp(now),
            progress_percent=(
                self.progress_percent if progress_percent is None else progress_percent
            ),
            last_heartbeat_at=heartbeat_at or self.last_heartbeat_at,
            error=error,
            commit_state=commit_state,
        )

    def heartbeat(self, now: datetime | None = None) -> JobStatus:
        if self.status not in {JobState.RUNNING, JobState.VALIDATING, JobState.CANCEL_REQUESTED}:
            raise ValueError(f"Heartbeat is not valid for job state {self.status}")
        timestamp = utc_timestamp(now)
        return replace(
            self,
            revision=self.revision + 1,
            updated_at=timestamp,
            last_heartbeat_at=timestamp,
        )

    def report_progress(self, progress_percent: float, now: datetime | None = None) -> JobStatus:
        if self.status not in {JobState.RUNNING, JobState.VALIDATING}:
            raise ValueError(f"Progress is not valid for job state {self.status}")
        if not 0 <= progress_percent <= 100:
            raise ValueError("Progress must be within [0, 100]")
        if self.progress_percent is not None and progress_percent < self.progress_percent:
            raise ValueError("Known progress cannot regress")
        return replace(
            self,
            revision=self.revision + 1,
            updated_at=utc_timestamp(now),
            progress_percent=progress_percent,
        )

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "attempt_id": self.attempt_id,
            "snapshot_digest": self.snapshot_digest,
            "revision": self.revision,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "progress_percent": self.progress_percent,
            "last_heartbeat_at": self.last_heartbeat_at,
            "error": None if self.error is None else dict(self.error),
        }
        if self.commit_state is not None:
            value["commit_state"] = self.commit_state
        return value


@dataclass(frozen=True)
class MediaStream:
    index: int
    codec_type: str
    codec_name: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    width: int | None = None
    height: int | None = None
    frame_rate: float | None = None
    duration_seconds: float | None = None
    duration_ts: int | None = None
    time_base_numerator: int | None = None
    time_base_denominator: int | None = None
    pixel_format: str | None = None
    profile: str | None = None
    color_space: str | None = None
    color_transfer: str | None = None
    color_primaries: str | None = None


@dataclass(frozen=True)
class MediaProbe:
    source_path: str
    tool_version: str
    duration_seconds: float | None
    streams: tuple[MediaStream, ...]
    format_name: str | None = None
    format_tags: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RenderPlan:
    snapshot: RenderSnapshot
    output_relative_path: str
    duration_seconds: float
    width: int
    height: int
    frame_rate: int
    tone_hz: int
    duration_tolerance_seconds: float
    video_codec: str
    audio_codec: str
    pixel_format: str


@dataclass(frozen=True)
class JobEvent:
    timestamp: str
    job_id: str
    attempt_id: str
    phase: str
    event: str
    elapsed_ms: int
    error: Mapping[str, Any] | None = None
    command: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ProcessExecution:
    returncode: int
    stdout: str
    stderr_tail: str
    timed_out: bool = False
    cancelled: bool = False
    sanitized_argv: tuple[str, ...] = ()


def utc_timestamp(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
