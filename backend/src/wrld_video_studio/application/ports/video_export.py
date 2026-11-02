from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol

from wrld_video_studio.domain.video_export import VideoExportPlan, VideoManifest
from wrld_video_studio.domain.video_export_v2 import MotionVideoExportPlan, MotionVideoManifest
from wrld_video_studio.domain.video_export_v3 import (
    RefinedVideoExportPlan,
    RefinedVideoManifest,
)
from wrld_video_studio.domain.video_export_v4 import PlayerVideoExportPlan, PlayerVideoManifest


class VideoProjectSource(Protocol):
    root: Path
    manifest: VideoManifest | MotionVideoManifest | RefinedVideoManifest | PlayerVideoManifest

    @property
    def manifest_document(self) -> Mapping[str, Any]: ...


class VideoProjectLoader(Protocol):
    def load(self, album_project: str | Path) -> VideoProjectSource: ...


class VideoExportPathValidator(Protocol):
    def validate(
        self,
        project_root: Path,
        plan: VideoExportPlan | MotionVideoExportPlan | RefinedVideoExportPlan | PlayerVideoExportPlan,
    ) -> None: ...


class VideoExportRenderer(Protocol):
    """Shared renderer port for static and resolved motion-profile exports."""

    def render(
        self,
        plan: VideoExportPlan | MotionVideoExportPlan | RefinedVideoExportPlan | PlayerVideoExportPlan,
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
    ) -> Any: ...
