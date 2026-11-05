from __future__ import annotations

import hashlib
import os
import shutil
import time
import uuid
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from wrld_video_studio.application.creation_render import CreationRenderService
from wrld_video_studio.infrastructure.artifact_verifier import FFmpegArtifactVerifier
from wrld_video_studio.infrastructure.ffprobe_adapter import FFprobeAdapter
from wrld_video_studio.infrastructure.media_tools import MediaToolchain
from wrld_video_studio.infrastructure.process_runner import SubprocessRunner
from wrld_video_studio.infrastructure.video_export_renderer import StaticVideoExportRenderer


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.integration_ffmpeg
def test_creation_render_service_produces_verified_album_single_and_portrait_short(tmp_path):
    if not os.environ.get("WRLD_FFMPEG_PATH") or not os.environ.get("WRLD_FFPROBE_PATH"):
        pytest.skip("WRLD_FFMPEG_PATH and WRLD_FFPROBE_PATH are required")
    project = tmp_path / "project"; project.mkdir()
    audio = project / "audio.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(2); stream.setsampwidth(2); stream.setframerate(48_000); stream.writeframes(b"\0\0\0\0" * 48_000)
    image = project / "cover.png"
    repository = Path(__file__).resolve().parents[3]
    shutil.copyfile(repository / "docs" / "ui" / "import.png", image)
    audio_sha, image_sha = _sha(audio), _sha(image)

    def visual(aspect: str):
        return {
            "canvas": {"aspect_ratio": aspect},
            "background_image": {"asset_id": "image-1", "expected_sha256": image_sha},
            "geometry": {"fit_mode": "cover", "focal_x": 0.5, "focal_y": 0.5},
            "camera": {"mode": "bounded", "max_zoom": 1.03},
            "visualizer": {"enabled": True, "bar_count": 16, "opacity": 0.6},
            "progress": {"enabled": True}, "color_treatment": {"mode": "none"},
        }

    state = {
        "contract_version": "wrld-creation-state/4.0", "revision": 1, "state_digest": "a" * 64,
        "albums": [{"album_plan_id": "album-1", "label": "Album", "status": "active", "assignments": [{"assignment_id": "assignment-1", "asset_id": "audio-1", "expected_sha256": audio_sha, "duplicate_acknowledged": False}], "visual_configuration": visual("16:9"), "source_visual_template_id": None}],
        "singles": [{"single_id": "single-1", "label": "Single", "status": "active", "asset_id": "audio-1", "expected_sha256": audio_sha, "visual_configuration": visual("16:9")}],
        "shorts": [{"short_id": "short-1", "label": "Short", "status": "active", "asset_id": "audio-1", "expected_sha256": audio_sha, "start_sample": 0, "sample_count": 48_000, "visual_configuration": visual("9:16")}],
    }
    inventory = {"assets": [
        {"asset_id": "audio-1", "relative_path": "audio.wav", "kind": "audio", "presence": "present", "sha256": audio_sha, "probe_status": "ok", "media": {"duration_seconds": 1.0}},
        {"asset_id": "image-1", "relative_path": "cover.png", "kind": "image", "presence": "present", "sha256": image_sha, "probe_status": "ok", "capabilities": {"inspection": {"status": "supported"}}},
    ]}
    runtime = SimpleNamespace(
        catalogs=SimpleNamespace(resolve=lambda _project_id: (object(), project)),
        creation=SimpleNamespace(get=lambda _project_id: state),
        inventories=SimpleNamespace(read=lambda _project_id: inventory),
        preferences=SimpleNamespace(get=lambda _project_id: {"excluded_asset_ids": []}),
    )
    runner = SubprocessRunner()
    toolchain = MediaToolchain(runner, {"ffmpeg": Path(os.environ["WRLD_FFMPEG_PATH"]), "ffprobe": Path(os.environ["WRLD_FFPROBE_PATH"])})
    prober = FFprobeAdapter(toolchain, runner, count_frames=False)
    service = CreationRenderService(runtime, tmp_path / "state", toolchain, prober, StaticVideoExportRenderer(toolchain, runner), FFmpegArtifactVerifier(prober, toolchain, runner))
    project_id = "00000000-0000-4000-8000-000000000001"
    profile = {"album": "wrld-album-1080p30-v1", "single": "wrld-single-1080p30-v1", "short": "wrld-short-1080x1920p30-v1"}
    submitted = []
    try:
        for kind in ("album", "single", "short"):
            identity = f"{kind}-1"
            base = {"contract_version": "wrld-creation-render-request/1.0", "target": {"kind": kind, "composition_id": identity}, "expected_creation_revision": 1, "expected_creation_state_digest": "a" * 64, "profile_id": profile[kind], "output_action": "reuse_verified_or_fail", "replacement": None}
            preflight = service.preflight(project_id, {**base, "mode": "preflight", "expected_plan_fingerprint": None, "submission_id": None})
            assert preflight["status"] == "ready"
            job, created = service.submit(project_id, {**base, "mode": "submit", "expected_plan_fingerprint": preflight["plan"]["plan_fingerprint"], "submission_id": str(uuid.uuid4())})
            assert created is True; submitted.append(job["job_id"])
        deadline = time.monotonic() + 240
        maximum_running = 0
        while time.monotonic() < deadline:
            jobs = [service.get_job(project_id, job_id) for job_id in submitted]
            maximum_running = max(maximum_running, sum(job["state"] in {"running", "cancel_requested"} for job in jobs))
            if all(job["state"] in {"succeeded", "failed", "cancelled"} for job in jobs): break
            time.sleep(0.2)
        assert maximum_running == 1
        for job_id in submitted:
            job = service.get_job(project_id, job_id)
            assert job["state"] == "succeeded", job.get("diagnostic")
            result = service.result(project_id, job_id)
            assert len(result["artifacts"]) == 1
            artifact = result["artifacts"][0]
            assert service.artifact_path(project_id, artifact["artifact_id"]).is_file()
        assert service.result(project_id, submitted[-1])["artifacts"][0]["media"]["width"] == 1080
        assert service.result(project_id, submitted[-1])["artifacts"][0]["media"]["height"] == 1920

        # Exercise additive staged recovery with a disposable copy of the real,
        # already encoded Album. The historical failed result remains intact.
        album_record = service._load_record(submitted[0])
        album_artifact = service.result(project_id, submitted[0])["artifacts"][0]
        album_final = service.artifact_path(project_id, album_artifact["artifact_id"])
        failed_job, failed_attempt = str(uuid.uuid4()), str(uuid.uuid4())
        staged = service._recovery_stage_path(failed_job, failed_attempt); staged.parent.mkdir(parents=True)
        shutil.copyfile(album_final, staged)
        artifact_document = service._artifact_document(project_id)
        artifact_document["artifacts"] = [item for item in artifact_document["artifacts"] if item["artifact_id"] != album_artifact["artifact_id"]]
        artifact_document["revision"] += 1; service._atomic(service._artifact_file(project_id), artifact_document)
        album_final.unlink()
        now = "2026-11-04T12:00:00Z"
        failed = service._job_document(project_id, album_record["request"], album_record["plan"], failed_job, failed_attempt, now)
        failed.update({"state": "failed", "phase": "probing_output", "started_at": now, "finished_at": now, "updated_at": now, "result_available": True})
        failed_record = {"job": failed, "request": album_record["request"], "plan": album_record["plan"], "result": None, "publication": {"state": "none", "artifact": None}}
        failed_record["result"] = service._terminal_result(failed_record, "failed", [service._diagnostic("RENDER_FAILED", "probe timeout", failed["target"], {})])
        service._save_record(failed_job, failed_record)
        recovery_base = {"contract_version": "wrld-creation-render-recovery-request/1.0", "target": failed["target"], "failed_job_id": failed_job, "failed_attempt_id": failed_attempt, "expected_creation_revision": 1, "expected_creation_state_digest": "a" * 64, "profile_id": "wrld-album-1080p30-v1", "output_action": "reuse_verified_or_fail", "replacement": None}
        recovery_preflight = service.recovery_preflight(project_id, {**recovery_base, "mode": "preflight", "expected_recovery_fingerprint": None, "submission_id": None})
        assert recovery_preflight["status"] == "ready"
        recovery_job, created = service.submit_recovery(project_id, {**recovery_base, "mode": "submit", "expected_recovery_fingerprint": recovery_preflight["recovery_fingerprint"], "submission_id": str(uuid.uuid4())})
        assert created is True
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            recovered = service.get_job(project_id, recovery_job["job_id"])
            if recovered["state"] in {"succeeded", "failed", "cancelled"}: break
            time.sleep(0.1)
        assert recovered["state"] == "succeeded", recovered.get("diagnostic")
        assert recovered["retry_of_attempt_id"] == failed_attempt
        assert service.get_job(project_id, failed_job)["state"] == "failed"
        assert service.result(project_id, recovery_job["job_id"])["artifacts"][0]["sha256"] == album_artifact["sha256"]
    finally:
        service.close()
