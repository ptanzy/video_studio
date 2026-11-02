from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import stat
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

import portalocker

from wrld_video_studio.application.ports.media import ArtifactVerifier
from wrld_video_studio.application.ports.motion_preview import MotionPreviewRenderer
from wrld_video_studio.application.ports.render_coordination import RenderAdmissionCoordinator
from wrld_video_studio.application.ports.render_coordination import RenderAdmissionCancelled
from wrld_video_studio.application.ports.video_export import VideoProjectLoader
from wrld_video_studio.domain.canonical_json import canonical_sha256
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.motion_preview import (
    MotionPreviewPlan,
    MotionPreviewRequest,
    create_motion_preview_plan,
    parse_motion_preview_request,
)
from wrld_video_studio.domain.motion_preview_v2 import (
    RefinedMotionPreviewPlan,
    RefinedMotionPreviewRequest,
    create_refined_motion_preview_plan,
    parse_refined_motion_preview_request,
)
from wrld_video_studio.domain.motion_preview_v3 import (
    PlayerMotionPreviewPlan,
    PlayerMotionPreviewRequest,
    create_player_motion_preview_plan,
    parse_player_motion_preview_request,
)
from wrld_video_studio.domain.render_progress import RenderPhase, RenderProgress
from wrld_video_studio.domain.video_export_v2 import MotionVideoManifest


from wrld_video_studio.domain.video_export_v3 import (
    REFINED_RENDERER_VERSION,
    RefinedVideoManifest,
)
from wrld_video_studio.domain.video_export_v4 import (
    PLAYER_PRESENTATION_VERSION,
    PLAYER_RENDERER_VERSION,
    PlayerVideoManifest,
)


LOGGER = logging.getLogger(__name__)


ResolvedMotionPreviewPlan = MotionPreviewPlan | RefinedMotionPreviewPlan | PlayerMotionPreviewPlan


@dataclass(frozen=True, slots=True)
class MotionPreviewResult:
    preview_id: str
    attempt_id: str
    request_digest: str
    byte_size: int
    duration_seconds: float
    start_sample: int
    sample_count: int
    width: int = 1920
    height: int = 1080
    frame_rate: float = 30.0
    video_codec: str = "h264"
    audio_codec: str = "aac"

    def to_dict(self) -> dict[str, Any]:
        return {
            "preview_id": self.preview_id,
            "attempt_id": self.attempt_id,
            "request_digest": self.request_digest,
            "byte_size": self.byte_size,
            "duration_seconds": self.duration_seconds,
            "excerpt": {
                "start_sample": self.start_sample,
                "sample_count": self.sample_count,
            },
            "media": {
                "width": self.width,
                "height": self.height,
                "frame_rate": self.frame_rate,
                "video_codec": self.video_codec,
                "audio_codec": self.audio_codec,
            },
        }


@dataclass(slots=True)
class _PreviewFlight:
    key: str
    project_root: Path
    plan: ResolvedMotionPreviewPlan
    attempt_id: str
    source_sample_counts: tuple[int, ...] | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    consumers: int = 0
    done: bool = False
    result: MotionPreviewResult | None = None
    artifact_path: Path | None = None
    directory: Path | None = None
    error: MediaInfrastructureError | None = None
    thread: threading.Thread | None = None
    owner_lock: Any = None


class MotionPreviewLease:
    def __init__(self, owner: MotionPreviews, flight: _PreviewFlight) -> None:
        self._owner = owner
        self._flight = flight
        self._stream: BinaryIO | None = None
        self._closed = False
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        with self._lock:
            if self._closed or self._flight.artifact_path is None:
                raise MediaInfrastructureError("PREVIEW_INTERNAL_ERROR", "The preview lease is closed.")
            return self._flight.artifact_path

    @property
    def result(self) -> MotionPreviewResult:
        with self._lock:
            if self._closed or self._flight.result is None:
                raise MediaInfrastructureError("PREVIEW_INTERNAL_ERROR", "The preview lease is closed.")
            return self._flight.result

    def read(self, amount: int = -1) -> bytes:
        with self._lock:
            if self._closed:
                raise MediaInfrastructureError("PREVIEW_INTERNAL_ERROR", "The preview lease is closed.")
            if self._stream is None:
                if self._flight.artifact_path is None:
                    raise MediaInfrastructureError(
                        "PREVIEW_INTERNAL_ERROR", "The preview artifact is unavailable."
                    )
                self._stream = self._flight.artifact_path.open("rb")
            return self._stream.read(amount)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            stream = self._stream
            self._stream = None
        if stream is not None:
            stream.close()
        try:
            self._owner._release(self._flight)
        except BaseException:
            with self._lock:
                self._closed = False
            raise

    def __enter__(self) -> MotionPreviewLease:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class MotionPreviews:
    """Private, lease-owned motion previews sharing the production renderer."""

    def __init__(
        self,
        loader: VideoProjectLoader,
        renderer: MotionPreviewRenderer,
        verifier: ArtifactVerifier,
        admission: RenderAdmissionCoordinator,
        preview_root: str | Path,
        *,
        tool_identity: dict[str, Any] | None = None,
        progress_store: Any = None,
        diagnostic_store: Any = None,
        progress_observer: Any = None,
        max_distinct_flights: int = 4,
        abandoned_after_seconds: float = 3600.0,
    ) -> None:
        if type(max_distinct_flights) is not int or not 1 <= max_distinct_flights <= 32:
            raise ValueError("max_distinct_flights must be between 1 and 32")
        self.loader = loader
        self.renderer = renderer
        self.verifier = verifier
        self.admission = admission
        self.root = Path(preview_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.tool_identity = dict(tool_identity or {})
        self.progress_store = progress_store
        self.diagnostic_store = diagnostic_store
        self.progress_observer = progress_observer
        self.max_distinct_flights = max_distinct_flights
        self.abandoned_after_seconds = abandoned_after_seconds
        self._condition = threading.Condition()
        self._flights: dict[str, _PreviewFlight] = {}
        self._accepting = True
        self._reconcile_abandoned()

    def prepare(
        self,
        album_project: str | Path,
        request: MotionPreviewRequest | RefinedMotionPreviewRequest | PlayerMotionPreviewRequest,
        cancel_event: Any = None,
    ) -> MotionPreviewLease:
        project = self.loader.load(album_project)
        if isinstance(project.manifest, PlayerVideoManifest):
            if not isinstance(request, PlayerMotionPreviewRequest):
                raise MediaInfrastructureError(
                    "PROFILE_MISMATCH", "The preview request does not match the player project."
                )
            request = parse_player_motion_preview_request(request.to_dict())
            plan = create_player_motion_preview_plan(project.manifest, request)
        elif isinstance(project.manifest, RefinedVideoManifest):
            if not isinstance(request, RefinedMotionPreviewRequest):
                raise MediaInfrastructureError(
                    "PROFILE_MISMATCH",
                    "The preview request does not match the refined motion project.",
                )
            request = parse_refined_motion_preview_request(request.to_dict())
            plan = create_refined_motion_preview_plan(project.manifest, request)
        elif isinstance(project.manifest, MotionVideoManifest):
            if not isinstance(request, MotionPreviewRequest):
                raise MediaInfrastructureError(
                    "PROFILE_MISMATCH", "The preview request does not match the motion project."
                )
            request = parse_motion_preview_request(request.to_dict())
            plan = create_motion_preview_plan(project.manifest, request)
        else:
            raise MediaInfrastructureError(
                "PROFILE_MISMATCH", "Motion previews require a supported motion project manifest."
            )
        project_counts = getattr(project, "normalized_sample_counts", None)
        selected_counts = self._selected_sample_counts(project.manifest, plan, project_counts)
        key = self._identity(project.root, plan, selected_counts)
        with self._condition:
            if not self._accepting:
                raise MediaInfrastructureError(
                    "PREVIEW_INTERNAL_ERROR", "Motion preview service is shutting down."
                )
            flight = self._flights.get(key)
            if flight is None:
                active_flights = sum(not item.done for item in self._flights.values())
                if active_flights >= self.max_distinct_flights:
                    raise MediaInfrastructureError(
                        "PREVIEW_CAPACITY_EXHAUSTED",
                        "The bounded motion-preview queue is full; retry after an active preview finishes.",
                        {"capacity": self.max_distinct_flights},
                    )
                flight = _PreviewFlight(
                    key,
                    project.root,
                    plan,
                    f"preview-{uuid.uuid4().hex}",
                    selected_counts,
                )
                self._flights[key] = flight
                flight.thread = threading.Thread(
                    target=self._run_flight,
                    args=(flight,),
                    name=f"wrld-motion-preview-{key[:8]}",
                    daemon=False,
                )
                flight.thread.start()
            flight.consumers += 1
        while True:
            with self._condition:
                if cancel_event is not None and cancel_event.is_set():
                    self._release_locked(flight)
                    raise MediaInfrastructureError("PREVIEW_CANCELLED", "Preview request was cancelled.")
                if flight.done:
                    if flight.error is not None:
                        error = flight.error
                        self._release_locked(flight)
                        raise MediaInfrastructureError(error.code, error.message, dict(error.details))
                    if flight.result is None or flight.artifact_path is None:
                        self._release_locked(flight)
                        raise MediaInfrastructureError(
                            "PREVIEW_INTERNAL_ERROR", "The verified preview is unavailable."
                        )
                    return MotionPreviewLease(self, flight)
                self._condition.wait(timeout=0.05)

    def close(self, *, timeout_seconds: float = 30.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            self._accepting = False
            flights = tuple(self._flights.values())
            for flight in flights:
                if not flight.done:
                    flight.cancel_event.set()
            self._condition.notify_all()
        for flight in flights:
            thread = flight.thread
            if thread is not None and thread.is_alive():
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if any(flight.thread is not None and flight.thread.is_alive() for flight in flights):
            raise MediaInfrastructureError(
                "PREVIEW_INTERNAL_ERROR", "Motion preview shutdown exceeded its bounded timeout."
            )
        cleanup_failed = False
        with self._condition:
            for flight in tuple(self._flights.values()):
                if flight.done and flight.consumers == 0:
                    try:
                        self._cleanup_flight_locked(flight)
                    except MediaInfrastructureError:
                        cleanup_failed = True
        if cleanup_failed:
            raise MediaInfrastructureError(
                "STORAGE_ERROR", "Motion preview shutdown could not remove private staging."
            )

    def _run_flight(self, flight: _PreviewFlight) -> None:
        rendered: Any = None
        phase = RenderPhase.PREPARING
        started = time.monotonic()
        try:
            with self.admission.acquire_preview(flight.cancel_event):
                directory = Path(tempfile.mkdtemp(prefix="motion-preview-", dir=self.root)).resolve()
                flight.directory = directory
                self._claim_directory(flight)
                phase = RenderPhase.SNAPSHOTTING_SOURCES
                background = directory / f"background{Path(flight.plan.manifest.background).suffix}"
                self._copy(flight.project_root / flight.plan.manifest.background, background, flight)
                audio_sources: list[Path] = []
                font_path = None
                if isinstance(flight.plan, PlayerMotionPreviewPlan):
                    assert flight.plan.manifest.effects.player is not None
                    source_font = flight.plan.manifest.effects.player.font.path
                    font_path = directory / f"font{Path(source_font).suffix}"
                    self._copy(flight.project_root / source_font, font_path, flight)
                for index, track in enumerate(flight.plan.selected_tracks, start=1):
                    source = flight.project_root / track.audio
                    if flight.source_sample_counts is None:
                        destination = directory / f"source-{index:03d}{Path(track.audio).suffix}"
                        self._copy(source, destination, flight)
                        source = destination
                    audio_sources.append(source)
                output = directory / "preview.mp4"
                pcm_paths = tuple(
                    directory / f"normalized-{index:03d}.pcm"
                    for index in range(1, len(audio_sources) + 1)
                )

                def progress(value: dict[str, Any]) -> None:
                    nonlocal phase
                    phase = RenderPhase(value["phase"])
                    self._save_progress(flight, started, phase, value)

                rendered = self.renderer.render(
                    flight.plan,
                    tuple(audio_sources),
                    background,
                    output,
                    pcm_paths,
                    directory / "combined.pcm",
                    flight.key,
                    cancel_event=flight.cancel_event,
                    progress=progress,
                    effect_control_path=directory / "effects.sendcmd",
                    font_path=font_path,
                    source_sample_counts=flight.source_sample_counts,
                )
                expected = self._expected(flight, rendered.duration_seconds)

                def verify_phase(value: str) -> None:
                    nonlocal phase
                    phase = RenderPhase(value)
                    self._save_progress(flight, started, phase, {})

                probe = self.verifier.verify(
                    output,
                    expected,
                    cancel_event=flight.cancel_event,
                    phase_callback=verify_phase,
                )
                if flight.cancel_event.is_set():
                    raise MediaInfrastructureError("PREVIEW_CANCELLED", "Preview request was cancelled.")
                phase = RenderPhase.COMPLETED
                self._save_progress(
                    flight,
                    started,
                    phase,
                    {
                        "phase_progress_percent": 100.0,
                        "processed_duration_seconds": rendered.duration_seconds,
                        "total_duration_seconds": rendered.duration_seconds,
                    },
                )
                video = next(item for item in probe.streams if item.codec_type == "video")
                audio = next(item for item in probe.streams if item.codec_type == "audio")
                result = MotionPreviewResult(
                    preview_id=flight.key,
                    attempt_id=flight.attempt_id,
                    request_digest=flight.key,
                    byte_size=output.stat().st_size,
                    duration_seconds=float(probe.duration_seconds),
                    start_sample=flight.plan.request.excerpt.start_sample,
                    sample_count=flight.plan.request.excerpt.sample_count,
                    width=int(video.width),
                    height=int(video.height),
                    frame_rate=float(video.frame_rate),
                    video_codec=str(video.codec_name),
                    audio_codec=str(audio.codec_name),
                )
                self._remove_derived(directory, output)
                with self._condition:
                    flight.result = result
                    flight.artifact_path = output
                    flight.done = True
                    if flight.consumers == 0:
                        self._cleanup_flight_locked(flight)
                    self._condition.notify_all()
                return
        except RenderAdmissionCancelled as error:
            failure = MediaInfrastructureError(
                "PREVIEW_CANCELLED", "Preview request was cancelled."
            )
            failure.__cause__ = error
        except MediaInfrastructureError as error:
            failure = error
        except Exception as error:
            failure = MediaInfrastructureError(
                "PREVIEW_INTERNAL_ERROR", "The motion preview could not be prepared safely."
            )
            failure.__cause__ = error
        try:
            self._release_owner_lock(flight)
        except MediaInfrastructureError:
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            cleanup = {
                "outcome": "failed",
                "error_code": "STORAGE_ERROR",
                "started_at": now,
                "finished_at": now,
            }
        else:
            cleanup = self._cleanup_directory(flight.directory)
        if cleanup["outcome"] == "succeeded":
            flight.directory = None
        diagnostic_reference = self._diagnose(flight, phase, failure, rendered, cleanup)
        try:
            self._save_progress(
                flight,
                started,
                phase,
                {},
                failure_phase=phase,
                diagnostic_reference=diagnostic_reference,
            )
        except Exception:
            pass
        with self._condition:
            flight.error = failure
            flight.done = True
            if flight.consumers == 0 and cleanup["outcome"] == "succeeded":
                self._flights.pop(flight.key, None)
            self._condition.notify_all()

    def _release(self, flight: _PreviewFlight) -> None:
        with self._condition:
            self._release_locked(flight)

    def _release_locked(self, flight: _PreviewFlight) -> None:
        if flight.consumers <= 0:
            return
        if flight.consumers == 1 and flight.done:
            self._cleanup_flight_locked(flight)
            flight.consumers = 0
        else:
            flight.consumers -= 1
            if flight.consumers == 0:
                flight.cancel_event.set()
        self._condition.notify_all()

    def _cleanup_flight_locked(self, flight: _PreviewFlight) -> None:
        self._release_owner_lock(flight)
        cleanup = self._cleanup_directory(flight.directory)
        if cleanup["outcome"] != "succeeded":
            raise MediaInfrastructureError(
                "STORAGE_ERROR", "The final preview lease could not remove its private artifact."
            )
        flight.artifact_path = None
        self._flights.pop(flight.key, None)

    def _identity(
        self,
        project_root: Path,
        plan: ResolvedMotionPreviewPlan,
        source_sample_counts: tuple[int, ...] | None,
    ) -> str:
        inputs = [project_root / "video_manifest.json", project_root / plan.manifest.background]
        if source_sample_counts is None:
            inputs.extend(project_root / track.audio for track in plan.selected_tracks)
        else:
            excerpt_start = plan.request.excerpt.start_sample
            excerpt_end = excerpt_start + plan.request.excerpt.sample_count
            position = 0
            for track, count in zip(plan.selected_tracks, source_sample_counts, strict=True):
                if position < excerpt_end and position + count > excerpt_start:
                    inputs.append(project_root / track.audio)
                position += count
        if isinstance(plan, PlayerMotionPreviewPlan):
            assert plan.manifest.effects.player is not None
            inputs.append(project_root / plan.manifest.effects.player.font.path)
        try:
            return canonical_sha256(
                {
                    "project": str(project_root.resolve()).casefold(),
                    "request": plan.request.to_dict(),
                    "inputs": [self._sha256(path) for path in inputs],
                    "toolchain": self.tool_identity,
                    "renderer": (
                        PLAYER_RENDERER_VERSION
                        if isinstance(plan, PlayerMotionPreviewPlan)
                        else REFINED_RENDERER_VERSION
                        if isinstance(plan, RefinedMotionPreviewPlan)
                        else "wu3b-motion-export-1"
                    ),
                    "presentation_version": (
                        PLAYER_PRESENTATION_VERSION
                        if isinstance(plan, PlayerMotionPreviewPlan)
                        else None
                    ),
                }
            )
        except OSError as error:
            raise MediaInfrastructureError(
                "PREVIEW_SOURCE_UNAVAILABLE", "A preview source could not be fingerprinted."
            ) from error

    @staticmethod
    def _selected_sample_counts(
        manifest: Any,
        plan: ResolvedMotionPreviewPlan,
        project_counts: tuple[int, ...] | None,
    ) -> tuple[int, ...] | None:
        if project_counts is None or len(project_counts) != len(manifest.tracks):
            return None
        by_id = {
            track.id: count for track, count in zip(manifest.tracks, project_counts, strict=True)
        }
        try:
            return tuple(by_id[track.id] for track in plan.selected_tracks)
        except KeyError:
            return None

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _copy(source: Path, destination: Path, flight: _PreviewFlight) -> None:
        if flight.cancel_event.is_set():
            raise MediaInfrastructureError("PREVIEW_CANCELLED", "Preview request was cancelled.")
        try:
            with source.open("rb") as input_stream, destination.open("xb") as output_stream:
                while chunk := input_stream.read(1024 * 1024):
                    if flight.cancel_event.is_set():
                        raise MediaInfrastructureError(
                            "PREVIEW_CANCELLED", "Preview request was cancelled."
                        )
                    output_stream.write(chunk)
        except MediaInfrastructureError:
            raise
        except OSError as error:
            raise MediaInfrastructureError(
                "STORAGE_ERROR", "A preview source could not be snapshotted."
            ) from error

    @staticmethod
    def _expected(flight: _PreviewFlight, duration: float) -> dict[str, Any]:
        return {
            "video_codec": "h264",
            "audio_codec": "aac",
            "width": 1920,
            "height": 1080,
            "pixel_format": "yuv420p",
            "frame_rate": 30.0,
            "audio_sample_rate": 48000,
            "audio_channels": 2,
            "video_profile": "High",
            "audio_profile": "LC",
            "color_space": "bt709",
            "color_transfer": "bt709",
            "color_primaries": "bt709",
            "duration_seconds": duration,
            "duration_tolerance_seconds": 0.1,
            "request_digest": flight.key,
            "faststart": True,
            "full_decode": True,
            "decode_timeout_seconds": max(30.0, duration * 4.0),
        }

    def _save_progress(
        self,
        flight: _PreviewFlight,
        started: float,
        phase: RenderPhase,
        value: dict[str, Any],
        *,
        failure_phase: RenderPhase | None = None,
        diagnostic_reference: str | None = None,
    ) -> None:
        if self.progress_store is None and self.progress_observer is None:
            return
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        progress = RenderProgress(
            job_id=flight.key,
            attempt_id=flight.attempt_id,
            phase=phase,
            phase_progress_percent=value.get("phase_progress_percent"),
            current_track=value.get("current_track"),
            total_tracks=value.get("total_tracks"),
            processed_duration_seconds=value.get("processed_duration_seconds"),
            total_duration_seconds=value.get("total_duration_seconds"),
            elapsed_seconds=max(0.0, time.monotonic() - started),
            eta_seconds=None,
            last_progress_at=timestamp,
            failure_phase=failure_phase,
            diagnostic_reference=diagnostic_reference,
        )
        if self.progress_store is not None:
            self.progress_store.save(progress)
        if self.progress_observer is not None:
            self.progress_observer(progress)

    def _diagnose(
        self,
        flight: _PreviewFlight,
        phase: RenderPhase,
        error: MediaInfrastructureError,
        rendered: Any,
        cleanup: dict[str, Any],
    ) -> str | None:
        if self.diagnostic_store is None:
            return None
        details = error.details
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            return self.diagnostic_store.save(
                {
                    "contract_version": "wrld-render-diagnostic/1.0",
                    "job_id": flight.key,
                    "attempt_id": flight.attempt_id,
                    "request_digest": flight.key,
                    "failure_phase": phase.value,
                    "error": {
                        "code": error.code,
                        "message": error.message,
                        "predicate": details.get("predicate"),
                        "expected": details.get("expected"),
                        "actual": details.get("actual"),
                    },
                    "ffmpeg_command": list(
                        getattr(rendered, "command", ()) or details.get("command", ())
                    ),
                    "ffmpeg_stderr_tail": str(
                        getattr(rendered, "stderr_tail", "") or details.get("stderr_tail", "")
                    )[:16384],
                    "toolchain": self.tool_identity,
                    "probe": details.get("probe"),
                    "cleanup": cleanup,
                    "failed_at": now,
                }
            )
        except Exception as diagnostic_error:
            LOGGER.warning(
                "Motion-preview diagnostic persistence failed (attempt=%s, error=%s).",
                flight.attempt_id,
                type(diagnostic_error).__name__,
            )
            return None

    def _remove_derived(self, directory: Path, keep: Path) -> None:
        for path in directory.iterdir():
            if path != keep and path.name not in {".preview-owner.json", ".preview-owner.lock"} and path.is_file():
                path.unlink()

    def _claim_directory(self, flight: _PreviewFlight) -> None:
        assert flight.directory is not None
        marker = {
            "contract_version": "wrld-motion-preview-owner/1.0",
            "owner_id": uuid.uuid4().hex,
            "process_id": os.getpid(),
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "persistent_review": False,
        }
        marker_path = flight.directory / ".preview-owner.json"
        marker_path.write_text(
            json.dumps(marker, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        lock = portalocker.Lock(
            str(flight.directory / ".preview-owner.lock"), mode="a", timeout=0
        )
        try:
            lock.acquire()
        except (OSError, portalocker.exceptions.LockException) as error:
            raise MediaInfrastructureError(
                "STORAGE_ERROR", "The preview staging directory could not be owned safely."
            ) from error
        flight.owner_lock = lock

    @staticmethod
    def _release_owner_lock(flight: _PreviewFlight) -> None:
        lock = flight.owner_lock
        flight.owner_lock = None
        if lock is not None:
            try:
                lock.release()
            except (OSError, portalocker.exceptions.LockException) as error:
                raise MediaInfrastructureError(
                    "STORAGE_ERROR", "The preview ownership lock could not be released."
                ) from error

    def _reconcile_abandoned(self) -> None:
        now = datetime.now(timezone.utc)
        try:
            candidates = tuple(self.root.iterdir())[:32]
        except OSError as error:
            LOGGER.warning("Motion-preview reconciliation could not enumerate state (%s).", type(error).__name__)
            return
        for directory in candidates:
            try:
                if not directory.name.startswith("motion-preview-") or self._is_reparse(directory):
                    continue
                if not directory.is_dir():
                    continue
                marker_path = directory / ".preview-owner.json"
                if not marker_path.is_file() or self._is_reparse(marker_path):
                    continue
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
                if (
                    set(marker) != {
                        "contract_version", "owner_id", "process_id", "created_at", "persistent_review"
                    }
                    or marker["contract_version"] != "wrld-motion-preview-owner/1.0"
                    or type(marker["persistent_review"]) is not bool
                    or marker["persistent_review"]
                ):
                    continue
                created = datetime.fromisoformat(str(marker["created_at"]).replace("Z", "+00:00"))
                if created.tzinfo is None or (now - created).total_seconds() < self.abandoned_after_seconds:
                    continue
                lock = portalocker.Lock(str(directory / ".preview-owner.lock"), mode="a", timeout=0)
                try:
                    lock.acquire()
                except portalocker.exceptions.LockException:
                    continue
                try:
                    lock.release()
                    shutil.rmtree(directory)
                    LOGGER.info("Removed one crash-abandoned motion-preview directory.")
                finally:
                    try:
                        lock.release()
                    except Exception:
                        pass
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
                LOGGER.warning(
                    "Motion-preview reconciliation preserved a suspicious entry (%s).",
                    type(error).__name__,
                )

    @staticmethod
    def _is_reparse(path: Path) -> bool:
        try:
            info = os.lstat(path)
        except OSError:
            return True
        attributes = getattr(info, "st_file_attributes", 0)
        return stat.S_ISLNK(info.st_mode) or bool(
            attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )

    def _cleanup_directory(self, directory: Path | None) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        cleanup = {
            "outcome": "succeeded",
            "error_code": None,
            "started_at": now,
            "finished_at": now,
        }
        if directory is None:
            return cleanup
        try:
            resolved = directory.resolve(strict=False)
            resolved.relative_to(self.root)
            if not resolved.name.startswith("motion-preview-"):
                raise ValueError("unowned preview directory")
            if resolved.exists():
                shutil.rmtree(resolved)
        except (OSError, ValueError):
            cleanup["outcome"] = "failed"
            cleanup["error_code"] = "STORAGE_ERROR"
        cleanup["finished_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return cleanup
