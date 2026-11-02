from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any


class RenderPhase(StrEnum):
    PREPARING = "preparing"
    SNAPSHOTTING_SOURCES = "snapshotting_sources"
    NORMALIZING_AUDIO = "normalizing_audio"
    ASSEMBLING_AUDIO = "assembling_audio"
    ENCODING = "encoding"
    PROBING_OUTPUT = "probing_output"
    DECODING_OUTPUT = "decoding_output"
    PUBLISHING_ARTIFACTS = "publishing_artifacts"
    PUBLISHING_REPORT = "publishing_report"
    COMPLETED = "completed"


@dataclass(frozen=True)
class RenderProgress:
    job_id: str
    attempt_id: str
    phase: RenderPhase
    phase_progress_percent: float | None
    current_track: int | None
    total_tracks: int | None
    processed_duration_seconds: float | None
    total_duration_seconds: float | None
    elapsed_seconds: float
    eta_seconds: float | None
    last_progress_at: str
    last_heartbeat_at: str | None = None
    failure_phase: RenderPhase | None = None
    diagnostic_reference: str | None = None

    def updated(self, **changes: Any) -> RenderProgress:
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "wrld-render-progress/1.0",
            "job_id": self.job_id,
            "attempt_id": self.attempt_id,
            "phase": self.phase.value,
            "phase_progress_percent": self.phase_progress_percent,
            "current_track": self.current_track,
            "total_tracks": self.total_tracks,
            "processed_duration_seconds": self.processed_duration_seconds,
            "total_duration_seconds": self.total_duration_seconds,
            "elapsed_seconds": self.elapsed_seconds,
            "eta_seconds": self.eta_seconds,
            "last_progress_at": self.last_progress_at,
            "last_heartbeat_at": self.last_heartbeat_at,
            "failure_phase": None if self.failure_phase is None else self.failure_phase.value,
            "diagnostic_reference": self.diagnostic_reference,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RenderProgress:
        return cls(
            job_id=value["job_id"],
            attempt_id=value["attempt_id"],
            phase=RenderPhase(value["phase"]),
            phase_progress_percent=value["phase_progress_percent"],
            current_track=value["current_track"],
            total_tracks=value["total_tracks"],
            processed_duration_seconds=value["processed_duration_seconds"],
            total_duration_seconds=value["total_duration_seconds"],
            elapsed_seconds=value["elapsed_seconds"],
            eta_seconds=value["eta_seconds"],
            last_progress_at=value["last_progress_at"],
            last_heartbeat_at=value["last_heartbeat_at"],
            failure_phase=(
                None if value["failure_phase"] is None else RenderPhase(value["failure_phase"])
            ),
            diagnostic_reference=value["diagnostic_reference"],
        )
