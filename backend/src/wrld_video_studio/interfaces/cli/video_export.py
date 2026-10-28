from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Sequence

from wrld_video_studio.application.media_jobs import MediaJobs, RenderWorker
from wrld_video_studio.application.render_coordination import ProcessLocalRenderAdmission
from wrld_video_studio.application.video_export import VideoExports
from wrld_video_studio.application.video_export_worker import VideoExportJobHandler
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.video_export import ExportTarget, VideoExportRequest
from wrld_video_studio.domain.video_export_v2 import (
    MOTION_PROFILE_ID,
    MotionVideoManifest,
    resolve_motion_export_request,
)
from wrld_video_studio.domain.video_export_v3 import (
    REFINED_PROFILE_ID,
    RefinedVideoManifest,
    resolve_refined_export_request,
)
from wrld_video_studio.domain.player_overlay import select_resolved_player
from wrld_video_studio.domain.video_export_v4 import (
    PLAYER_PROFILE_ID,
    PlayerVideoManifest,
    resolve_player_export_request,
)
from wrld_video_studio.infrastructure.artifact_store import FilesystemArtifactStore
from wrld_video_studio.infrastructure.artwork_theme import FFmpegArtworkThemeResolver
from wrld_video_studio.infrastructure.artifact_verifier import FFmpegArtifactVerifier
from wrld_video_studio.infrastructure.ffmpeg_adapter import SyntheticMediaEncoder
from wrld_video_studio.infrastructure.ffprobe_adapter import FFprobeAdapter
from wrld_video_studio.infrastructure.job_repository import JsonJobRepository
from wrld_video_studio.infrastructure.media_tools import MediaToolchain
from wrld_video_studio.infrastructure.process_runner import SubprocessRunner
from wrld_video_studio.infrastructure.project_sources import FilesystemVideoProjectLoader
from wrld_video_studio.infrastructure.render_attempt_records import (
    JsonRenderDiagnosticStore,
    JsonRenderProgressStore,
)
from wrld_video_studio.infrastructure.render_report_store import JsonVideoResultStore, RenderReportStore
from wrld_video_studio.infrastructure.video_export_renderer import StaticVideoExportRenderer
from wrld_video_studio.infrastructure.video_export_paths import VideoExportPathPreflight


def add_video_export_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("video-export", help="Render one verified album or track MP4")
    parser.add_argument("--album-project", required=True)
    parser.add_argument("--target", choices=("album", "track"), required=True)
    parser.add_argument("--track-id")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--ffmpeg-path")
    parser.add_argument("--ffprobe-path")
    parser.set_defaults(command=run_video_export)


def run_video_export(args: argparse.Namespace, *, state_root: Path | None = None) -> int:
    if (args.ffmpeg_path is None) != (args.ffprobe_path is None):
        return _error("INVALID_TOOL_PATH", "FFmpeg and FFprobe overrides must be supplied together.")
    if args.target == "album" and args.track_id is not None:
        return _error("INVALID_EXPORT_REQUEST", "--track-id is valid only for a track target.")
    if args.target == "track" and not args.track_id:
        return _error("INVALID_EXPORT_REQUEST", "A track target requires --track-id.")
    project = Path(args.album_project).expanduser()
    if not project.is_absolute():
        return _error("PROJECT_PATH_INVALID", "--album-project must be an absolute path.")
    configured: dict[str, Path] = {}
    if args.ffmpeg_path is not None:
        configured = {
            "ffmpeg": Path(args.ffmpeg_path),
            "ffprobe": Path(args.ffprobe_path),
        }
        if not all(path.is_absolute() for path in configured.values()):
            return _error("INVALID_TOOL_PATH", "Media-tool overrides must be absolute paths.")
    try:
        project = project.resolve(strict=True)
        schemas = _schema_root()
        state_base = state_root or default_state_root()
        identity_key = project_identity(project)
        root = state_base / identity_key
        runner = SubprocessRunner()
        tools = MediaToolchain(runner, configured)
        tool_identity = _tool_identity(tools)
        prober = FFprobeAdapter(tools, runner)
        repository = JsonJobRepository(
            root / "jobs",
            schemas / "render-job-snapshot-v1.schema.json",
            schemas / "render-job-status-v1.schema.json",
        )
        artifacts = FilesystemArtifactStore(project / "output")
        reports = RenderReportStore(project, schemas / "render-report-v1.schema.json")
        results = JsonVideoResultStore(
            root / "results",
            (
                schemas / "video-export-result-v1.schema.json",
                schemas / "video-export-result-v2.schema.json",
                schemas / "video-export-result-v3.schema.json",
                schemas / "video-export-result-v4.schema.json",
            ),
        )
        progress_store = JsonRenderProgressStore(
            root / "progress", schemas / "render-progress-v1.schema.json"
        )
        diagnostic_store = JsonRenderDiagnosticStore(
            state_base / "diagnostics" / identity_key[:24],
            schemas / "render-diagnostic-v1.schema.json",
            fallback_root=state_base / "diagnostics-fallback" / identity_key[:24],
        )
        verifier = FFmpegArtifactVerifier(prober, tools, runner)
        renderer = StaticVideoExportRenderer(tools, runner)
        handler = VideoExportJobHandler(
            source_root=project,
            repository=repository,
            artifacts=artifacts,
            renderer=renderer,
            verifier=verifier,
            report_store=reports,
            result_store=results,
            progress_store=progress_store,
            diagnostic_store=diagnostic_store,
        )
        worker = RenderWorker(
            repository,
            prober,
            SyntheticMediaEncoder(tools, runner),
            verifier,
            artifacts,
            project,
            admission=ProcessLocalRenderAdmission(),
            request_handlers=(handler,),
        )
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
        target = ExportTarget(
            args.target, args.track_id if args.target == "track" else None
        )
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
            request = resolve_player_export_request(
                loaded.manifest,
                target,
                select_resolved_player(loaded.resolved_player, selected_ids),
            )
        elif isinstance(loaded.manifest, RefinedVideoManifest):
            if args.profile != REFINED_PROFILE_ID:
                raise MediaInfrastructureError(
                    "PROFILE_MISMATCH", "The request profile does not match the manifest profile."
                )
            request = resolve_refined_export_request(loaded.manifest, target)
        elif isinstance(loaded.manifest, MotionVideoManifest):
            if args.profile != MOTION_PROFILE_ID:
                raise MediaInfrastructureError(
                    "PROFILE_MISMATCH", "The request profile does not match the manifest profile."
                )
            request = resolve_motion_export_request(loaded.manifest, target)
        else:
            request = VideoExportRequest(target, args.profile)
        exports = VideoExports(
            loader,
            MediaJobs(repository),
            path_validator=VideoExportPathPreflight(
                artifacts,
                tuple(tools.resolve(name).path for name in ("ffmpeg", "ffprobe")),
            ),
            tool_identity=tool_identity,
        )
        submitted = _submit_after_reconciliation(worker, exports, project, request)
        if submitted.status.status.value == "completed":
            result = reports.matching_result(submitted.snapshot.request_digest)
        else:
            result = _run_worker(
                worker,
                submitted.snapshot.job_id,
                submitted.snapshot.attempt_id,
                progress_store=progress_store,
            )
            if result[1].status.value != "completed":
                print(json.dumps(result[1].to_dict(), ensure_ascii=False), file=sys.stdout)
                return 1
            result = results.load(submitted.snapshot.job_id, submitted.snapshot.attempt_id)
        if result is None:
            raise MediaInfrastructureError("RESULT_MISSING", "Completed export result is unavailable.")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True), file=sys.stdout)
        media = next(item for item in result["artifacts"] if item["kind"].endswith("video"))
        print(f"Verified {media['path']} ({media['byte_size']} bytes)", file=sys.stderr)
        return 0
    except MediaInfrastructureError as error:
        return _error(error.code, error.message, error.details)
    except OSError:
        return _error("STORAGE_ERROR", "A required local file or directory was not accessible.")
    except KeyboardInterrupt:
        return _error("PROCESS_CANCELLED", "Video export was cancelled.")


def _submit_after_reconciliation(
    worker: RenderWorker,
    exports: VideoExports,
    project: Path,
    request: Any,
) -> Any:
    # Reconcile crash-interrupted attempts before digest deduplication decides
    # whether this identical request needs a new retry attempt.
    worker.reconcile()
    return exports.submit(project, request)


def _run_worker(
    worker: RenderWorker,
    job_id: str,
    attempt_id: str,
    *,
    progress_store: JsonRenderProgressStore | None = None,
) -> tuple[Any, Any]:
    box: list[Any] = []
    errors: list[BaseException] = []

    def target() -> None:
        try:
            box.append(worker.run_next(job_id, attempt_id))
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=target, name="wrld-video-export-worker")
    thread.start()
    last_display: tuple[Any, ...] | None = None
    last_display_at = 0.0
    progress_warning_shown = False
    try:
        while thread.is_alive():
            thread.join(timeout=0.2)
            if progress_store is not None:
                try:
                    progress = progress_store.load(job_id, attempt_id)
                    if progress is not None:
                        display = (
                            progress.phase,
                            progress.phase_progress_percent,
                            progress.current_track,
                            progress.processed_duration_seconds,
                            progress.failure_phase,
                            progress.diagnostic_reference,
                        )
                        now = time.monotonic()
                        phase_changed = last_display is None or display[0] != last_display[0]
                        if display != last_display and (phase_changed or now - last_display_at >= 0.5):
                            print(_format_progress(progress), file=sys.stderr, flush=True)
                            last_display = display
                            last_display_at = now
                except MediaInfrastructureError as error:
                    if not progress_warning_shown:
                        print(f"Progress unavailable: {error.code}", file=sys.stderr, flush=True)
                        progress_warning_shown = True
    except KeyboardInterrupt:
        worker.request_cancel(job_id, attempt_id)
        thread.join()
        raise
    if progress_store is not None:
        try:
            progress = progress_store.load(job_id, attempt_id)
            if progress is not None:
                display = (
                    progress.phase,
                    progress.phase_progress_percent,
                    progress.current_track,
                    progress.processed_duration_seconds,
                    progress.failure_phase,
                    progress.diagnostic_reference,
                )
                if display != last_display:
                    print(_format_progress(progress), file=sys.stderr, flush=True)
        except MediaInfrastructureError:
            pass
    if errors:
        raise errors[0]
    if not box:
        raise MediaInfrastructureError("WORKER_FAILED", "The render worker did not execute the job.")
    if box[0] is None:
        recovered = worker.repository.get_attempt(job_id, attempt_id)
        if recovered[1].status.value in {"completed", "failed", "cancelled"}:
            print(f"Render outcome: {recovered[1].status.value}", file=sys.stderr, flush=True)
            return recovered
        raise MediaInfrastructureError("WORKER_FAILED", "The render worker did not execute the job.")
    outcome = box[0]
    if (
        outcome[0].job_id != job_id
        or outcome[0].attempt_id != attempt_id
        or outcome[1].job_id != job_id
        or outcome[1].attempt_id != attempt_id
    ):
        raise MediaInfrastructureError(
            "WORKER_FAILED", "The render worker returned a different job attempt."
        )
    print(f"Render outcome: {outcome[1].status.value}", file=sys.stderr, flush=True)
    return outcome


def _format_progress(progress: Any) -> str:
    fields = [f"phase={progress.phase.value}"]
    if progress.phase_progress_percent is not None:
        fields.append(f"phase_percent={progress.phase_progress_percent:.3f}")
    if progress.current_track is not None and progress.total_tracks is not None:
        fields.append(f"track={progress.current_track}/{progress.total_tracks}")
    if progress.processed_duration_seconds is not None:
        if progress.total_duration_seconds is None:
            fields.append(f"processed_seconds={progress.processed_duration_seconds:.3f}")
        else:
            fields.append(
                "duration_seconds="
                f"{progress.processed_duration_seconds:.3f}/{progress.total_duration_seconds:.3f}"
            )
    fields.append(f"elapsed_seconds={progress.elapsed_seconds:.1f}")
    if progress.eta_seconds is not None:
        fields.append(f"eta_seconds={progress.eta_seconds:.1f}")
    if progress.failure_phase is not None:
        fields.append(f"failure_phase={progress.failure_phase.value}")
    if progress.diagnostic_reference is not None:
        fields.append(f"diagnostic={progress.diagnostic_reference}")
    return "Render progress: " + " ".join(fields)


def default_state_root() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "WRLD Video Studio" / "state" / "video-export"
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "wrld-video-studio" / "video-export"


def project_identity(project: Path) -> str:
    canonical = str(project.resolve())
    if os.name == "nt":
        canonical = canonical.casefold()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _tool_identity(tools: MediaToolchain) -> dict[str, Any]:
    identity: dict[str, Any] = {}
    for name in ("ffmpeg", "ffprobe"):
        tool = tools.resolve(name)
        digest = hashlib.sha256()
        try:
            with tool.path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as error:
            raise MediaInfrastructureError(
                "MEDIA_TOOL_MISSING", f"Configured {name} executable is not readable."
            ) from error
        identity[name] = {"version": tool.version, "sha256": digest.hexdigest()}
    return identity


def _schema_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "contracts" / "schemas"
        if candidate.is_dir():
            return candidate
    raise MediaInfrastructureError("SCHEMA_INVALID", "Repository contract schemas were not found.")


def _error(code: str, message: str, details: Any = None) -> int:
    payload: dict[str, Any] = {"code": code, "message": message}
    if details:
        payload["details"] = details
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    from wrld_video_studio.interfaces.cli.motion_preview import add_motion_preview_parser

    parser = argparse.ArgumentParser(prog="python -m wrld_video_studio")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    add_video_export_parser(subparsers)
    add_motion_preview_parser(subparsers)
    args = parser.parse_args(argv)
    return int(args.command(args))
