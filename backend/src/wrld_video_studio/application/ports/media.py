from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from wrld_video_studio.domain.jobs import (
    JobEvent,
    JobStatus,
    MediaProbe,
    ProcessExecution,
    RenderSnapshot,
)


class MediaProber(Protocol):
    def probe(self, path: Path) -> MediaProbe: ...


class ProcessRunner(Protocol):
    def run(
        self,
        argv: list[str],
        timeout_seconds: float,
        cancel_event: Any = None,
        heartbeat: Any = None,
        progress_callback: Any = None,
    ) -> ProcessExecution: ...

    def sanitize_diagnostic(self, text: str) -> str: ...


class JobRepository(Protocol):
    def publication_lock(self, job_id: str, attempt_id: str) -> Any: ...

    def create(self, snapshot: RenderSnapshot, status: JobStatus) -> None: ...

    def get(self, job_id: str) -> tuple[RenderSnapshot, JobStatus]: ...

    def get_attempt(self, job_id: str, attempt_id: str) -> tuple[RenderSnapshot, JobStatus]: ...

    def update_status(
        self, status: JobStatus, expected_revision: int
    ) -> JobStatus: ...

    def find_by_request_digest(self, request_digest: str) -> tuple[RenderSnapshot, JobStatus] | None: ...

    def queued(self) -> list[tuple[RenderSnapshot, JobStatus]]: ...

    def all_attempts(self) -> list[tuple[RenderSnapshot, JobStatus]]: ...


class ArtifactVerifier(Protocol):
    def verify(self, path: Path, expected: Mapping[str, Any]) -> MediaProbe: ...


class SyntheticEncoder(Protocol):
    def encode(
        self,
        plan: Any,
        audio_input: Path,
        staged_output: Path,
        cancel_event: Any = None,
        heartbeat: Any = None,
        progress: Any = None,
    ) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdFactory(Protocol):
    def new_id(self) -> str: ...


class JobEventSink(Protocol):
    def emit(self, event: JobEvent) -> None: ...


class ArtifactStore(Protocol):
    def stage_path(self, job_id: str, attempt_id: str, relative_path: str) -> Path: ...

    def promote(self, staged: Path, relative_path: str) -> Path: ...

    def resolve_final(self, relative_path: str) -> Path: ...

    def cleanup_owned(self, job_id: str, attempt_id: str) -> None: ...

    def has_promotion_record(self, job_id: str, attempt_id: str, final: Path) -> bool: ...
