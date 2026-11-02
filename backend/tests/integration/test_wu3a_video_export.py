import json
import os
import argparse
import threading
from array import array
from pathlib import Path

import pytest

from wrld_video_studio.application.media_jobs import MediaJobs, RenderWorker
from wrld_video_studio.application.motion_preview import MotionPreviews
from wrld_video_studio.application.render_coordination import ProcessLocalRenderAdmission
from wrld_video_studio.application.video_export import VideoExports
from wrld_video_studio.application.video_export_worker import VideoExportJobHandler
from wrld_video_studio.domain.jobs import MediaProbe, MediaStream
from wrld_video_studio.domain.jobs import JobState
from wrld_video_studio.domain.media_errors import IndeterminateMediaCommitError, MediaInfrastructureError
from wrld_video_studio.domain.render_progress import RenderPhase, RenderProgress
from wrld_video_studio.domain.video_export import (
    ExportTarget,
    VideoExportRequest,
    build_timeline,
)
from wrld_video_studio.domain.video_effects import (
    AudioBarsSettings,
    PanZoomSettings,
    TrackProgressSettings,
    VideoEffects,
)
from wrld_video_studio.domain.motion_preview import MotionPreviewExcerpt, resolve_motion_preview_request
from wrld_video_studio.domain.video_effects_v2 import (
    AudioBarsSettingsV2,
    TrackProgressSettingsV2,
    VideoEffectsV2,
)
from wrld_video_studio.domain.video_export_v2 import (
    MOTION_RENDERER_VERSION,
    MotionVideoExportRequest,
    create_motion_plan,
    parse_motion_manifest,
)
from wrld_video_studio.domain.video_export_v3 import (
    REFINED_RENDERER_VERSION,
    RefinedVideoExportRequest,
)
from wrld_video_studio.infrastructure.artifact_store import FilesystemArtifactStore
from wrld_video_studio.infrastructure.artifact_verifier import FFmpegArtifactVerifier
from wrld_video_studio.infrastructure.artwork_theme import FFmpegArtworkThemeResolver
from wrld_video_studio.infrastructure.job_repository import JsonJobRepository
from wrld_video_studio.infrastructure.ffprobe_adapter import FFprobeAdapter
from wrld_video_studio.infrastructure.project_sources import FilesystemVideoProjectLoader
from wrld_video_studio.infrastructure.render_attempt_records import (
    JsonRenderDiagnosticStore,
    JsonRenderProgressStore,
)
from wrld_video_studio.infrastructure.render_report_store import JsonVideoResultStore, RenderReportStore
from wrld_video_studio.infrastructure.video_export_renderer import (
    RenderedVideo,
    StaticVideoExportRenderer,
)
from wrld_video_studio.infrastructure.media_tools import MediaToolchain
from wrld_video_studio.infrastructure.process_runner import SubprocessRunner
from wrld_video_studio.interfaces.cli.video_export import run_video_export


def _project(tmp_path: Path, *, motion: bool = False, refined: bool = False) -> Path:
    project = tmp_path / "library" / "channel" / "Albums" / "Album"
    project.mkdir(parents=True)
    (project / "background.png").write_bytes(b"png")
    (project / "first.wav").write_bytes(b"wav-1")
    (project / "second.wav").write_bytes(b"wav-2")
    effects = (
        VideoEffectsV2(
            pan_zoom=PanZoomSettings(enabled=True),
            audio_bars=AudioBarsSettingsV2(enabled=True),
            track_progress=TrackProgressSettingsV2(enabled=True),
        )
        if refined
        else VideoEffects(pan_zoom=PanZoomSettings(enabled=motion))
    )
    manifest = {
        "format": (
            "wrld-video-album/3.0"
            if refined
            else "wrld-video-album/2.0"
            if motion
            else "wrld-video-album/1.0"
        ),
        "album": {"id": "album-1", "title": "Album", "artist": "Artist", "channel": "Channel"},
        "visual": {"background": "background.png"},
        "tracks": [
            {"id": "t1", "number": 1, "title": "First", "audio": "first.wav"},
            {"id": "t2", "number": 2, "title": "Second", "audio": "second.wav"},
        ],
        "render": (
            {
                "profile_id": "youtube-1080p30-motion-v1",
                "effects": effects.to_dict(),
            }
            if motion or refined
            else {"profile_id": "youtube-1080p30-v1"}
        ),
    }
    if refined:
        manifest["render"]["profile_id"] = "youtube-1080p30-motion-v2"
    (project / "video_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return project


class FakeProber:
    def probe(self, path):
        return _probe(path)


class UnusedEncoder:
    pass


class FakeVerifier:
    def verify(self, path, expected, **kwargs):
        assert path.is_file()
        return _probe(path, expected["duration_seconds"])


class RejectingColorVerifier:
    def verify(self, path, expected, **kwargs):
        callback = kwargs.get("phase_callback")
        if callback is not None:
            callback("probing_output")
        raise MediaInfrastructureError(
            "OUTPUT_INVALID",
            "Output video color transfer check failed.",
            {
                "predicate": "video color transfer",
                "expected": "bt709",
                "actual": None,
                "probe": {"streams": [{"codec_type": "video", "color_transfer": None}]},
            },
        )


class FakeRenderer:
    def render(self, plan, audio_sources, background, staged, pcm_paths, combined, request_digest, *args, **kwargs):
        assert all(path.is_file() for path in audio_sources)
        assert background.is_file()
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(b"fake-mp4")
        counts = tuple(480_000 for _ in plan.selected_tracks)
        timeline = build_timeline(plan.selected_tracks, counts)
        duration = sum(counts) / 48_000
        return RenderedVideo(timeline, sum(counts), duration, ("<tool:ffmpeg>",), "")


def _probe(path, duration=10.0):
    return MediaProbe(
        str(path),
        "fake",
        duration,
        (
            MediaStream(0, "video", "h264", width=1920, height=1080, frame_rate=30.0, pixel_format="yuv420p"),
            MediaStream(1, "audio", "aac", sample_rate=48000, channels=2),
        ),
        "mov,mp4,m4a,3gp,3g2,mj2",
        {},
    )


def _services(tmp_path, schema_dir, *, renderer=None, verifier=None, report_store=None,
              progress_store=None, diagnostic_store=None, artifact_factory=None,
              motion=False, refined=False):
    project = _project(tmp_path, motion=motion, refined=refined)
    state = tmp_path / "state"
    repository = JsonJobRepository(
        state / "jobs",
        schema_dir / "render-job-snapshot-v1.schema.json",
        schema_dir / "render-job-status-v1.schema.json",
    )
    artifacts = (
        artifact_factory(project / "output")
        if artifact_factory is not None
        else FilesystemArtifactStore(project / "output")
    )
    reports = report_store or RenderReportStore(project, schema_dir / "render-report-v1.schema.json")
    result_schemas = (
        (
            schema_dir / "video-export-result-v1.schema.json",
            schema_dir / "video-export-result-v2.schema.json",
        )
        if motion or refined
        else schema_dir / "video-export-result-v1.schema.json"
    )
    if refined:
        result_schemas = result_schemas + (
            schema_dir / "video-export-result-v3.schema.json",
        )
    results = JsonVideoResultStore(state / "results", result_schemas)
    progress_store = progress_store or JsonRenderProgressStore(
        state / "progress", schema_dir / "render-progress-v1.schema.json"
    )
    diagnostic_store = diagnostic_store or JsonRenderDiagnosticStore(
        state / "diagnostics", schema_dir / "render-diagnostic-v1.schema.json"
    )
    handler = VideoExportJobHandler(
        source_root=project,
        repository=repository,
        artifacts=artifacts,
        renderer=renderer or FakeRenderer(),
        verifier=verifier or FakeVerifier(),
        report_store=reports,
        result_store=results,
        progress_store=progress_store,
        diagnostic_store=diagnostic_store,
    )
    worker = RenderWorker(
        repository, FakeProber(), UnusedEncoder(), FakeVerifier(), artifacts, project,
        admission=ProcessLocalRenderAdmission(), request_handlers=(handler,),
    )
    manifest_schemas = (
        (
            schema_dir / "video-manifest-v1.schema.json",
            schema_dir / "video-manifest-v2.schema.json",
        )
        if motion or refined
        else schema_dir / "video-manifest-v1.schema.json"
    )
    if refined:
        manifest_schemas = manifest_schemas + (
            schema_dir / "video-manifest-v3.schema.json",
        )
    loader = FilesystemVideoProjectLoader(manifest_schemas)
    return project, repository, reports, results, worker, VideoExports(loader, MediaJobs(repository))


def _motion_request(target):
    return MotionVideoExportRequest(
        target,
        VideoEffects(pan_zoom=PanZoomSettings(enabled=True)),
    )


def _refined_request(target):
    return RefinedVideoExportRequest(
        target,
        VideoEffectsV2(
            pan_zoom=PanZoomSettings(enabled=True),
            audio_bars=AudioBarsSettingsV2(enabled=True),
            track_progress=TrackProgressSettingsV2(enabled=True),
        ),
    )


def test_album_export_uses_existing_worker_and_publishes_report(tmp_path, schema_dir):
    project, _repository, _reports, results, worker, exports = _services(tmp_path, schema_dir)
    submitted = exports.submit(project, VideoExportRequest(ExportTarget("album")))
    completed = worker.run_next()
    assert completed is not None and completed[1].status.value == "completed"
    assert (project / "output" / "album" / "Album.mp4").read_bytes() == b"fake-mp4"
    assert (project / "output" / "metadata" / "chapters.txt").read_text() == (
        "00:00 First\n00:10 Second\n"
    )
    report = json.loads((project / "output" / "metadata" / "render_report.json").read_text())
    assert report["project_id"] == "album-1"
    assert [item["kind"] for item in report["artifacts"]] == ["album_video", "chapters"]
    assert results.load(submitted.snapshot.job_id, submitted.snapshot.attempt_id)["timeline"][1]["start_sample"] == 480000


def test_track_export_has_no_chapter_artifact(tmp_path, schema_dir):
    project, _repository, _reports, _results, worker, exports = _services(tmp_path, schema_dir)
    exports.submit(project, VideoExportRequest(ExportTarget("track", "t2")))
    completed = worker.run_next()
    assert completed is not None and completed[1].status.value == "completed"
    assert (project / "output" / "tracks" / "02 - Second.mp4").is_file()
    assert not (project / "output" / "metadata" / "chapters.txt").exists()


def test_motion_track_uses_shared_worker_and_publishes_v2_result(tmp_path, schema_dir):
    project, _repository, reports, results, worker, exports = _services(
        tmp_path, schema_dir, motion=True
    )
    request = _motion_request(ExportTarget("track", "t1"))

    submitted = exports.submit(project, request)
    completed = worker.run_next()

    assert completed is not None and completed[1].status is JobState.COMPLETED
    digest = request.effects.fingerprint
    output = (
        project
        / "output"
        / "profiles"
        / "youtube-1080p30-motion-v1"
        / digest
        / "tracks"
        / "01 - First.mp4"
    )
    assert output.read_bytes() == b"fake-mp4"
    result = results.load(submitted.snapshot.job_id, submitted.snapshot.attempt_id)
    assert result["contract_version"] == "video-export-result/2.0"
    assert result["profile_id"] == "youtube-1080p30-motion-v1"
    assert result["effects"] == request.effects.to_dict()
    assert submitted.snapshot.renderer_version == MOTION_RENDERER_VERSION
    assert reports.matching_result(submitted.snapshot.request_digest) == result


def test_refined_track_uses_shared_worker_and_publishes_v3_result(tmp_path, schema_dir):
    project, _repository, reports, results, worker, exports = _services(
        tmp_path, schema_dir, refined=True
    )
    request = _refined_request(ExportTarget("track", "t1"))

    submitted = exports.submit(project, request)
    completed = worker.run_next()

    assert completed is not None and completed[1].status is JobState.COMPLETED
    output = (
        project
        / "output"
        / "profiles"
        / "youtube-1080p30-motion-v2"
        / request.effects.fingerprint
        / "tracks"
        / "01 - First.mp4"
    )
    assert output.read_bytes() == b"fake-mp4"
    result = results.load(submitted.snapshot.job_id, submitted.snapshot.attempt_id)
    assert result["contract_version"] == "video-export-result/3.0"
    assert result["profile_id"] == "youtube-1080p30-motion-v2"
    assert result["effects"] == request.effects.to_dict()
    assert submitted.snapshot.renderer_version == REFINED_RENDERER_VERSION
    assert reports.matching_result(submitted.snapshot.request_digest) == result

    reused = exports.submit(project, request)
    assert reused.snapshot.request_digest == submitted.snapshot.request_digest
    assert reused.status.status is JobState.COMPLETED
    assert worker.run_next() is None


def test_exact_motion_request_reuses_verified_result_without_second_render(tmp_path, schema_dir):
    project, _repository, _reports, _results, worker, exports = _services(
        tmp_path, schema_dir, motion=True
    )
    request = _motion_request(ExportTarget("track", "t1"))
    first = exports.submit(project, request)
    assert worker.run_next()[1].status is JobState.COMPLETED

    second = exports.submit(project, request)

    assert second.snapshot.request_digest == first.snapshot.request_digest
    assert second.status.status is JobState.COMPLETED
    assert worker.run_next() is None


def test_changed_motion_source_cannot_replace_existing_effect_path(tmp_path, schema_dir):
    project, _repository, _reports, _results, worker, exports = _services(
        tmp_path, schema_dir, motion=True
    )
    request = _motion_request(ExportTarget("track", "t1"))
    first = exports.submit(project, request)
    assert worker.run_next()[1].status is JobState.COMPLETED
    (project / "first.wav").write_bytes(b"changed-source")

    second = exports.submit(project, request)
    failed = worker.run_next()

    assert second.snapshot.request_digest != first.snapshot.request_digest
    assert failed is not None and failed[1].status is JobState.FAILED
    assert failed[1].error["code"] == "OUTPUT_EXISTS"


def test_motion_request_preserves_cooperative_cancellation(tmp_path, schema_dir):
    entered = threading.Event()

    class BlockingMotionRenderer:
        def render(self, *args, **kwargs):
            token = args[7]
            entered.set()
            assert token.wait(timeout=5)
            raise MediaInfrastructureError("PROCESS_CANCELLED", "cancelled")

    project, repository, _reports, _results, worker, exports = _services(
        tmp_path, schema_dir, renderer=BlockingMotionRenderer(), motion=True
    )
    submitted = exports.submit(
        project, _motion_request(ExportTarget("track", "t1"))
    )
    box = []
    thread = threading.Thread(target=lambda: box.append(worker.run_next()))
    thread.start()
    assert entered.wait(timeout=5)
    worker.request_cancel(submitted.snapshot.job_id, submitted.snapshot.attempt_id)
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert box[0][1].status is JobState.CANCELLED
    assert repository.get(submitted.snapshot.job_id)[1].status is JobState.CANCELLED
    assert not any((project / "output").rglob("*.mp4"))


def test_phase3_accepts_audio_bars_and_progress_for_worker_submission(tmp_path, schema_dir):
    project, repository, _reports, _results, _worker, exports = _services(
        tmp_path, schema_dir, motion=True
    )
    document = json.loads((project / "video_manifest.json").read_text(encoding="utf-8"))
    document["render"]["effects"]["audio_bars"]["enabled"] = True
    document["render"]["effects"]["track_progress"]["enabled"] = True
    (project / "video_manifest.json").write_text(json.dumps(document), encoding="utf-8")
    effects = VideoEffects.from_dict(document["render"]["effects"])

    submitted = exports.submit(
        project,
        MotionVideoExportRequest(ExportTarget("track", "t1"), effects),
    )

    claimed = repository.claim_next()
    assert claimed is not None
    assert claimed[0].job_id == submitted.snapshot.job_id


def test_phase3_cancellation_cleans_attempt_owned_effect_control(tmp_path, schema_dir):
    entered = threading.Event()

    class CancellingEffectRenderer:
        def render(self, *args, **kwargs):
            control = kwargs["effect_control_path"]
            control.parent.mkdir(parents=True, exist_ok=True)
            control.write_text("partial", encoding="ascii")
            entered.set()
            assert args[7].wait(timeout=5)
            raise MediaInfrastructureError("PROCESS_CANCELLED", "cancelled")

    project, repository, _reports, _results, worker, exports = _services(
        tmp_path, schema_dir, renderer=CancellingEffectRenderer(), motion=True
    )
    document = json.loads((project / "video_manifest.json").read_text(encoding="utf-8"))
    document["render"]["effects"]["audio_bars"]["enabled"] = True
    (project / "video_manifest.json").write_text(json.dumps(document), encoding="utf-8")
    effects = VideoEffects.from_dict(document["render"]["effects"])
    submitted = exports.submit(
        project, MotionVideoExportRequest(ExportTarget("track", "t1"), effects)
    )

    box = []
    thread = threading.Thread(target=lambda: box.append(worker.run_next()))
    thread.start()
    assert entered.wait(timeout=5)
    worker.request_cancel(submitted.snapshot.job_id, submitted.snapshot.attempt_id)
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert box[0] is not None and box[0][1].status is JobState.CANCELLED
    assert repository.get(submitted.snapshot.job_id)[1].status is JobState.CANCELLED
    assert not any((project / "output" / ".wrld-staging").rglob("*.sendcmd"))


def test_refined_cancellation_cleans_attempt_owned_effect_control(tmp_path, schema_dir):
    entered = threading.Event()

    class CancellingRefinedRenderer:
        def render(self, *args, **kwargs):
            control = kwargs["effect_control_path"]
            control.parent.mkdir(parents=True, exist_ok=True)
            control.write_text("partial", encoding="ascii")
            entered.set()
            assert args[7].wait(timeout=5)
            raise MediaInfrastructureError("PROCESS_CANCELLED", "cancelled")

    project, repository, _reports, _results, worker, exports = _services(
        tmp_path, schema_dir, renderer=CancellingRefinedRenderer(), refined=True
    )
    submitted = exports.submit(
        project, _refined_request(ExportTarget("track", "t1"))
    )
    box = []
    thread = threading.Thread(target=lambda: box.append(worker.run_next()))
    thread.start()
    assert entered.wait(timeout=5)
    worker.request_cancel(submitted.snapshot.job_id, submitted.snapshot.attempt_id)
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert box[0] is not None and box[0][1].status is JobState.CANCELLED
    assert repository.get(submitted.snapshot.job_id)[1].status is JobState.CANCELLED
    assert not any((project / "output" / ".wrld-staging").rglob("*.sendcmd"))


def test_static_then_motion_album_reuses_verified_profile_independent_chapters(
    tmp_path, schema_dir
):
    project, repository, reports, _results, static_worker, static_exports = _services(
        tmp_path, schema_dir
    )
    static_exports.submit(project, VideoExportRequest(ExportTarget("album")))
    assert static_worker.run_next()[1].status is JobState.COMPLETED
    original_chapters = (project / "output" / "metadata" / "chapters.txt").read_bytes()
    document = json.loads((project / "video_manifest.json").read_text(encoding="utf-8"))
    effects = VideoEffects(pan_zoom=PanZoomSettings(enabled=True))
    document["format"] = "wrld-video-album/2.0"
    document["render"] = {
        "profile_id": "youtube-1080p30-motion-v1",
        "effects": effects.to_dict(),
    }
    (project / "video_manifest.json").write_text(json.dumps(document), encoding="utf-8")
    state = tmp_path / "state"
    artifacts = FilesystemArtifactStore(project / "output")
    results = JsonVideoResultStore(
        state / "results",
        (
            schema_dir / "video-export-result-v1.schema.json",
            schema_dir / "video-export-result-v2.schema.json",
        ),
    )
    progress = JsonRenderProgressStore(
        state / "progress", schema_dir / "render-progress-v1.schema.json"
    )
    diagnostics = JsonRenderDiagnosticStore(
        state / "diagnostics", schema_dir / "render-diagnostic-v1.schema.json"
    )
    handler = VideoExportJobHandler(
        source_root=project,
        repository=repository,
        artifacts=artifacts,
        renderer=FakeRenderer(),
        verifier=FakeVerifier(),
        report_store=reports,
        result_store=results,
        progress_store=progress,
        diagnostic_store=diagnostics,
    )
    worker = RenderWorker(
        repository,
        FakeProber(),
        UnusedEncoder(),
        FakeVerifier(),
        artifacts,
        project,
        admission=ProcessLocalRenderAdmission(),
        request_handlers=(handler,),
    )
    loader = FilesystemVideoProjectLoader(
        (
            schema_dir / "video-manifest-v1.schema.json",
            schema_dir / "video-manifest-v2.schema.json",
        )
    )
    exports = VideoExports(loader, MediaJobs(repository))

    submitted = exports.submit(
        project, MotionVideoExportRequest(ExportTarget("album"), effects)
    )
    completed = worker.run_next()

    assert completed is not None and completed[1].status is JobState.COMPLETED
    assert (project / "output" / "metadata" / "chapters.txt").read_bytes() == original_chapters
    report = json.loads((project / "output" / "metadata" / "render_report.json").read_text())
    assert len(report["history"]) == 2
    assert sum(item["kind"] == "chapters" for item in report["artifacts"]) == 1
    result = results.load(submitted.snapshot.job_id, submitted.snapshot.attempt_id)
    assert result["contract_version"] == "video-export-result/2.0"


def test_unowned_chapter_collision_is_still_rejected_before_media_promotion(
    tmp_path, schema_dir
):
    project, _repository, _reports, _results, worker, exports = _services(
        tmp_path, schema_dir, motion=True
    )
    chapter = project / "output" / "metadata" / "chapters.txt"
    chapter.parent.mkdir(parents=True)
    chapter.write_text("unowned\n", encoding="utf-8")
    exports.submit(project, _motion_request(ExportTarget("album")))

    failed = worker.run_next()

    assert failed is not None and failed[1].status is JobState.FAILED
    assert failed[1].error["code"] == "OUTPUT_EXISTS"
    assert not any((project / "output" / "profiles").rglob("*.mp4"))
    assert chapter.read_text(encoding="utf-8") == "unowned\n"


def test_wu3a_never_opens_or_creates_publishing_metadata(tmp_path, schema_dir, monkeypatch):
    project, _repository, _reports, _results, worker, exports = _services(tmp_path, schema_dir)
    publishing = project / "youtube_metadata.json"
    publishing.write_bytes(b"opaque publishing data")
    before = publishing.read_bytes()
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        if path.name in {"youtube_metadata.json", "youtube_publish_state.json"}:
            raise AssertionError("WU3A attempted to access publishing-owned state")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    exports.submit(project, VideoExportRequest(ExportTarget("track", "t1")))
    completed = worker.run_next()
    assert completed is not None and completed[1].status is JobState.COMPLETED
    with original_open(publishing, "rb") as stream:
        assert stream.read() == before
    assert not (project / "output" / "metadata" / "youtube_metadata.json").exists()
    assert not (project / "output" / "metadata" / "youtube_publish_state.json").exists()


def test_product_handler_preserves_cooperative_cancellation(tmp_path, schema_dir):
    entered = threading.Event()

    class BlockingRenderer:
        def render(self, *args, **kwargs):
            token = args[7]
            entered.set()
            assert token.wait(timeout=5)
            raise MediaInfrastructureError("PROCESS_CANCELLED", "cancelled")

    project, repository, _reports, _results, worker, exports = _services(
        tmp_path, schema_dir, renderer=BlockingRenderer()
    )
    submitted = exports.submit(project, VideoExportRequest(ExportTarget("album")))
    box = []
    thread = threading.Thread(target=lambda: box.append(worker.run_next()))
    thread.start()
    assert entered.wait(timeout=5)
    worker.request_cancel(submitted.snapshot.job_id, submitted.snapshot.attempt_id)
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert box[0][1].status is JobState.CANCELLED
    assert not (project / "output" / "album" / "Album.mp4").exists()
    assert repository.get(submitted.snapshot.job_id)[1].status is JobState.CANCELLED


def test_verification_failure_persists_diagnostic_and_cleans_staging(tmp_path, schema_dir):
    state = tmp_path / "state"
    progress_store = JsonRenderProgressStore(
        state / "progress", schema_dir / "render-progress-v1.schema.json"
    )
    diagnostic_store = JsonRenderDiagnosticStore(
        state / "diagnostics", schema_dir / "render-diagnostic-v1.schema.json"
    )
    project, repository, _reports, _results, worker, exports = _services(
        tmp_path,
        schema_dir,
        verifier=RejectingColorVerifier(),
        progress_store=progress_store,
        diagnostic_store=diagnostic_store,
    )
    submitted = exports.submit(project, VideoExportRequest(ExportTarget("album")))

    failed = worker.run_next()

    assert failed is not None and failed[1].status is JobState.FAILED
    assert failed[1].error["code"] == "OUTPUT_INVALID"
    progress = progress_store.load(submitted.snapshot.job_id, submitted.snapshot.attempt_id)
    assert progress is not None
    assert progress.failure_phase.value == "probing_output"
    assert progress.diagnostic_reference is not None
    diagnostic = json.loads((state / progress.diagnostic_reference).read_text(encoding="utf-8"))
    assert diagnostic["error"] == {
        "code": "OUTPUT_INVALID",
        "message": "Output video color transfer check failed.",
        "predicate": "video color transfer",
        "expected": "bt709",
        "actual": None,
    }
    assert diagnostic["cleanup"]["outcome"] == "succeeded"
    assert diagnostic["ffmpeg_command"] == ["<tool:ffmpeg>"]
    assert str(project) not in json.dumps(diagnostic)
    assert not any((project / "output" / ".wrld-staging").rglob("*.mp4"))


def test_cleanup_failure_does_not_replace_primary_render_failure(tmp_path, schema_dir):
    class CleanupFails(FilesystemArtifactStore):
        def cleanup_owned(self, job_id, attempt_id):
            raise OSError("injected cleanup failure")

    state = tmp_path / "state"
    progress_store = JsonRenderProgressStore(
        state / "progress", schema_dir / "render-progress-v1.schema.json"
    )
    diagnostic_store = JsonRenderDiagnosticStore(
        state / "diagnostics", schema_dir / "render-diagnostic-v1.schema.json"
    )
    _project_path, _repository, _reports, _results, worker, exports = _services(
        tmp_path,
        schema_dir,
        verifier=RejectingColorVerifier(),
        progress_store=progress_store,
        diagnostic_store=diagnostic_store,
        artifact_factory=CleanupFails,
    )
    submitted = exports.submit(_project_path, VideoExportRequest(ExportTarget("album")))

    failed = worker.run_next()

    assert failed is not None and failed[1].error["code"] == "OUTPUT_INVALID"
    progress = progress_store.load(submitted.snapshot.job_id, submitted.snapshot.attempt_id)
    diagnostic = json.loads((state / progress.diagnostic_reference).read_text(encoding="utf-8"))
    assert diagnostic["error"]["code"] == "OUTPUT_INVALID"
    assert diagnostic["cleanup"] == {
        "outcome": "failed",
        "error_code": "STORAGE_ERROR",
        "started_at": diagnostic["cleanup"]["started_at"],
        "finished_at": diagnostic["cleanup"]["finished_at"],
    }


def test_diagnostic_failure_does_not_replace_primary_render_failure(tmp_path, schema_dir):
    class DiagnosticFails:
        def save(self, diagnostic):
            raise ValueError("injected diagnostic failure")

    state = tmp_path / "state"
    progress_store = JsonRenderProgressStore(
        state / "progress", schema_dir / "render-progress-v1.schema.json"
    )
    project, _repository, _reports, _results, worker, exports = _services(
        tmp_path,
        schema_dir,
        verifier=RejectingColorVerifier(),
        progress_store=progress_store,
        diagnostic_store=DiagnosticFails(),
    )
    submitted = exports.submit(project, VideoExportRequest(ExportTarget("album")))

    failed = worker.run_next()

    assert failed is not None and failed[1].error["code"] == "OUTPUT_INVALID"
    progress = progress_store.load(submitted.snapshot.job_id, submitted.snapshot.attempt_id)
    assert progress.failure_phase.value == "probing_output"
    assert progress.diagnostic_reference is None


def test_interrupted_report_publication_reconciles_promoted_artifacts(tmp_path, schema_dir):
    project = _project(tmp_path)
    state = tmp_path / "state"
    repository = JsonJobRepository(
        state / "jobs",
        schema_dir / "render-job-snapshot-v1.schema.json",
        schema_dir / "render-job-status-v1.schema.json",
    )
    artifacts = FilesystemArtifactStore(project / "output")
    real_reports = RenderReportStore(project, schema_dir / "render-report-v1.schema.json")

    class FailOnceReport:
        failed = False

        def matching_result(self, digest):
            return real_reports.matching_result(digest)

        def current_revision(self):
            return real_reports.current_revision()

        def publish(self, *args, **kwargs):
            if not self.failed:
                self.failed = True
                raise MediaInfrastructureError("STORAGE_ERROR", "injected report failure")
            return real_reports.publish(*args, **kwargs)

    results = JsonVideoResultStore(state / "results", schema_dir / "video-export-result-v1.schema.json")
    progress_store = JsonRenderProgressStore(
        state / "progress", schema_dir / "render-progress-v1.schema.json"
    )
    diagnostic_store = JsonRenderDiagnosticStore(
        state / "diagnostics", schema_dir / "render-diagnostic-v1.schema.json"
    )
    loader = FilesystemVideoProjectLoader(schema_dir / "video-manifest-v1.schema.json")
    exports = VideoExports(loader, MediaJobs(repository))
    submitted = exports.submit(project, VideoExportRequest(ExportTarget("album")))
    broken_handler = VideoExportJobHandler(
        source_root=project, repository=repository, artifacts=artifacts,
        renderer=FakeRenderer(), verifier=FakeVerifier(), report_store=FailOnceReport(),
        result_store=results,
        progress_store=progress_store, diagnostic_store=diagnostic_store,
    )
    broken_worker = RenderWorker(
        repository, FakeProber(), UnusedEncoder(), FakeVerifier(), artifacts, project,
        admission=ProcessLocalRenderAdmission(), request_handlers=(broken_handler,),
    )
    with pytest.raises(IndeterminateMediaCommitError):
        broken_worker.run_next()
    assert repository.get(submitted.snapshot.job_id)[1].status is JobState.VALIDATING
    assert (project / "output" / "album" / "Album.mp4").is_file()
    healthy_handler = VideoExportJobHandler(
        source_root=project, repository=repository, artifacts=artifacts,
        renderer=FakeRenderer(), verifier=FakeVerifier(), report_store=real_reports,
        result_store=results,
        progress_store=progress_store, diagnostic_store=diagnostic_store,
    )
    healthy_worker = RenderWorker(
        repository, FakeProber(), UnusedEncoder(), FakeVerifier(), artifacts, project,
        admission=ProcessLocalRenderAdmission(), request_handlers=(healthy_handler,),
    )
    assert healthy_worker.run_next() is None
    assert repository.get(submitted.snapshot.job_id)[1].status is JobState.COMPLETED
    recovered_progress = progress_store.load(
        submitted.snapshot.job_id, submitted.snapshot.attempt_id
    )
    assert recovered_progress.phase.value == "completed"
    assert recovered_progress.phase_progress_percent == 100.0
    assert (project / "output" / "metadata" / "render_report.json").is_file()


def test_crash_interrupted_export_is_reconciled_retried_and_exact_attempt_runs(
    tmp_path, schema_dir
):
    state = tmp_path / "state"
    progress_store = JsonRenderProgressStore(
        state / "progress", schema_dir / "render-progress-v1.schema.json"
    )
    diagnostic_store = JsonRenderDiagnosticStore(
        state / "diagnostics", schema_dir / "render-diagnostic-v1.schema.json"
    )
    project, repository, _reports, results, worker, exports = _services(
        tmp_path,
        schema_dir,
        progress_store=progress_store,
        diagnostic_store=diagnostic_store,
    )
    request = VideoExportRequest(ExportTarget("album"))
    interrupted = exports.submit(project, request)
    running = interrupted.status.transition(JobState.RUNNING)
    repository.update_status(running, interrupted.status.revision)
    progress_store.save(
        RenderProgress(
            job_id=interrupted.snapshot.job_id,
            attempt_id=interrupted.snapshot.attempt_id,
            phase=RenderPhase.ENCODING,
            phase_progress_percent=0.0,
            current_track=None,
            total_tracks=12,
            processed_duration_seconds=0.0,
            total_duration_seconds=None,
            elapsed_seconds=853.2,
            eta_seconds=None,
            last_progress_at="2026-10-28T16:50:55Z",
        )
    )

    recovered = worker.reconcile()
    retried = exports.submit(project, request)
    completed = worker.run_next(retried.snapshot.job_id, retried.snapshot.attempt_id)

    assert recovered[0][0].attempt_id == interrupted.snapshot.attempt_id
    assert recovered[0][1].status is JobState.FAILED
    assert recovered[0][1].error == {
        "code": "RECOVERABLE_INTERRUPTION",
        "message": "RECOVERABLE_INTERRUPTION",
    }
    assert retried.snapshot.job_id == interrupted.snapshot.job_id
    assert retried.snapshot.attempt_id != interrupted.snapshot.attempt_id
    assert retried.snapshot.request_digest == interrupted.snapshot.request_digest
    assert retried.status.status is JobState.QUEUED
    assert completed is not None
    assert completed[0].attempt_id == retried.snapshot.attempt_id
    assert completed[1].status is JobState.COMPLETED
    assert results.load(retried.snapshot.job_id, retried.snapshot.attempt_id) is not None
    historical = repository.get_attempt(
        interrupted.snapshot.job_id, interrupted.snapshot.attempt_id
    )[1]
    assert historical.status is JobState.FAILED
    historical_progress = progress_store.load(
        interrupted.snapshot.job_id, interrupted.snapshot.attempt_id
    )
    assert historical_progress is not None
    assert historical_progress.failure_phase is RenderPhase.ENCODING
    assert historical_progress.diagnostic_reference is not None
    assert (state / historical_progress.diagnostic_reference).is_file()
    assert len(repository.attempts(interrupted.snapshot.job_id)) == 2


def test_real_echoes_manifest_validates_against_implemented_schema(schema_dir):
    project = Path(r"C:\Users\ptanz\job_search\WORLD_MUSIC\WRLD-FI\Albums\Echoes of Asia - Album 1")
    if not project.is_dir():
        pytest.skip("Local acceptance album is unavailable")
    runner = SubprocessRunner()
    configured = {}
    if os.environ.get("WRLD_FFMPEG_PATH") and os.environ.get("WRLD_FFPROBE_PATH"):
        configured = {
            "ffmpeg": Path(os.environ["WRLD_FFMPEG_PATH"]),
            "ffprobe": Path(os.environ["WRLD_FFPROBE_PATH"]),
        }
    tools = MediaToolchain(runner, configured)
    try:
        tools.resolve("ffmpeg")
        tools.resolve("ffprobe")
    except MediaInfrastructureError:
        pytest.skip("Configured FFmpeg/FFprobe are unavailable for the real manifest")
    loaded = FilesystemVideoProjectLoader(
        tuple(schema_dir / f"video-manifest-v{version}.schema.json" for version in range(1, 5)),
        prober=FFprobeAdapter(tools, runner),
        theme_resolver=FFmpegArtworkThemeResolver(tools, runner),
    ).load(project)
    assert loaded.manifest.album.id == "wrld-fi-album-01"
    assert len(loaded.manifest.tracks) == 12
    assert loaded.manifest.background == "video_background.png"


@pytest.mark.integration_ffmpeg
def test_real_ffmpeg_album_and_track_through_supported_cli(tmp_path):
    runner = SubprocessRunner()
    configured = {}
    if os.environ.get("WRLD_FFMPEG_PATH") and os.environ.get("WRLD_FFPROBE_PATH"):
        configured = {
            "ffmpeg": Path(os.environ["WRLD_FFMPEG_PATH"]),
            "ffprobe": Path(os.environ["WRLD_FFPROBE_PATH"]),
        }
    tools = MediaToolchain(runner, configured)
    try:
        ffmpeg = tools.resolve("ffmpeg")
        ffprobe = tools.resolve("ffprobe")
    except Exception as error:
        pytest.skip(f"FFmpeg integration tools unavailable: {error}")
    project = tmp_path / "external-library" / "channel" / "Albums" / "Tiny Album"
    project.mkdir(parents=True)
    commands = [
        [str(ffmpeg.path), "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=640x360", "-frames:v", "1", "-y", str(project / "background.png")],
        [str(ffmpeg.path), "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.6", "-c:a", "pcm_s16le", "-y", str(project / "first.wav")],
        [str(ffmpeg.path), "-v", "error", "-f", "lavfi", "-i", "sine=frequency=660:duration=0.7", "-c:a", "pcm_s16le", "-y", str(project / "second.wav")],
    ]
    for command in commands:
        result = runner.run(command, timeout_seconds=30)
        assert result.returncode == 0 and not result.timed_out
    manifest = {
        "format": "wrld-video-album/1.0",
        "album": {"id": "tiny-album", "title": "Tiny Album", "artist": "Test", "channel": "Test"},
        "visual": {"background": "background.png"},
        "tracks": [
            {"id": "tiny-t01", "number": 1, "title": "First", "audio": "first.wav"},
            {"id": "tiny-t02", "number": 2, "title": "Second", "audio": "second.wav"},
        ],
        "render": {"profile_id": "youtube-1080p30-v1"},
    }
    (project / "video_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    base = {
        "album_project": str(project.resolve()),
        "profile": "youtube-1080p30-v1",
        "ffmpeg_path": str(ffmpeg.path),
        "ffprobe_path": str(ffprobe.path),
    }
    assert run_video_export(
        argparse.Namespace(**base, target="album", track_id=None), state_root=tmp_path / "state"
    ) == 0
    assert run_video_export(
        argparse.Namespace(**base, target="track", track_id="tiny-t01"), state_root=tmp_path / "state"
    ) == 0
    assert (project / "output" / "album" / "Tiny Album.mp4").is_file()
    assert (project / "output" / "tracks" / "01 - First.mp4").is_file()
    album_output = project / "output" / "album" / "Tiny Album.mp4"
    track_output = project / "output" / "tracks" / "01 - First.mp4"
    album_probe = FFprobeAdapter(tools, runner).probe(album_output)
    track_probe = FFprobeAdapter(tools, runner).probe(track_output)
    album_video = next(item for item in album_probe.streams if item.codec_type == "video")
    album_audio = next(item for item in album_probe.streams if item.codec_type == "audio")
    assert (album_video.codec_name, album_video.width, album_video.height) == ("h264", 1920, 1080)
    assert album_video.frame_rate == pytest.approx(30.0, abs=0.01)
    assert (album_video.color_space, album_video.color_transfer, album_video.color_primaries) == (
        "bt709", "bt709", "bt709"
    )
    assert (album_audio.codec_name, album_audio.sample_rate, album_audio.channels) == ("aac", 48000, 2)
    track_video = next(item for item in track_probe.streams if item.codec_type == "video")
    assert (track_video.color_space, track_video.color_transfer, track_video.color_primaries) == (
        "bt709", "bt709", "bt709"
    )
    assert album_probe.duration_seconds == pytest.approx(1.3, abs=0.25)
    assert track_probe.duration_seconds == pytest.approx(0.6, abs=0.25)
    decoded = tmp_path / "decoded-album.pcm"
    decode = runner.run(
        [
            str(ffmpeg.path), "-v", "error", "-xerror", "-i", str(album_output),
            "-map", "0:a:0", "-ac", "1", "-ar", "48000", "-f", "s16le", "-y", str(decoded),
        ],
        timeout_seconds=60,
    )
    assert decode.returncode == 0 and not decode.timed_out
    samples = array("h")
    samples.frombytes(decoded.read_bytes())
    assert _frequency(samples, 4_800, 24_000) == pytest.approx(440, abs=12)
    assert _frequency(samples, 36_000, 55_200) == pytest.approx(660, abs=12)
    report = json.loads((project / "output" / "metadata" / "render_report.json").read_text())
    assert report["revision"] == 1
    assert len(report["history"]) == 2


@pytest.mark.integration_ffmpeg
def test_real_ffmpeg_motion_preview_bounds_cross_track_pcm_work(tmp_path, schema_dir):
    runner = SubprocessRunner()
    tools = MediaToolchain(
        runner,
        {
            "ffmpeg": Path(os.environ["WRLD_FFMPEG_PATH"]),
            "ffprobe": Path(os.environ["WRLD_FFPROBE_PATH"]),
        },
    )
    ffmpeg = tools.resolve("ffmpeg")
    project = tmp_path / "bounded-preview"
    project.mkdir()
    commands = [
        [str(ffmpeg.path), "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=640x360", "-frames:v", "1", "-y", str(project / "background.png")],
    ]
    for index, frequency in enumerate((330, 440, 550), start=1):
        commands.append(
            [str(ffmpeg.path), "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration=5", "-c:a", "pcm_s16le", "-y", str(project / f"{index}.wav")]
        )
    for command in commands:
        result = runner.run(command, timeout_seconds=30)
        assert result.returncode == 0 and not result.timed_out
    effects = VideoEffects(
        audio_bars=AudioBarsSettings(enabled=True),
        track_progress=TrackProgressSettings(enabled=True),
    )
    manifest = {
        "format": "wrld-video-album/2.0",
        "album": {"id": "bounded", "title": "Bounded", "artist": "Test", "channel": "Test"},
        "visual": {"background": "background.png"},
        "tracks": [
            {"id": f"t{index}", "number": index, "title": f"Track {index}", "audio": f"{index}.wav"}
            for index in range(1, 4)
        ],
        "render": {"profile_id": "youtube-1080p30-motion-v1", "effects": effects.to_dict()},
    }
    (project / "video_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    prober = FFprobeAdapter(tools, runner)
    loader = FilesystemVideoProjectLoader(
        schema_dir / "video-manifest-v2.schema.json", prober=prober
    )

    class RecordingRenderer:
        def __init__(self):
            self.inner = StaticVideoExportRenderer(tools, runner)
            self.normalized_bytes = 0

        def render(self, *args, **kwargs):
            rendered = self.inner.render(*args, **kwargs)
            self.normalized_bytes = sum(path.stat().st_size for path in args[4])
            return rendered

    renderer = RecordingRenderer()
    service = MotionPreviews(
        loader,
        renderer,
        FFmpegArtifactVerifier(prober, tools, runner),
        ProcessLocalRenderAdmission(),
        tmp_path / "private-previews",
    )
    loaded = loader.load(project)
    request = resolve_motion_preview_request(
        loaded.manifest,
        ExportTarget("album"),
        MotionPreviewExcerpt(216_000, 144_000),
    )
    with service.prepare(project, request) as lease:
        assert lease.result.duration_seconds == pytest.approx(3.0, abs=0.1)
        assert lease.path.is_file()
        assert renderer.normalized_bytes == 260_160 * 4
        assert renderer.normalized_bytes < 15 * 48_000 * 4
    service.close()


def _frequency(samples, start, end):
    window = samples[start:end]
    crossings = sum(left <= 0 < right for left, right in zip(window, window[1:]))
    return crossings / (len(window) / 48_000)


@pytest.mark.integration_ffmpeg
def test_real_ffmpeg_motion_track_decodes_and_has_no_exposed_edges(tmp_path):
    runner = SubprocessRunner()
    configured = {}
    if os.environ.get("WRLD_FFMPEG_PATH") and os.environ.get("WRLD_FFPROBE_PATH"):
        configured = {
            "ffmpeg": Path(os.environ["WRLD_FFMPEG_PATH"]),
            "ffprobe": Path(os.environ["WRLD_FFPROBE_PATH"]),
        }
    tools = MediaToolchain(runner, configured)
    try:
        ffmpeg = tools.resolve("ffmpeg")
        ffprobe = tools.resolve("ffprobe")
    except Exception as error:
        pytest.skip(f"FFmpeg integration tools unavailable: {error}")
    project = tmp_path / "external-library" / "channel" / "Albums" / "Motion Album"
    project.mkdir(parents=True)
    sources = [
        [
            str(ffmpeg.path), "-v", "error", "-f", "lavfi", "-i",
            "color=c=0x204080:s=640x360,drawbox=x=80:y=60:w=160:h=120:c=white:t=fill",
            "-frames:v", "1", "-y", str(project / "background.png"),
        ],
        [
            str(ffmpeg.path), "-v", "error", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=2", "-c:a", "pcm_s16le", "-y",
            str(project / "track.wav"),
        ],
    ]
    for command in sources:
        generated = runner.run(command, timeout_seconds=30)
        assert generated.returncode == 0 and not generated.timed_out
    effects = VideoEffects(
        pan_zoom=PanZoomSettings(
            enabled=True,
            max_zoom=1.05,
            path="diagonal_down_right",
            cycle_seconds=15,
            return_to_origin=False,
        )
    )
    manifest = {
        "format": "wrld-video-album/2.0",
        "album": {
            "id": "motion-album",
            "title": "Motion Album",
            "artist": "Test",
            "channel": "Test",
        },
        "visual": {"background": "background.png"},
        "tracks": [
            {"id": "motion-t01", "number": 1, "title": "Motion", "audio": "track.wav"}
        ],
        "render": {
            "profile_id": "youtube-1080p30-motion-v1",
            "effects": effects.to_dict(),
        },
    }
    (project / "video_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    arguments = argparse.Namespace(
        album_project=str(project.resolve()),
        target="track",
        track_id="motion-t01",
        profile="youtube-1080p30-motion-v1",
        ffmpeg_path=str(ffmpeg.path),
        ffprobe_path=str(ffprobe.path),
    )

    assert run_video_export(arguments, state_root=tmp_path / "state") == 0

    output = (
        project
        / "output"
        / "profiles"
        / "youtube-1080p30-motion-v1"
        / effects.fingerprint
        / "tracks"
        / "01 - Motion.mp4"
    )
    probe = FFprobeAdapter(tools, runner).probe(output)
    video = next(item for item in probe.streams if item.codec_type == "video")
    audio = next(item for item in probe.streams if item.codec_type == "audio")
    assert (video.width, video.height, video.frame_rate, video.pixel_format) == (
        1920,
        1080,
        30.0,
        "yuv420p",
    )
    assert (video.color_space, video.color_transfer, video.color_primaries) == (
        "bt709",
        "bt709",
        "bt709",
    )
    assert (audio.codec_name, audio.sample_rate, audio.channels) == ("aac", 48000, 2)
    frames = []
    for name, seek in (("first", None), ("last", "-0.1")):
        raw = tmp_path / f"{name}.rgb"
        command = [str(ffmpeg.path), "-v", "error"]
        if seek is not None:
            command.extend(["-sseof", seek])
        command.extend(
            [
                "-i", str(output), "-frames:v", "1", "-f", "rawvideo",
                "-pix_fmt", "rgb24", "-y", str(raw),
            ]
        )
        decoded = runner.run(command, timeout_seconds=60)
        assert decoded.returncode == 0 and not decoded.timed_out
        frames.append(raw.read_bytes())
    assert frames[0] != frames[1]
    expected_size = 1920 * 1080 * 3
    for frame in frames:
        assert len(frame) == expected_size
        for pixel in (0, 1919, 1079 * 1920, 1080 * 1920 - 1):
            assert sum(frame[pixel * 3 : pixel * 3 + 3]) > 30


@pytest.mark.integration_ffmpeg
def test_real_ffmpeg_motion_album_boundary_max_zoom_and_return(tmp_path):
    runner = SubprocessRunner()
    configured = {
        "ffmpeg": Path(os.environ["WRLD_FFMPEG_PATH"]),
        "ffprobe": Path(os.environ["WRLD_FFPROBE_PATH"]),
    }
    tools = MediaToolchain(runner, configured)
    ffmpeg = tools.resolve("ffmpeg")
    ffprobe = tools.resolve("ffprobe")
    project = tmp_path / "library" / "channel" / "Albums" / "Motion Boundary"
    project.mkdir(parents=True)
    source_commands = [
        [
            str(ffmpeg.path), "-v", "error", "-f", "lavfi", "-i",
            "color=c=0x204080:s=640x360,drawbox=x=80:y=60:w=160:h=120:c=white:t=fill",
            "-frames:v", "1", "-y", str(project / "background.png"),
        ],
        [
            str(ffmpeg.path), "-v", "error", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=4", "-c:a", "pcm_s16le", "-y",
            str(project / "first.wav"),
        ],
        [
            str(ffmpeg.path), "-v", "error", "-f", "lavfi", "-i",
            "sine=frequency=660:duration=4", "-c:a", "pcm_s16le", "-y",
            str(project / "second.wav"),
        ],
    ]
    for command in source_commands:
        generated = runner.run(command, timeout_seconds=30)
        assert generated.returncode == 0 and not generated.timed_out
    effects = VideoEffects(
        pan_zoom=PanZoomSettings(
            enabled=True,
            max_zoom=1.05,
            path="diagonal_down_right",
            cycle_seconds=15,
            return_to_origin=True,
            return_duration_seconds=0.5,
        )
    )
    manifest = {
        "format": "wrld-video-album/2.0",
        "album": {
            "id": "motion-boundary",
            "title": "Motion Boundary",
            "artist": "Test",
            "channel": "Test",
        },
        "visual": {"background": "background.png"},
        "tracks": [
            {"id": "motion-t01", "number": 1, "title": "First", "audio": "first.wav"},
            {"id": "motion-t02", "number": 2, "title": "Second", "audio": "second.wav"},
        ],
        "render": {
            "profile_id": "youtube-1080p30-motion-v1",
            "effects": effects.to_dict(),
        },
    }
    (project / "video_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    arguments = argparse.Namespace(
        album_project=str(project.resolve()),
        target="album",
        track_id=None,
        profile="youtube-1080p30-motion-v1",
        ffmpeg_path=str(ffmpeg.path),
        ffprobe_path=str(ffprobe.path),
    )

    assert run_video_export(arguments, state_root=tmp_path / "state") == 0

    output = (
        project
        / "output"
        / "profiles"
        / "youtube-1080p30-motion-v1"
        / effects.fingerprint
        / "album"
        / "Motion Boundary.mp4"
    )
    probe = FFprobeAdapter(tools, runner).probe(output)
    assert probe.duration_seconds == pytest.approx(8.0, abs=0.25)
    samples = {}
    for name, timestamp in (
        ("origin", "0"),
        ("before_boundary", "3.966667"),
        ("after_boundary", "4.033333"),
        ("maximum", "7.5"),
        ("final", "7.966667"),
    ):
        raw = tmp_path / f"{name}.rgb"
        decoded = runner.run(
            [
                str(ffmpeg.path), "-v", "error", "-i", str(output), "-ss", timestamp,
                "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-y", str(raw),
            ],
            timeout_seconds=60,
        )
        assert decoded.returncode == 0 and not decoded.timed_out
        samples[name] = _white_bounds(raw.read_bytes(), 1920, 1080)
    origin = samples["origin"]
    before = samples["before_boundary"]
    after = samples["after_boundary"]
    maximum = samples["maximum"]
    final = samples["final"]
    origin_width = origin[2] - origin[0] + 1
    maximum_width = maximum[2] - maximum[0] + 1
    final_width = final[2] - final[0] + 1
    assert maximum_width / origin_width == pytest.approx(1.05, abs=0.01)
    assert abs(after[0] - before[0]) <= 4
    assert abs(after[1] - before[1]) <= 4
    assert (after[2] - after[0]) > origin_width
    assert final_width / origin_width == pytest.approx(1.0, abs=0.005)
    assert abs(final[0] - origin[0]) <= 2
    assert abs(final[1] - origin[1]) <= 2
    decoded_audio = tmp_path / "motion-audio.pcm"
    decode = runner.run(
        [
            str(ffmpeg.path), "-v", "error", "-xerror", "-i", str(output),
            "-map", "0:a:0", "-ac", "1", "-ar", "48000", "-f", "s16le", "-y",
            str(decoded_audio),
        ],
        timeout_seconds=60,
    )
    assert decode.returncode == 0 and not decode.timed_out
    audio_samples = array("h")
    audio_samples.frombytes(decoded_audio.read_bytes())
    assert _frequency(audio_samples, 48_000, 96_000) == pytest.approx(440, abs=12)
    assert _frequency(audio_samples, 240_000, 288_000) == pytest.approx(660, abs=12)


def _white_bounds(frame, width, height):
    assert len(frame) == width * height * 3
    points = []
    for pixel in range(width * height):
        offset = pixel * 3
        red, green, blue = frame[offset : offset + 3]
        if red > 220 and green > 220 and blue > 220:
            points.append((pixel % width, pixel // width))
    assert points
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


@pytest.mark.integration_ffmpeg
def test_real_ffmpeg_phase3_bars_progress_and_camera_follow_sample_timeline(tmp_path):
    runner = SubprocessRunner()
    configured = {
        "ffmpeg": Path(os.environ["WRLD_FFMPEG_PATH"]),
        "ffprobe": Path(os.environ["WRLD_FFPROBE_PATH"]),
    }
    tools = MediaToolchain(runner, configured)
    ffmpeg = tools.resolve("ffmpeg")
    tools.resolve("ffprobe")
    project = tmp_path / "library" / "channel" / "Albums" / "Phase 3"
    project.mkdir(parents=True)
    sources = [
        [
            str(ffmpeg.path), "-v", "error", "-f", "lavfi", "-i",
            "color=c=0x203050:s=640x360,drawbox=x=80:y=60:w=120:h=90:c=0x20c060:t=fill",
            "-frames:v", "1", "-y", str(project / "background.png"),
        ],
        [
            str(ffmpeg.path), "-v", "error", "-f", "lavfi", "-i",
            "anullsrc=r=48000:cl=stereo:d=1.2", "-c:a", "pcm_s16le", "-y",
            str(project / "silence.wav"),
        ],
        [
            str(ffmpeg.path), "-v", "error", "-f", "lavfi", "-i",
            "sine=frequency=660:sample_rate=48000:duration=1.2", "-filter:a", "volume=0.8",
            "-ac", "2", "-c:a", "pcm_s16le", "-y", str(project / "tone.wav"),
        ],
    ]
    for command in sources:
        generated = runner.run(command, timeout_seconds=30)
        assert generated.returncode == 0 and not generated.timed_out
    effects = VideoEffects(
        pan_zoom=PanZoomSettings(
            enabled=True,
            max_zoom=1.05,
            cycle_seconds=15,
            return_to_origin=False,
        ),
        audio_bars=AudioBarsSettings(
            enabled=True,
            bar_count=8,
            opacity=1,
            rms_window_samples=480,
            attack_ms=0,
            release_ms=0,
        ),
        track_progress=TrackProgressSettings(
            enabled=True,
            placement="top",
            opacity=1,
            thickness_px=8,
        ),
    )
    manifest = {
        "format": "wrld-video-album/2.0",
        "album": {"id": "phase-3", "title": "Phase 3", "artist": "Test", "channel": "Test"},
        "visual": {"background": "background.png"},
        "tracks": [
            {"id": "silent", "number": 1, "title": "Silence", "audio": "silence.wav"},
            {"id": "tone", "number": 2, "title": "Tone", "audio": "tone.wav"},
        ],
        "render": {
            "profile_id": "youtube-1080p30-motion-v1",
            "effects": effects.to_dict(),
        },
    }
    (project / "video_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    arguments = argparse.Namespace(
        album_project=str(project.resolve()),
        target="album",
        track_id=None,
        profile="youtube-1080p30-motion-v1",
        ffmpeg_path=str(ffmpeg.path),
        ffprobe_path=str(configured["ffprobe"]),
    )

    assert run_video_export(arguments, state_root=tmp_path / "state") == 0

    output = (
        project / "output" / "profiles" / "youtube-1080p30-motion-v1"
        / effects.fingerprint / "album" / "Phase 3.mp4"
    )
    probe = FFprobeAdapter(tools, runner).probe(output)
    video = next(item for item in probe.streams if item.codec_type == "video")
    audio = next(item for item in probe.streams if item.codec_type == "audio")
    assert (video.width, video.height, video.frame_rate, video.pixel_format) == (
        1920, 1080, 30.0, "yuv420p"
    )
    assert (video.color_space, video.color_transfer, video.color_primaries) == (
        "bt709", "bt709", "bt709"
    )
    assert (audio.codec_name, audio.sample_rate, audio.channels) == ("aac", 48000, 2)
    frames = {}
    for name, timestamp in (
        ("silence", "0.600000"),
        ("before_boundary", "1.166667"),
        ("after_boundary", "1.233333"),
        ("tone", "1.800000"),
    ):
        raw = tmp_path / f"phase3-{name}.rgb"
        decoded = runner.run(
            [
                str(ffmpeg.path), "-v", "error", "-i", str(output), "-ss", timestamp,
                "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-y", str(raw),
            ],
            timeout_seconds=60,
        )
        assert decoded.returncode == 0 and not decoded.timed_out
        frames[name] = raw.read_bytes()
    silence_bounds = _white_region_bounds(frames["silence"], 1920, 1080, 800, 1016)
    tone_bounds = _white_region_bounds(frames["tone"], 1920, 1080, 800, 1016)
    assert silence_bounds[3] - silence_bounds[1] + 1 <= 4
    assert tone_bounds[3] - tone_bounds[1] + 1 >= 80
    before_progress = _white_row_width(frames["before_boundary"], 1920, 64, 71)
    after_progress = _white_row_width(frames["after_boundary"], 1920, 64, 71)
    assert before_progress > 1600
    assert after_progress < 100
    assert tone_bounds[0] == silence_bounds[0]
    assert tone_bounds[2] == silence_bounds[2]
    assert not any((project / "output" / ".wrld-staging").rglob("*.sendcmd"))


def _white_region_bounds(frame, width, height, y_start, y_end):
    points = []
    for y in range(y_start, min(height, y_end)):
        for x in range(width):
            offset = (y * width + x) * 3
            red, green, blue = frame[offset : offset + 3]
            if red > 220 and green > 220 and blue > 220:
                points.append((x, y))
    assert points
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def _white_row_width(frame, width, y_start, y_end):
    xs = set()
    for y in range(y_start, y_end + 1):
        for x in range(width):
            offset = (y * width + x) * 3
            red, green, blue = frame[offset : offset + 3]
            if red > 220 and green > 220 and blue > 220:
                xs.add(x)
    return 0 if not xs else max(xs) - min(xs) + 1


@pytest.mark.integration_ffmpeg
@pytest.mark.parametrize("effect", ["bars", "line", "segmented"])
def test_real_ffmpeg_phase3_individual_overlays_decode_visibly(tmp_path, effect):
    runner = SubprocessRunner()
    tools = MediaToolchain(
        runner,
        {
            "ffmpeg": Path(os.environ["WRLD_FFMPEG_PATH"]),
            "ffprobe": Path(os.environ["WRLD_FFPROBE_PATH"]),
        },
    )
    ffmpeg = tools.resolve("ffmpeg")
    tools.resolve("ffprobe")
    background = tmp_path / "background.png"
    audio = tmp_path / "tone.wav"
    for command in (
        [
            str(ffmpeg.path), "-v", "error", "-f", "lavfi", "-i",
            "color=c=0x203050:s=640x360", "-frames:v", "1", "-y", str(background),
        ],
        [
            str(ffmpeg.path), "-v", "error", "-f", "lavfi", "-i",
            "sine=frequency=440:sample_rate=48000:duration=1", "-ac", "2",
            "-c:a", "pcm_s16le", "-y", str(audio),
        ],
    ):
        generated = runner.run(command, timeout_seconds=30)
        assert generated.returncode == 0 and not generated.timed_out
    effects = VideoEffects(
        audio_bars=AudioBarsSettings(
            enabled=effect == "bars",
            bar_count=8,
            opacity=1,
            rms_window_samples=480,
            attack_ms=0,
            release_ms=0,
        ),
        track_progress=TrackProgressSettings(
            enabled=effect != "bars",
            style="segmented" if effect == "segmented" else "line",
            placement="top",
            opacity=1,
            thickness_px=8,
            segment_count=20,
        ),
    )
    document = {
        "format": "wrld-video-album/2.0",
        "album": {"id": "individual", "title": "Individual", "artist": "Test", "channel": "Test"},
        "visual": {"background": "background.png"},
        "tracks": [{"id": "tone", "number": 1, "title": "Tone", "audio": "tone.wav"}],
        "render": {
            "profile_id": "youtube-1080p30-motion-v1",
            "effects": effects.to_dict(),
        },
    }
    manifest = parse_motion_manifest(document)
    plan = create_motion_plan(
        manifest, MotionVideoExportRequest(ExportTarget("track", "tone"), effects)
    )
    output = tmp_path / f"{effect}.mp4"
    StaticVideoExportRenderer(tools, runner).render(
        plan,
        (audio,),
        background,
        output,
        (tmp_path / f"{effect}.pcm",),
        tmp_path / f"{effect}-combined.pcm",
        "a" * 64,
        effect_control_path=tmp_path / f"{effect}.sendcmd",
    )
    raw = tmp_path / f"{effect}.rgb"
    decoded = runner.run(
        [
            str(ffmpeg.path), "-v", "error", "-i", str(output), "-ss", "0.5",
            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-y", str(raw),
        ],
        timeout_seconds=60,
    )
    assert decoded.returncode == 0 and not decoded.timed_out
    frame = raw.read_bytes()
    if effect == "bars":
        bounds = _white_region_bounds(frame, 1920, 1080, 800, 1016)
        assert bounds[3] - bounds[1] + 1 >= 80
    else:
        assert _white_row_width(frame, 1920, 64, 71) > 800
        if effect == "segmented":
            assert _white_runs(frame, 1920, 67) == 10
    full_decode = runner.run(
        [str(ffmpeg.path), "-v", "error", "-xerror", "-i", str(output), "-f", "null", "NUL"],
        timeout_seconds=60,
    )
    assert full_decode.returncode == 0 and not full_decode.timed_out


def _white_runs(frame, width, y):
    active = []
    for x in range(width):
        offset = (y * width + x) * 3
        red, green, blue = frame[offset : offset + 3]
        active.append(red > 220 and green > 220 and blue > 220)
    return sum(value and (index == 0 or not active[index - 1]) for index, value in enumerate(active))
