from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from wrld_video_studio.domain.motion_preview import MotionPreviewPlan
from wrld_video_studio.domain.motion_preview_v2 import RefinedMotionPreviewPlan


class MotionPreviewRenderer(Protocol):
    def render(
        self,
        plan: MotionPreviewPlan | RefinedMotionPreviewPlan,
        audio_sources: tuple[Path, ...],
        background: Path,
        staged_output: Path,
        pcm_paths: tuple[Path, ...],
        combined_pcm: Path,
        request_digest: str,
        cancel_event: Any = None,
        heartbeat: Any = None,
        progress: Any = None,
        effect_control_path: Path | None = None,
        font_path: Path | None = None,
        source_sample_counts: tuple[int, ...] | None = None,
    ) -> Any: ...


class MotionPreviewArtifactLease(Protocol):
    @property
    def path(self) -> Path: ...

    @property
    def result(self) -> Any: ...

    def read(self, amount: int = -1) -> bytes: ...

    def close(self) -> None: ...

    def __enter__(self) -> MotionPreviewArtifactLease: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...
