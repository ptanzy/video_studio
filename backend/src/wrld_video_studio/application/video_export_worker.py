from __future__ import annotations

import hashlib
import logging
import shutil
import time
from pathlib import Path
from typing import Any, Mapping

from wrld_video_studio.domain.jobs import JobState, JobStatus, MediaProbe, RenderSnapshot, utc_timestamp
from wrld_video_studio.domain.media_errors import IndeterminateMediaCommitError, MediaInfrastructureError
from wrld_video_studio.domain.render_progress import RenderPhase, RenderProgress
from wrld_video_studio.domain.video_export import (
    SAMPLE_RATE,
    VideoExportPlan,
    chapters_text,
    create_plan,
    parse_export_request,
    parse_manifest,
)
from wrld_video_studio.domain.video_export_v2 import (
    MOTION_EXPORT_REQUEST_VERSION,
    MOTION_EXPORT_RESULT_VERSION,
    MotionVideoExportPlan,
    create_motion_plan,
    parse_motion_export_request,
    parse_motion_manifest,
)
from wrld_video_studio.domain.video_export_v3 import (
    REFINED_EXPORT_REQUEST_VERSION,
    REFINED_EXPORT_RESULT_VERSION,
    RefinedVideoExportPlan,
    create_refined_plan,
    parse_refined_export_request,
    parse_refined_manifest,
)


from wrld_video_studio.domain.video_export_v4 import (
    PLAYER_EXPORT_REQUEST_VERSION,
    PLAYER_EXPORT_RESULT_VERSION,
    PlayerVideoExportPlan,
    create_player_plan,
    parse_player_export_request,
    parse_player_manifest,
)


LOGGER = logging.getLogger(__name__)


ResolvedVideoExportPlan = VideoExportPlan | MotionVideoExportPlan | RefinedVideoExportPlan | PlayerVideoExportPlan


class VideoExportJobHandler:
    def __init__(
        self,
        *,
        source_root: Path,
        repository: Any,
        artifacts: Any,
        renderer: Any,
        verifier: Any,
        report_store: Any,
        result_store: Any,
        progress_store: Any = None,
        diagnostic_store: Any = None,
        decode_min_seconds: float = 600.0,
        decode_duration_factor: float = 4.0,
    ) -> None:
        self.source_root = source_root.resolve()
        self.repository = repository
        self.artifacts = artifacts
        self.renderer = renderer
        self.verifier = verifier
        self.report_store = report_store
        self.result_store = result_store
        self.progress_store = progress_store
        self.diagnostic_store = diagnostic_store
        self.decode_min_seconds = decode_min_seconds
        self.decode_duration_factor = decode_duration_factor

    def supports(self, snapshot: RenderSnapshot) -> bool:
        return snapshot.request.get("kind") == "video-export"

    def execute(
        self,
        worker: Any,
        snapshot: RenderSnapshot,
        status: JobStatus,
        token: Any,
        started: float,
    ) -> tuple[RenderSnapshot, JobStatus]:
        phase = RenderPhase.PREPARING
        command: tuple[str, ...] = ()
        stderr_tail = ""
        try:
            self._progress(snapshot, started, phase)
            plan = self._plan(snapshot)
            total_tracks = len(plan.selected_tracks)
            worker._verify_fingerprints(snapshot)
            existing = self.report_store.matching_result(snapshot.request_digest)
            if existing is not None:
                self._verify_result(
                    snapshot,
                    existing,
                    require_receipts=False,
                    cancel_event=token,
                    heartbeat=lambda: worker._heartbeat(snapshot),
                    phase_callback=lambda value: self._progress(
                        snapshot, started, RenderPhase(value), total_tracks=total_tracks
                    ),
                )
                validating = worker._transition_current(snapshot, JobState.VALIDATING)
                self._progress(
                    snapshot, started, RenderPhase.COMPLETED,
                    phase_progress_percent=100.0, total_tracks=total_tracks,
                )
                completed = worker._transition_current(
                    snapshot, JobState.COMPLETED, progress_percent=100
                )
                worker._emit(snapshot, "render", "matching_verified_artifact_reused", started)
                return snapshot, completed
            self._reject_unowned_collisions(plan)
            self.result_store.save_report_base_revision(
                snapshot.job_id,
                snapshot.attempt_id,
                self.report_store.current_revision(),
            )
            staged = self.artifacts.stage_path(
                snapshot.job_id, snapshot.attempt_id, plan.output_relative_path
            )
            pcm_paths = tuple(
                self.artifacts.stage_path(
                    snapshot.job_id, snapshot.attempt_id, f"work/{index:02d}.pcm"
                )
                for index, _track in enumerate(plan.selected_tracks, start=1)
            )
            combined = self.artifacts.stage_path(
                snapshot.job_id, snapshot.attempt_id, "work/combined.pcm"
            )
            effect_control = None
            if isinstance(plan, (MotionVideoExportPlan, RefinedVideoExportPlan, PlayerVideoExportPlan)) and (
                plan.request.effects.audio_bars.enabled
                or plan.request.effects.track_progress.enabled
            ):
                effect_control = self.artifacts.stage_path(
                    snapshot.job_id, snapshot.attempt_id, "work/effects.sendcmd"
                )
            background_copy = self.artifacts.stage_path(
                snapshot.job_id,
                snapshot.attempt_id,
                f"work/source-background{Path(plan.manifest.background).suffix}",
            )
            audio_copies = tuple(
                self.artifacts.stage_path(
                    snapshot.job_id,
                    snapshot.attempt_id,
                    f"work/source-{index:02d}.wav",
                )
                for index, _track in enumerate(plan.selected_tracks, start=1)
            )
            font_copy = None
            if isinstance(plan, PlayerVideoExportPlan):
                assert plan.manifest.effects.player is not None
                font_copy = self.artifacts.stage_path(
                    snapshot.job_id,
                    snapshot.attempt_id,
                    f"work/source-font{Path(plan.manifest.effects.player.font.path).suffix}",
                )
            phase = RenderPhase.SNAPSHOTTING_SOURCES
            self._progress(snapshot, started, phase, total_tracks=total_tracks)
            self._copy_source(plan.manifest.background, background_copy, token)
            if font_copy is not None:
                assert isinstance(plan, PlayerVideoExportPlan)
                assert plan.manifest.effects.player is not None
                self._copy_source(plan.manifest.effects.player.font.path, font_copy, token)
            for track_index, (track, destination) in enumerate(
                zip(plan.selected_tracks, audio_copies, strict=True), start=1
            ):
                self._progress(
                    snapshot, started, phase,
                    current_track=track_index, total_tracks=total_tracks,
                )
                self._copy_source(track.audio, destination, token)
            worker._verify_fingerprints(snapshot)
            rendered = self.renderer.render(
                plan,
                audio_copies,
                background_copy,
                staged,
                pcm_paths,
                combined,
                snapshot.request_digest,
                token,
                heartbeat=lambda: self._heartbeat(worker, snapshot, started),
                progress=lambda value: self._renderer_progress(snapshot, started, value),
                effect_control_path=effect_control,
                font_path=font_copy,
            )
            command = rendered.command
            stderr_tail = rendered.stderr_tail
            if token.is_set():
                self.artifacts.cleanup_owned(snapshot.job_id, snapshot.attempt_id)
                return snapshot, worker._finish_cancelled(snapshot, started)
            worker._verify_fingerprints(snapshot)
            validating = worker._transition_current(snapshot, JobState.VALIDATING)
            if validating.status is JobState.CANCEL_REQUESTED:
                self.artifacts.cleanup_owned(snapshot.job_id, snapshot.attempt_id)
                return snapshot, worker._finish_cancelled(snapshot, started)
            expected = self._expected(snapshot, rendered.duration_seconds)
            probe = self.verifier.verify(
                staged,
                expected,
                cancel_event=token,
                heartbeat=lambda: self._heartbeat(worker, snapshot, started),
                phase_callback=lambda value: self._progress(
                    snapshot,
                    started,
                    RenderPhase(value),
                    total_tracks=total_tracks,
                    total_duration_seconds=rendered.duration_seconds,
                ),
            )
            artifacts = [self._media_artifact(plan, staged, probe)]
            chapter_stage: Path | None = None
            chapter_reused = False
            if plan.request.target.kind == "album":
                chapter_stage = self.artifacts.stage_path(
                    snapshot.job_id, snapshot.attempt_id, "metadata/chapters.txt"
                )
                chapter_stage.write_text(chapters_text(rendered.timeline), encoding="utf-8", newline="\n")
                chapter_artifact = self._file_artifact(
                    "chapters", chapter_stage, "output/metadata/chapters.txt"
                )
                artifacts.append(chapter_artifact)
                chapter_final = self.artifacts.resolve_final("metadata/chapters.txt")
                if chapter_final.exists():
                    matches = getattr(self.report_store, "has_artifact", None)
                    if matches is None or not matches(chapter_artifact):
                        raise MediaInfrastructureError(
                            "OUTPUT_EXISTS",
                            "An output exists without a matching verified render result.",
                        )
                    chapter_reused = True
            result = {
                "contract_version": (
                    PLAYER_EXPORT_RESULT_VERSION
                    if isinstance(plan, PlayerVideoExportPlan)
                    else REFINED_EXPORT_RESULT_VERSION
                    if isinstance(plan, RefinedVideoExportPlan)
                    else MOTION_EXPORT_RESULT_VERSION
                    if isinstance(plan, MotionVideoExportPlan)
                    else "video-export-result/1.0"
                ),
                "job_id": snapshot.job_id,
                "attempt_id": snapshot.attempt_id,
                "state": "completed",
                "target": plan.request.target.to_dict(),
                "request_digest": snapshot.request_digest,
                "artifacts": artifacts,
                "warnings": self._warnings(rendered.timeline),
                "started_at": snapshot.created_at,
                "finished_at": utc_timestamp(worker.clock.now()),
            }
            if isinstance(plan, (MotionVideoExportPlan, RefinedVideoExportPlan, PlayerVideoExportPlan)):
                result["profile_id"] = plan.request.profile_id
                result["effects"] = plan.request.effects.to_dict()
            if isinstance(plan, PlayerVideoExportPlan):
                result["resolved_player"] = plan.request.resolved_player.to_dict()
            if plan.request.target.kind == "album":
                result["timeline"] = [item.to_dict() for item in rendered.timeline]
            self.result_store.save(snapshot.job_id, snapshot.attempt_id, result)
            if token.is_set():
                self.artifacts.cleanup_owned(snapshot.job_id, snapshot.attempt_id)
                return snapshot, worker._finish_cancelled(snapshot, started)
            promoted_any = False
            phase = RenderPhase.PUBLISHING_ARTIFACTS
            self._progress(
                snapshot, started, phase,
                total_tracks=total_tracks,
                total_duration_seconds=rendered.duration_seconds,
            )
            with worker._control_lock, self.repository.publication_lock(
                snapshot.job_id, snapshot.attempt_id
            ):
                current = worker._current_status(snapshot)
                if token.is_set() or current.status is JobState.CANCEL_REQUESTED:
                    self.artifacts.cleanup_owned(snapshot.job_id, snapshot.attempt_id)
                    return snapshot, worker._finish_cancelled(snapshot, started)
                try:
                    self.artifacts.promote(staged, plan.output_relative_path)
                    promoted_any = True
                    if chapter_stage is not None and not chapter_reused:
                        self.artifacts.promote(chapter_stage, "metadata/chapters.txt")
                    phase = RenderPhase.PUBLISHING_REPORT
                    self._progress(
                        snapshot, started, phase,
                        total_tracks=total_tracks,
                        total_duration_seconds=rendered.duration_seconds,
                    )
                    self._publish_report(plan, snapshot, result)
                    self.artifacts.cleanup_owned(snapshot.job_id, snapshot.attempt_id)
                    self._progress(
                        snapshot, started, RenderPhase.COMPLETED,
                        phase_progress_percent=100.0,
                        total_tracks=total_tracks,
                        processed_duration_seconds=rendered.duration_seconds,
                        total_duration_seconds=rendered.duration_seconds,
                    )
                    completed = worker._transition_current(
                        snapshot, JobState.COMPLETED, progress_percent=100
                    )
                except Exception as error:
                    if not promoted_any:
                        raise
                    raise IndeterminateMediaCommitError(
                        "Video artifacts were promoted but publication was interrupted.",
                        {"job_id": snapshot.job_id, "attempt_id": snapshot.attempt_id},
                    ) from error
            worker._emit(snapshot, "worker", "completed", started)
            return snapshot, completed
        except IndeterminateMediaCommitError:
            raise
        except MediaInfrastructureError as error:
            phase = self._current_phase(snapshot, phase)
            current = worker._current_status(snapshot)
            if current.status is JobState.CANCEL_REQUESTED and error.code == "PROCESS_CANCELLED":
                self._cleanup_and_diagnose(
                    worker, snapshot, started, phase, error, command, stderr_tail
                )
                return snapshot, worker._finish_cancelled(snapshot, started)
            if current.status in {JobState.RUNNING, JobState.VALIDATING, JobState.CANCEL_REQUESTED}:
                failed = current.transition(
                    JobState.FAILED,
                    worker.clock.now(),
                    error=error.to_dict(),
                    commit_state=error.commit_state,
                )
                saved = self.repository.update_status(failed, current.revision)
            else:
                saved = current
            self._cleanup_and_diagnose(
                worker, snapshot, started, phase, error, command, stderr_tail
            )
            worker._emit(snapshot, "worker", "failed", started, error.to_dict())
            return snapshot, saved

    def reconcile(
        self, worker: Any, snapshot: RenderSnapshot, status: JobStatus
    ) -> tuple[RenderSnapshot, JobStatus] | None:
        started = time.monotonic()
        phase = RenderPhase.PREPARING
        candidate = self.result_store.load(snapshot.job_id, snapshot.attempt_id)
        try:
            if candidate is None:
                raise MediaInfrastructureError(
                    "RECOVERABLE_INTERRUPTION", "No verified export candidate was persisted."
                )
            self._verify_result(
                snapshot,
                candidate,
                require_receipts=status.status is JobState.CANCEL_REQUESTED,
                phase_callback=lambda value: self._progress(
                    snapshot, started, RenderPhase(value)
                ),
            )
            plan = self._plan(snapshot)
            total_tracks = len(plan.selected_tracks)
            media = next(
                item for item in candidate["artifacts"]
                if item["kind"] in {"album_video", "track_video"}
            )
            duration = float(media["media"]["duration_seconds"])
            phase = RenderPhase.PUBLISHING_REPORT
            self._progress(
                snapshot,
                started,
                phase,
                total_tracks=total_tracks,
                total_duration_seconds=duration,
            )
            self._publish_report(plan, snapshot, candidate)
            if status.status is JobState.RUNNING:
                status = self.repository.update_status(
                    status.transition(JobState.VALIDATING, worker.clock.now()), status.revision
                )
            self.artifacts.cleanup_owned(snapshot.job_id, snapshot.attempt_id)
            self._progress(
                snapshot,
                started,
                RenderPhase.COMPLETED,
                phase_progress_percent=100.0,
                total_tracks=total_tracks,
                processed_duration_seconds=duration,
                total_duration_seconds=duration,
            )
            updated = status.transition(JobState.COMPLETED, worker.clock.now(), progress_percent=100)
            saved = self.repository.update_status(updated, status.revision)
            return snapshot, saved
        except MediaInfrastructureError as error:
            phase = self._current_phase(snapshot, phase)
            next_state = JobState.CANCELLED if status.status is JobState.CANCEL_REQUESTED else JobState.FAILED
            updated = status.transition(
                next_state,
                worker.clock.now(),
                error={"code": "RECOVERABLE_INTERRUPTION", "message": error.code},
            )
            saved = self.repository.update_status(updated, status.revision)
            self._cleanup_and_diagnose(
                worker, snapshot, started, phase, error, (), ""
            )
            return snapshot, saved

    def _plan(self, snapshot: RenderSnapshot) -> ResolvedVideoExportPlan:
        try:
            request_document = snapshot.request["export_request"]
            if request_document.get("contract_version") == PLAYER_EXPORT_REQUEST_VERSION:
                manifest = parse_player_manifest(snapshot.request["manifest"])
                request = parse_player_export_request(request_document)
                plan = create_player_plan(manifest, request)
            elif request_document.get("contract_version") == REFINED_EXPORT_REQUEST_VERSION:
                manifest = parse_refined_manifest(snapshot.request["manifest"])
                request = parse_refined_export_request(request_document)
                plan = create_refined_plan(manifest, request)
            elif request_document.get("contract_version") == MOTION_EXPORT_REQUEST_VERSION:
                manifest = parse_motion_manifest(snapshot.request["manifest"])
                request = parse_motion_export_request(request_document)
                plan = create_motion_plan(manifest, request)
            else:
                manifest = parse_manifest(snapshot.request["manifest"])
                request = parse_export_request(request_document)
                plan = create_plan(manifest, request)
        except (KeyError, TypeError) as error:
            raise MediaInfrastructureError(
                "INVALID_RENDER_PLAN", "The frozen video export plan is invalid."
            ) from error
        if (
            snapshot.request.get("output_relative_path") != plan.output_relative_path
            or snapshot.request.get("artifact_kind") != plan.artifact_kind
        ):
            raise MediaInfrastructureError(
                "INVALID_RENDER_PLAN", "Frozen output identity does not match the manifest."
            )
        return plan

    def _reject_unowned_collisions(
        self, plan: ResolvedVideoExportPlan
    ) -> None:
        targets = [self.artifacts.resolve_final(plan.output_relative_path)]
        if any(path.exists() for path in targets):
            raise MediaInfrastructureError(
                "OUTPUT_EXISTS", "An output exists without a matching verified render result."
            )

    def _copy_source(self, relative: str, destination: Path, token: Any) -> None:
        if token.is_set():
            raise MediaInfrastructureError("PROCESS_CANCELLED", "Export was cancelled.")
        source = self.source_root / Path(*relative.split("/"))
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as input_stream, destination.open("wb") as output_stream:
                while True:
                    if token.is_set():
                        raise MediaInfrastructureError("PROCESS_CANCELLED", "Export was cancelled.")
                    chunk = input_stream.read(1024 * 1024)
                    if not chunk:
                        break
                    output_stream.write(chunk)
        except MediaInfrastructureError:
            raise
        except OSError as error:
            raise MediaInfrastructureError(
                "STORAGE_ERROR", "Could not snapshot a render source into attempt staging."
            ) from error

    def _publish_report(
        self,
        plan: ResolvedVideoExportPlan,
        snapshot: RenderSnapshot,
        result: Mapping[str, Any],
    ) -> None:
        self.report_store.publish(
            plan.manifest.album.id,
            result,
            renderer_version=snapshot.renderer_version,
            input_fingerprints=[item.to_dict() for item in snapshot.inputs],
            toolchain=snapshot.request.get("toolchain", {}),
            expected_revision=self.result_store.load_report_base_revision(
                snapshot.job_id, snapshot.attempt_id
            ),
        )

    def _verify_result(
        self,
        snapshot: RenderSnapshot,
        result: Mapping[str, Any],
        *,
        require_receipts: bool,
        cancel_event: Any = None,
        heartbeat: Any = None,
        phase_callback: Any = None,
    ) -> None:
        plan = self._plan(snapshot)
        if (
            result.get("job_id") != snapshot.job_id
            or result.get("attempt_id") != snapshot.attempt_id
            or result.get("request_digest") != snapshot.request_digest
            or result.get("target") != plan.request.target.to_dict()
        ):
            raise MediaInfrastructureError(
                "OUTPUT_PROVENANCE_MISMATCH", "Export result does not belong to this attempt."
            )
        if isinstance(plan, (MotionVideoExportPlan, RefinedVideoExportPlan, PlayerVideoExportPlan)) and (
            result.get("contract_version")
            != (
                PLAYER_EXPORT_RESULT_VERSION
                if isinstance(plan, PlayerVideoExportPlan)
                else REFINED_EXPORT_RESULT_VERSION
                if isinstance(plan, RefinedVideoExportPlan)
                else MOTION_EXPORT_RESULT_VERSION
            )
            or result.get("profile_id") != plan.request.profile_id
            or result.get("effects") != plan.request.effects.to_dict()
        ):
            raise MediaInfrastructureError(
                "OUTPUT_PROVENANCE_MISMATCH",
                "Motion export result does not match its resolved profile and effects.",
            )
        if isinstance(plan, PlayerVideoExportPlan) and result.get(
            "resolved_player"
        ) != plan.request.resolved_player.to_dict():
            raise MediaInfrastructureError(
                "OUTPUT_PROVENANCE_MISMATCH",
                "Player export result does not match its resolved configuration.",
            )
        media = next(
            (item for item in result.get("artifacts", []) if item.get("kind") in {"album_video", "track_video"}),
            None,
        )
        if not isinstance(media, dict) or not isinstance(media.get("media"), dict):
            raise MediaInfrastructureError("OUTPUT_INVALID", "Result lacks a video artifact.")
        relative = str(media["path"])
        if (
            relative != f"output/{plan.output_relative_path}"
            or media.get("kind") != plan.artifact_kind
        ):
            raise MediaInfrastructureError("OUTPUT_INVALID", "Result path is invalid.")
        final = self.artifacts.resolve_final(relative.removeprefix("output/"))
        duration = float(media["media"]["duration_seconds"])
        self.verifier.verify(
            final,
            self._expected(snapshot, duration),
            cancel_event=cancel_event,
            heartbeat=heartbeat,
            phase_callback=phase_callback,
        )
        if self._sha256(final) != media["sha256"]:
            raise MediaInfrastructureError("OUTPUT_INVALID", "Video artifact digest changed.")
        if require_receipts and not self.artifacts.has_promotion_record(
            snapshot.job_id, snapshot.attempt_id, final
        ):
            raise MediaInfrastructureError(
                "PROMOTION_ORDER_UNKNOWN", "Promotion receipt is missing after cancellation."
            )
        for item in result.get("artifacts", []):
            if item.get("kind") != "chapters":
                continue
            chapter = self.artifacts.resolve_final(str(item["path"]).removeprefix("output/"))
            if not chapter.is_file() or self._sha256(chapter) != item["sha256"]:
                raise MediaInfrastructureError("OUTPUT_INVALID", "Chapter artifact changed.")
            if require_receipts and not self.artifacts.has_promotion_record(
                snapshot.job_id, snapshot.attempt_id, chapter
            ):
                raise MediaInfrastructureError(
                    "PROMOTION_ORDER_UNKNOWN", "Chapter promotion receipt is missing."
                )
        chapter_count = sum(
            1 for item in result.get("artifacts", []) if item.get("kind") == "chapters"
        )
        if chapter_count != (1 if plan.request.target.kind == "album" else 0):
            raise MediaInfrastructureError("OUTPUT_INVALID", "Chapter artifact set is invalid.")

    def _expected(self, snapshot: RenderSnapshot, duration: float) -> dict[str, Any]:
        return {
            "video_codec": "h264",
            "audio_codec": "aac",
            "pixel_format": "yuv420p",
            "width": 1920,
            "height": 1080,
            "frame_rate": 30,
            "audio_sample_rate": SAMPLE_RATE,
            "audio_channels": 2,
            "video_profile": "High",
            "audio_profile": "LC",
            "color_space": "bt709",
            "color_transfer": "bt709",
            "color_primaries": "bt709",
            "duration_seconds": duration,
            "duration_tolerance_seconds": 0.25,
            "request_digest": snapshot.request_digest,
            "faststart": True,
            "full_decode": True,
            "decode_timeout_seconds": max(
                self.decode_min_seconds, duration * self.decode_duration_factor
            ),
        }

    def _media_artifact(
        self,
        plan: ResolvedVideoExportPlan,
        path: Path,
        probe: MediaProbe,
    ) -> dict[str, Any]:
        video = next(stream for stream in probe.streams if stream.codec_type == "video")
        audio = next(stream for stream in probe.streams if stream.codec_type == "audio")
        return {
            "kind": plan.artifact_kind,
            "path": f"output/{plan.output_relative_path}",
            "sha256": self._sha256(path),
            "byte_size": path.stat().st_size,
            "verification": "verified",
            "media": {
                "duration_seconds": probe.duration_seconds,
                "video_codec": video.codec_name,
                "audio_codec": audio.codec_name,
                "width": video.width,
                "height": video.height,
                "frame_rate": video.frame_rate,
                "pixel_format": video.pixel_format,
                "audio_sample_rate": audio.sample_rate,
                "audio_channels": audio.channels,
            },
        }

    def _file_artifact(self, kind: str, path: Path, relative: str) -> dict[str, Any]:
        return {
            "kind": kind,
            "path": relative,
            "sha256": self._sha256(path),
            "byte_size": path.stat().st_size,
            "verification": "verified",
        }

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _warnings(timeline: tuple[Any, ...]) -> list[str]:
        if len(timeline) < 3:
            return ["Timeline has fewer than three YouTube chapter entries."]
        if any(item.sample_count < 10 * SAMPLE_RATE for item in timeline):
            return ["One or more chapters are shorter than ten seconds."]
        return []

    def _renderer_progress(
        self, snapshot: RenderSnapshot, started: float, value: Mapping[str, Any]
    ) -> None:
        self._progress(
            snapshot,
            started,
            RenderPhase(str(value["phase"])),
            phase_progress_percent=value.get("phase_progress_percent"),
            current_track=value.get("current_track"),
            total_tracks=value.get("total_tracks"),
            processed_duration_seconds=value.get("processed_duration_seconds"),
            total_duration_seconds=value.get("total_duration_seconds"),
        )

    def _heartbeat(
        self, worker: Any, snapshot: RenderSnapshot, started: float
    ) -> None:
        worker._heartbeat(snapshot)
        if self.progress_store is None:
            return
        current = self.progress_store.load(snapshot.job_id, snapshot.attempt_id)
        if current is None:
            return
        now = utc_timestamp(worker.clock.now())
        self.progress_store.save(
            current.updated(elapsed_seconds=max(0.0, time.monotonic() - started), last_heartbeat_at=now)
        )

    def _progress(
        self,
        snapshot: RenderSnapshot,
        started: float,
        phase: RenderPhase,
        *,
        phase_progress_percent: float | None = None,
        current_track: int | None = None,
        total_tracks: int | None = None,
        processed_duration_seconds: float | None = None,
        total_duration_seconds: float | None = None,
        failure_phase: RenderPhase | None = None,
        diagnostic_reference: str | None = None,
    ) -> None:
        if self.progress_store is None:
            return
        timestamp = utc_timestamp()
        self.progress_store.save(
            RenderProgress(
                job_id=snapshot.job_id,
                attempt_id=snapshot.attempt_id,
                phase=phase,
                phase_progress_percent=phase_progress_percent,
                current_track=current_track,
                total_tracks=total_tracks,
                processed_duration_seconds=processed_duration_seconds,
                total_duration_seconds=total_duration_seconds,
                elapsed_seconds=max(0.0, time.monotonic() - started),
                eta_seconds=None,
                last_progress_at=timestamp,
                failure_phase=failure_phase,
                diagnostic_reference=diagnostic_reference,
            )
        )

    def _current_phase(self, snapshot: RenderSnapshot, fallback: RenderPhase) -> RenderPhase:
        if self.progress_store is None:
            return fallback
        try:
            current = self.progress_store.load(snapshot.job_id, snapshot.attempt_id)
        except MediaInfrastructureError:
            return fallback
        return fallback if current is None else current.phase

    def _cleanup_and_diagnose(
        self,
        worker: Any,
        snapshot: RenderSnapshot,
        started: float,
        phase: RenderPhase,
        error: MediaInfrastructureError,
        command: tuple[str, ...],
        stderr_tail: str,
    ) -> None:
        cleanup_started_at = utc_timestamp(worker.clock.now())
        cleanup = {
            "outcome": "succeeded",
            "error_code": None,
            "started_at": cleanup_started_at,
            "finished_at": cleanup_started_at,
        }
        try:
            self.artifacts.cleanup_owned(snapshot.job_id, snapshot.attempt_id)
        except Exception as cleanup_error:
            cleanup = {
                "outcome": "failed",
                "error_code": (
                    cleanup_error.code
                    if isinstance(cleanup_error, MediaInfrastructureError)
                    else "STORAGE_ERROR"
                ),
                "started_at": cleanup_started_at,
                "finished_at": utc_timestamp(worker.clock.now()),
            }
        else:
            cleanup["finished_at"] = utc_timestamp(worker.clock.now())
        details = error.details
        diagnostic_reference: str | None = None
        if self.diagnostic_store is not None:
            diagnostic = {
                "contract_version": "wrld-render-diagnostic/1.0",
                "job_id": snapshot.job_id,
                "attempt_id": snapshot.attempt_id,
                "request_digest": snapshot.request_digest,
                "failure_phase": phase.value,
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "predicate": details.get("predicate"),
                    "expected": details.get("expected"),
                    "actual": details.get("actual"),
                },
                "ffmpeg_command": list(command or tuple(details.get("command", ()))),
                "ffmpeg_stderr_tail": str(
                    stderr_tail or details.get("stderr_tail", "")
                )[:16384],
                "toolchain": dict(snapshot.request.get("toolchain", {})),
                "probe": details.get("probe"),
                "cleanup": cleanup,
                "failed_at": utc_timestamp(worker.clock.now()),
            }
            try:
                diagnostic_reference = self.diagnostic_store.save(diagnostic)
            except Exception as diagnostic_error:
                LOGGER.warning(
                    "Video-export diagnostic persistence failed (attempt=%s, error=%s).",
                    snapshot.attempt_id,
                    type(diagnostic_error).__name__,
                )
                diagnostic_reference = None
        try:
            self._progress(
                snapshot,
                started,
                phase,
                failure_phase=phase,
                diagnostic_reference=diagnostic_reference,
            )
        except Exception:
            pass
