from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wrld_video_studio.application.media_jobs import MediaJobs
from wrld_video_studio.application.ports.video_export import (
    VideoExportPathValidator,
    VideoProjectLoader,
)
from wrld_video_studio.domain.jobs import JobStatus, RenderSnapshot
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.video_export import (
    VideoManifest,
    VideoExportRequest,
    create_plan,
    parse_export_request,
)
from wrld_video_studio.domain.video_export_v2 import (
    MOTION_RENDERER_VERSION,
    MotionVideoExportRequest,
    MotionVideoManifest,
    create_motion_plan,
    parse_motion_export_request,
)
from wrld_video_studio.domain.video_export_v3 import (
    REFINED_RENDERER_VERSION,
    RefinedVideoExportRequest,
    RefinedVideoManifest,
    create_refined_plan,
    parse_refined_export_request,
)
from wrld_video_studio.domain.video_export_v4 import (
    PLAYER_RENDERER_VERSION,
    PlayerVideoExportRequest,
    PlayerVideoManifest,
    create_player_plan,
    parse_player_export_request,
)
from wrld_video_studio.domain.jobs import JobState


VIDEO_RENDERER_VERSION = "wu3a-video-export-1"


@dataclass(frozen=True)
class SubmittedVideoExport:
    project_root: Path
    snapshot: RenderSnapshot
    status: JobStatus


class VideoExports:
    def __init__(
        self,
        loader: VideoProjectLoader,
        jobs: MediaJobs,
        *,
        path_validator: VideoExportPathValidator | None = None,
        tool_identity: dict[str, Any] | None = None,
    ) -> None:
        self.loader = loader
        self.jobs = jobs
        self.path_validator = path_validator
        self.tool_identity = dict(tool_identity or {})

    def submit(
        self,
        album_project: str | Path,
        request: VideoExportRequest | MotionVideoExportRequest | RefinedVideoExportRequest | PlayerVideoExportRequest,
        *,
        force: bool = False,
    ) -> SubmittedVideoExport:
        project = self.loader.load(album_project)
        if isinstance(project.manifest, PlayerVideoManifest):
            if not isinstance(request, PlayerVideoExportRequest):
                raise MediaInfrastructureError(
                    "PROFILE_MISMATCH", "The request profile does not match the manifest profile."
                )
            request = parse_player_export_request(request.to_dict())
            plan = create_player_plan(project.manifest, request)
            renderer_version = PLAYER_RENDERER_VERSION
        elif isinstance(project.manifest, RefinedVideoManifest):
            if not isinstance(request, RefinedVideoExportRequest):
                raise MediaInfrastructureError(
                    "PROFILE_MISMATCH", "The request profile does not match the manifest profile."
                )
            request = parse_refined_export_request(request.to_dict())
            plan = create_refined_plan(project.manifest, request)
            renderer_version = REFINED_RENDERER_VERSION
        elif isinstance(project.manifest, MotionVideoManifest):
            if not isinstance(request, MotionVideoExportRequest):
                raise MediaInfrastructureError(
                    "PROFILE_MISMATCH", "The request profile does not match the manifest profile."
                )
            request = parse_motion_export_request(request.to_dict())
            plan = create_motion_plan(project.manifest, request)
            renderer_version = MOTION_RENDERER_VERSION
        elif isinstance(project.manifest, VideoManifest):
            if not isinstance(request, VideoExportRequest):
                raise MediaInfrastructureError(
                    "PROFILE_MISMATCH", "The request profile does not match the manifest profile."
                )
            request = parse_export_request(request.to_dict())
            plan = create_plan(project.manifest, request)
            renderer_version = VIDEO_RENDERER_VERSION
        else:
            raise MediaInfrastructureError(
                "MANIFEST_UNSUPPORTED", "The video manifest version is unsupported."
            )
        if self.path_validator is not None:
            self.path_validator.validate(project.root, plan)
        portable_request = request.to_dict()
        internal_request: dict[str, Any] = {
            "kind": "video-export",
            "export_request": portable_request,
            "manifest": dict(project.manifest_document),
            "output_relative_path": plan.output_relative_path,
            "artifact_kind": plan.artifact_kind,
            "toolchain": self.tool_identity,
        }
        inputs = ["video_manifest.json", project.manifest.background]
        inputs.extend(track.audio for track in plan.selected_tracks)
        if isinstance(project.manifest, PlayerVideoManifest):
            assert project.manifest.effects.player is not None
            inputs.append(project.manifest.effects.player.font.path)
        snapshot, status = self.jobs.submit(
            internal_request,
            project.root,
            renderer_version,
            force=force,
            input_paths=inputs,
        )
        if status.status in {JobState.FAILED, JobState.CANCELLED} and not force:
            snapshot, status = self.jobs.retry(snapshot.job_id, project.root)
        return SubmittedVideoExport(project.root, snapshot, status)
