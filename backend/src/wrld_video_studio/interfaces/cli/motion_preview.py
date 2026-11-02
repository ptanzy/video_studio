from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from wrld_video_studio.application.motion_preview import MotionPreviews
from wrld_video_studio.application.render_coordination import ProcessLocalRenderAdmission
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.motion_preview import (
    DEFAULT_PREVIEW_SAMPLES,
    MotionPreviewExcerpt,
    resolve_motion_preview_request,
)
from wrld_video_studio.domain.motion_preview_v2 import (
    resolve_refined_motion_preview_request,
)
from wrld_video_studio.domain.motion_preview_v3 import resolve_player_motion_preview_request
from wrld_video_studio.domain.player_overlay import select_resolved_player
from wrld_video_studio.domain.video_export import ExportTarget
from wrld_video_studio.domain.video_export_v2 import MOTION_PROFILE_ID, MotionVideoManifest
from wrld_video_studio.domain.video_export_v3 import REFINED_PROFILE_ID, RefinedVideoManifest
from wrld_video_studio.domain.video_export_v4 import PLAYER_PROFILE_ID, PlayerVideoManifest
from wrld_video_studio.infrastructure.artwork_theme import FFmpegArtworkThemeResolver
from wrld_video_studio.infrastructure.artifact_verifier import FFmpegArtifactVerifier
from wrld_video_studio.infrastructure.ffprobe_adapter import FFprobeAdapter
from wrld_video_studio.infrastructure.media_tools import MediaToolchain
from wrld_video_studio.infrastructure.process_runner import SubprocessRunner
from wrld_video_studio.infrastructure.project_sources import FilesystemVideoProjectLoader
from wrld_video_studio.infrastructure.render_attempt_records import (
    JsonRenderDiagnosticStore,
    JsonRenderProgressStore,
)
from wrld_video_studio.infrastructure.video_export_renderer import StaticVideoExportRenderer
from wrld_video_studio.interfaces.cli.video_export import (
    _error,
    _schema_root,
    _tool_identity,
    default_state_root,
    project_identity,
    _format_progress,
)


def add_motion_preview_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "motion-preview", help="Render and temporarily hold one verified WU3B motion preview"
    )
    parser.add_argument("--album-project", required=True)
    parser.add_argument("--target", choices=("album", "track"), required=True)
    parser.add_argument("--track-id")
    parser.add_argument(
        "--profile",
        default=MOTION_PROFILE_ID,
        choices=(MOTION_PROFILE_ID, REFINED_PROFILE_ID, PLAYER_PROFILE_ID),
    )
    parser.add_argument("--start-sample", type=int, default=0)
    parser.add_argument("--sample-count", type=int, default=DEFAULT_PREVIEW_SAMPLES)
    parser.add_argument("--ffmpeg-path")
    parser.add_argument("--ffprobe-path")
    parser.set_defaults(command=run_motion_preview)


def run_motion_preview(args: argparse.Namespace, *, state_root: Path | None = None) -> int:
    if (args.ffmpeg_path is None) != (args.ffprobe_path is None):
        return _error("INVALID_TOOL_PATH", "FFmpeg and FFprobe overrides must be supplied together.")
    if args.target == "album" and args.track_id is not None:
        return _error("PREVIEW_INVALID_REQUEST", "--track-id is valid only for a track target.")
    if args.target == "track" and not args.track_id:
        return _error("PREVIEW_INVALID_REQUEST", "A track target requires --track-id.")
    project = Path(args.album_project).expanduser()
    if not project.is_absolute():
        return _error("PROJECT_PATH_INVALID", "--album-project must be an absolute path.")
    configured: dict[str, Path] = {}
    if args.ffmpeg_path is not None:
        configured = {"ffmpeg": Path(args.ffmpeg_path), "ffprobe": Path(args.ffprobe_path)}
        if not all(path.is_absolute() for path in configured.values()):
            return _error("INVALID_TOOL_PATH", "Media-tool overrides must be absolute paths.")
    service: MotionPreviews | None = None
    lease = None
    result_code = 0
    cleanup_error: MediaInfrastructureError | None = None
    try:
        project = project.resolve(strict=True)
        schemas = _schema_root()
        state_base = state_root or default_state_root()
        identity_key = project_identity(project)
        root = state_base / identity_key
        runner = SubprocessRunner()
        tools = MediaToolchain(runner, configured)
        identity = _tool_identity(tools)
        prober = FFprobeAdapter(tools, runner)
        loader = FilesystemVideoProjectLoader(
            (
                schemas / "video-manifest-v1.schema.json",
                schemas / "video-manifest-v2.schema.json",
                schemas / "video-manifest-v3.schema.json",
                schemas / "video-manifest-v4.schema.json",
            ),
            prober=prober,
            theme_resolver=FFmpegArtworkThemeResolver(tools, runner),
        )
        loaded = loader.load(project)
        target = ExportTarget(args.target, args.track_id if args.target == "track" else None)
        excerpt = MotionPreviewExcerpt(args.start_sample, args.sample_count)
        if isinstance(loaded.manifest, PlayerVideoManifest):
            if args.profile != PLAYER_PROFILE_ID or loaded.resolved_player is None:
                raise MediaInfrastructureError(
                    "PROFILE_MISMATCH", "The request profile does not match the manifest profile."
                )
            selected_ids = (
                tuple(track.id for track in loaded.manifest.tracks)
                if target.kind == "album"
                else (target.track_id,)
            )
            request = resolve_player_motion_preview_request(
                loaded.manifest,
                target,
                select_resolved_player(loaded.resolved_player, selected_ids),
                excerpt,
            )
        elif isinstance(loaded.manifest, RefinedVideoManifest):
            if args.profile != REFINED_PROFILE_ID:
                raise MediaInfrastructureError(
                    "PROFILE_MISMATCH", "The request profile does not match the manifest profile."
                )
            request = resolve_refined_motion_preview_request(
                loaded.manifest, target, excerpt
            )
        elif isinstance(loaded.manifest, MotionVideoManifest):
            if args.profile != MOTION_PROFILE_ID:
                raise MediaInfrastructureError(
                    "PROFILE_MISMATCH", "The request profile does not match the manifest profile."
                )
            request = resolve_motion_preview_request(loaded.manifest, target, excerpt)
        else:
            raise MediaInfrastructureError(
                "PROFILE_MISMATCH", "Motion previews require a supported motion project manifest."
            )
        service = MotionPreviews(
            loader,
            StaticVideoExportRenderer(tools, runner),
            FFmpegArtifactVerifier(prober, tools, runner),
            ProcessLocalRenderAdmission(),
            root / "motion-previews",
            tool_identity=identity,
            progress_store=JsonRenderProgressStore(
                root / "progress", schemas / "render-progress-v1.schema.json"
            ),
            diagnostic_store=JsonRenderDiagnosticStore(
                state_base / "diagnostics" / identity_key[:24],
                schemas / "render-diagnostic-v1.schema.json",
                fallback_root=state_base / "diagnostics-fallback" / identity_key[:24],
            ),
            progress_observer=lambda progress: print(
                _format_progress(progress), file=sys.stderr, flush=True
            ),
        )
        lease = service.prepare(project, request)
        print(json.dumps(lease.result.to_dict(), ensure_ascii=False, sort_keys=True))
        print(f"Verified temporary preview: {lease.path}", file=sys.stderr, flush=True)
        print(
            "Open the MP4 now. Press Enter here to release the final lease and delete it.",
            file=sys.stderr,
            flush=True,
        )
        input()
        result_code = 0
    except MediaInfrastructureError as error:
        result_code = _error(error.code, error.message, error.details)
    except (OSError, EOFError):
        result_code = _error("STORAGE_ERROR", "A required local resource was unavailable.")
    except KeyboardInterrupt:
        result_code = _error("PREVIEW_CANCELLED", "Motion preview was cancelled.")
    finally:
        cleanup_error = _close_preview_resources(lease, service)
    if cleanup_error is not None:
        if result_code == 0:
            return _error(cleanup_error.code, cleanup_error.message, cleanup_error.details)
        print(
            "Motion-preview cleanup also failed; the primary error above remains authoritative.",
            file=sys.stderr,
            flush=True,
        )
    return result_code


def _close_preview_resources(lease: Any, service: MotionPreviews | None) -> MediaInfrastructureError | None:
    cleanup_error: MediaInfrastructureError | None = None
    if lease is not None:
        try:
            lease.close()
        except MediaInfrastructureError as error:
            cleanup_error = error
    if service is not None:
        try:
            service.close()
        except MediaInfrastructureError as error:
            cleanup_error = cleanup_error or error
    return cleanup_error
