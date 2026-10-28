import threading
import time
import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
import portalocker

from wrld_video_studio.application.motion_preview import MotionPreviews
from wrld_video_studio.application.render_coordination import ProcessLocalRenderAdmission
from wrld_video_studio.domain.jobs import MediaProbe, MediaStream
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.motion_preview import MotionPreviewExcerpt, resolve_motion_preview_request
from wrld_video_studio.domain.motion_preview_v2 import resolve_refined_motion_preview_request
from wrld_video_studio.domain.video_effects_v2 import VideoEffectsV2
from wrld_video_studio.domain.video_export import ExportTarget
from wrld_video_studio.domain.video_export_v2 import parse_motion_manifest
from wrld_video_studio.domain.video_export_v3 import parse_refined_manifest
from wrld_video_studio.infrastructure.video_export_renderer import RenderedVideo
from wrld_video_studio.infrastructure.render_attempt_records import (
    JsonRenderDiagnosticStore,
    JsonRenderProgressStore,
)


@dataclass(frozen=True)
class Project:
    root: Path
    manifest: object
    manifest_document: dict


class Loader:
    def __init__(self, project):
        self.project = project

    def load(self, _path):
        return self.project


class Renderer:
    def __init__(self, gate=None, failure=None):
        self.calls = 0
        self.gate = gate
        self.failure = failure
        self.started = threading.Event()

    def render(self, plan, audio, background, output, pcm, combined, digest, **kwargs):
        self.calls += 1
        self.started.set()
        if self.gate is not None:
            while not self.gate.is_set():
                if kwargs["cancel_event"].wait(0.01):
                    raise MediaInfrastructureError("PREVIEW_CANCELLED", "Preview request was cancelled.")
        if self.failure is not None:
            kwargs["progress"]({"phase": "encoding"})
            raise self.failure
        output.write_bytes(b"verified-mp4")
        return RenderedVideo((), plan.request.excerpt.sample_count, 5.0, ("ffmpeg",), "")


class Verifier:
    def verify(self, path, expected, **_kwargs):
        assert path.read_bytes() == b"verified-mp4"
        return MediaProbe(
            str(path),
            "fixture",
            expected["duration_seconds"],
            (
                MediaStream(0, "video", "h264", width=1920, height=1080, frame_rate=30.0),
                MediaStream(1, "audio", "aac"),
            ),
            "mov,mp4",
            {"comment": f"wrld_request:{expected['request_digest']}"},
        )


def _project(tmp_path):
    document = {
        "format": "wrld-video-album/2.0",
        "album": {"id": "a1", "title": "A", "artist": "B", "channel": "C"},
        "visual": {"background": "background.png"},
        "tracks": [{"id": "t1", "number": 1, "title": "T", "audio": "one.wav"}],
        "render": {
            "profile_id": "youtube-1080p30-motion-v1",
            "effects": {
                "pan_zoom": {"enabled": False, "max_zoom": 1.04, "path": "diagonal_down_right", "cycle_seconds": 180.0, "return_to_origin": True, "return_duration_seconds": 5.0, "easing": "smoothstep"},
                "audio_bars": {"enabled": False, "bar_count": 24, "opacity": 0.65, "placement": "bottom_center", "rms_window_samples": 1920, "attack_ms": 60.0, "release_ms": 240.0},
                "track_progress": {"enabled": False, "style": "line", "placement": "bottom", "opacity": 0.8, "thickness_px": 6, "segment_count": 20},
            },
        },
    }
    (tmp_path / "video_manifest.json").write_text("{}")
    (tmp_path / "background.png").write_bytes(b"image")
    (tmp_path / "one.wav").write_bytes(b"audio")
    return Project(tmp_path, parse_motion_manifest(document), document)


def _request(project):
    return resolve_motion_preview_request(
        project.manifest, ExportTarget("album"), MotionPreviewExcerpt(0, 240000)
    )


def _refined_project(tmp_path):
    document = {
        "format": "wrld-video-album/3.0",
        "album": {"id": "a1", "title": "A", "artist": "B", "channel": "C"},
        "visual": {"background": "background.png"},
        "tracks": [{"id": "t1", "number": 1, "title": "T", "audio": "one.wav"}],
        "render": {
            "profile_id": "youtube-1080p30-motion-v2",
            "effects": VideoEffectsV2().to_dict(),
        },
    }
    (tmp_path / "video_manifest.json").write_text("{}")
    (tmp_path / "background.png").write_bytes(b"image")
    (tmp_path / "one.wav").write_bytes(b"audio")
    return Project(tmp_path, parse_refined_manifest(document), document)


def _refined_request(project):
    return resolve_refined_motion_preview_request(
        project.manifest, ExportTarget("album"), MotionPreviewExcerpt(0, 240000)
    )


def test_preview_final_owner_cleanup_and_no_output_pollution(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    project = _project(root)
    service = MotionPreviews(
        Loader(project), Renderer(), Verifier(), ProcessLocalRenderAdmission(), tmp_path / "private"
    )
    lease = service.prepare(root, _request(project))
    path = lease.path
    assert path.is_file()
    assert not (root / "output").exists()
    lease.close()
    assert not path.exists()
    assert not list((tmp_path / "private").iterdir())
    service.close()


def test_refined_preview_has_distinct_identity_and_same_lease_cleanup(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    project = _refined_project(root)
    renderer = Renderer()
    service = MotionPreviews(
        Loader(project), renderer, Verifier(), ProcessLocalRenderAdmission(), tmp_path / "private"
    )
    lease = service.prepare(root, _refined_request(project))
    path = lease.path
    assert path.is_file()
    assert renderer.calls == 1
    lease.close()
    assert not path.exists()
    assert not list((tmp_path / "private").iterdir())
    service.close()


def test_identical_concurrent_callers_share_flight_and_last_lease_owns_file(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    project = _project(root)
    gate = threading.Event()
    renderer = Renderer(gate)
    service = MotionPreviews(
        Loader(project), renderer, Verifier(), ProcessLocalRenderAdmission(), tmp_path / "private"
    )
    leases = []
    errors = []

    def call():
        try:
            leases.append(service.prepare(root, _request(project)))
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=call) for _ in range(2)]
    for thread in threads:
        thread.start()
    gate.set()
    for thread in threads:
        thread.join()
    assert not errors
    assert renderer.calls == 1
    path = leases[0].path
    leases[0].close()
    assert path.exists()
    leases[1].close()
    assert not path.exists()
    service.close()


def test_final_waiting_caller_cancellation_stops_work_and_cleans(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    project = _project(root)
    gate = threading.Event()
    service = MotionPreviews(
        Loader(project), Renderer(gate), Verifier(), ProcessLocalRenderAdmission(), tmp_path / "private"
    )
    cancelled = threading.Event()
    caught = []

    def call():
        try:
            service.prepare(root, _request(project), cancelled)
        except MediaInfrastructureError as error:
            caught.append(error.code)

    thread = threading.Thread(target=call)
    thread.start()
    assert service.renderer.started.wait(1)
    cancelled.set()
    cancelled.set()
    thread.join()
    service.close()
    assert caught == ["PREVIEW_CANCELLED"]
    assert not list((tmp_path / "private").iterdir())


def test_one_cancelled_joiner_does_not_cancel_remaining_owner(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    project = _project(root)
    gate = threading.Event()
    renderer = Renderer(gate)
    service = MotionPreviews(
        Loader(project), renderer, Verifier(), ProcessLocalRenderAdmission(), tmp_path / "private"
    )
    first_cancel = threading.Event()
    leases = []
    codes = []

    def first():
        try:
            service.prepare(root, _request(project), first_cancel)
        except MediaInfrastructureError as error:
            codes.append(error.code)

    def second():
        leases.append(service.prepare(root, _request(project)))

    first_thread = threading.Thread(target=first)
    second_thread = threading.Thread(target=second)
    first_thread.start()
    assert renderer.started.wait(1)
    second_thread.start()
    time.sleep(0.05)
    first_cancel.set()
    first_cancel.set()
    gate.set()
    first_thread.join()
    second_thread.join()
    assert codes == ["PREVIEW_CANCELLED"]
    assert len(leases) == 1
    assert renderer.calls == 1
    path = leases[0].path
    leases[0].close()
    assert not path.exists()
    service.close()


def test_distinct_preview_capacity_is_bounded_while_same_flight_still_joins(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    project = _project(root)
    gate = threading.Event()
    renderer = Renderer(gate=gate)
    service = MotionPreviews(
        Loader(project),
        renderer,
        Verifier(),
        ProcessLocalRenderAdmission(),
        tmp_path / "private",
        max_distinct_flights=2,
    )
    requests = [
        replace(_request(project), excerpt=MotionPreviewExcerpt(index, 240000))
        for index in range(3)
    ]
    leases = []
    errors = []

    def prepare(request):
        try:
            leases.append(service.prepare(root, request))
        except BaseException as error:
            errors.append(error)

    first = threading.Thread(target=prepare, args=(requests[0],))
    second = threading.Thread(target=prepare, args=(requests[1],))
    first.start()
    assert renderer.started.wait(1)
    second.start()
    deadline = time.monotonic() + 2
    while len(service._flights) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)

    with pytest.raises(MediaInfrastructureError) as caught:
        service.prepare(root, requests[2])
    assert caught.value.code == "PREVIEW_CAPACITY_EXHAUSTED"
    assert caught.value.details == {"capacity": 2}

    gate.set()
    first.join(2)
    second.join(2)
    assert errors == []
    assert len(leases) == 2
    for lease in leases:
        lease.close()
    service.close()


def test_startup_reconciliation_removes_only_old_unlocked_owned_previews(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    project = _project(root)
    preview_root = tmp_path / "private"
    abandoned = preview_root / "motion-preview-abandoned"
    active = preview_root / "motion-preview-active"
    suspicious = preview_root / "motion-preview-unmarked"
    for directory in (abandoned, active, suspicious):
        directory.mkdir(parents=True)
        (directory / "preview.mp4").write_bytes(b"temporary")
    marker = {
        "contract_version": "wrld-motion-preview-owner/1.0",
        "owner_id": "fixture",
        "process_id": 1,
        "created_at": "2020-01-01T00:00:00Z",
        "persistent_review": False,
    }
    for directory in (abandoned, active):
        (directory / ".preview-owner.json").write_text(json.dumps(marker), encoding="utf-8")
    lock = portalocker.Lock(str(active / ".preview-owner.lock"), mode="a", timeout=0)
    lock.acquire()
    try:
        service = MotionPreviews(
            Loader(project),
            Renderer(),
            Verifier(),
            ProcessLocalRenderAdmission(),
            preview_root,
            abandoned_after_seconds=0,
        )
        assert not abandoned.exists()
        assert active.is_dir()
        assert suspicious.is_dir()
        service.close()
    finally:
        lock.release()


def test_renderer_failure_and_shutdown_overlap_leave_no_private_media(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    project = _project(root)
    gate = threading.Event()
    renderer = Renderer(gate)
    service = MotionPreviews(
        Loader(project), renderer, Verifier(), ProcessLocalRenderAdmission(), tmp_path / "private"
    )
    codes = []

    def call():
        try:
            service.prepare(root, _request(project))
        except MediaInfrastructureError as error:
            codes.append(error.code)

    thread = threading.Thread(target=call)
    thread.start()
    assert renderer.started.wait(1)
    service.close()
    thread.join()
    assert codes == ["PREVIEW_CANCELLED"]
    assert not list((tmp_path / "private").iterdir())


def test_renderer_failure_is_safe_and_cleans_owned_staging(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    project = _project(root)
    service = MotionPreviews(
        Loader(project),
        Renderer(failure=MediaInfrastructureError("PROCESS_FAILED", "Encoding failed.")),
        Verifier(),
        ProcessLocalRenderAdmission(),
        tmp_path / "private",
    )
    with pytest.raises(MediaInfrastructureError) as caught:
        service.prepare(root, _request(project))
    assert (caught.value.code, caught.value.message) == ("PROCESS_FAILED", "Encoding failed.")
    assert not list((tmp_path / "private").iterdir())
    service.close()


def test_failure_persists_private_diagnostic_and_failed_progress(tmp_path, schema_dir):
    root = tmp_path / "project"
    root.mkdir()
    project = _project(root)
    progress_root = tmp_path / "state" / "progress"
    diagnostic_root = tmp_path / "state" / "diagnostics"
    service = MotionPreviews(
        Loader(project),
        Renderer(failure=MediaInfrastructureError("PROCESS_FAILED", "Encoding failed.")),
        Verifier(),
        ProcessLocalRenderAdmission(),
        tmp_path / "private",
        progress_store=JsonRenderProgressStore(
            progress_root, schema_dir / "render-progress-v1.schema.json"
        ),
        diagnostic_store=JsonRenderDiagnosticStore(
            diagnostic_root, schema_dir / "render-diagnostic-v1.schema.json"
        ),
    )
    with pytest.raises(MediaInfrastructureError):
        service.prepare(root, _request(project))
    diagnostics = list(diagnostic_root.rglob("*.json"))
    progress_files = list(progress_root.rglob("*.json"))
    assert len(diagnostics) == len(progress_files) == 1
    diagnostic = json.loads(diagnostics[0].read_text(encoding="utf-8"))
    progress = json.loads(progress_files[0].read_text(encoding="utf-8"))
    assert diagnostic["failure_phase"] == "encoding"
    assert diagnostic["error"]["code"] == "PROCESS_FAILED"
    assert diagnostic["cleanup"]["outcome"] == "succeeded"
    assert progress["failure_phase"] == "encoding"
    assert progress["diagnostic_reference"].startswith("diagnostics/")
    service.close()


def test_final_owner_cleanup_failure_is_surfaced_and_retryable(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    project = _project(root)
    service = MotionPreviews(
        Loader(project), Renderer(), Verifier(), ProcessLocalRenderAdmission(), tmp_path / "private"
    )
    lease = service.prepare(root, _request(project))
    path = lease.path
    import wrld_video_studio.application.motion_preview as module

    real_rmtree = module.shutil.rmtree
    monkeypatch.setattr(module.shutil, "rmtree", lambda _path: (_ for _ in ()).throw(OSError()))
    with pytest.raises(MediaInfrastructureError) as caught:
        lease.close()
    assert caught.value.code == "STORAGE_ERROR"
    assert path.exists()
    monkeypatch.setattr(module.shutil, "rmtree", real_rmtree)
    lease.close()
    assert not path.exists()
    service.close()
