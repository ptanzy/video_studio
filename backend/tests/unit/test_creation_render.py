from __future__ import annotations

import pytest
from types import SimpleNamespace
import hashlib
import json
import threading
import time

from wrld_video_studio.application import creation_render as creation_render_module
from wrld_video_studio.application.creation_render import CreationRenderService
from wrld_video_studio.domain.creation_render import CreationRenderExcerpt, camera_direction, effects_from_visual_configuration
from wrld_video_studio.domain.media_errors import MediaInfrastructureError


class RecoveryProber:
    def __init__(self):
        self.fingerprint = ""
        self.fail = False

    def probe(self, _path):
        if self.fail: raise MediaInfrastructureError("PROBE_FAILED", "partial")
        return SimpleNamespace(
            duration_seconds=20.0,
            format_tags={"comment": f"wrld_request:{self.fingerprint}"},
            streams=(
                SimpleNamespace(codec_type="video", width=1920, height=1080),
                SimpleNamespace(codec_type="audio"),
            ),
        )


class RecoveryVerifier:
    def __init__(self, prober): self.prober, self.calls = prober, []
    def verify(self, path, _expected, cancel_event=None, heartbeat=None, phase_callback=None):
        self.calls.append(path)
        if phase_callback: phase_callback("probing_output")
        if heartbeat: heartbeat()
        if cancel_event is not None and cancel_event.is_set(): raise MediaInfrastructureError("PROCESS_CANCELLED", "cancelled")
        if phase_callback: phase_callback("decoding_output")
        return self.prober.probe(path)


class EncodingForbidden:
    def render(self, *_args, **_kwargs): raise AssertionError("staged recovery must not encode")


class BlockingRecoveryVerifier:
    def __init__(self, prober): self.prober, self.started = prober, threading.Event()
    def verify(self, path, _expected, cancel_event=None, heartbeat=None, phase_callback=None):
        if phase_callback: phase_callback("decoding_output")
        if heartbeat: heartbeat()
        self.started.set()
        while cancel_event is not None and not cancel_event.is_set():
            if heartbeat: heartbeat()
            time.sleep(0.01)
        raise MediaInfrastructureError("PROCESS_CANCELLED", "cancelled")


class FailingRecoveryVerifier:
    def verify(self, _path, _expected, **_kwargs):
        raise MediaInfrastructureError("OUTPUT_DECODE_FAILED", "complete decode failed")


@pytest.mark.parametrize(
    ("composition_id", "expected"),
    [
        ("test-3", "horizontal"),
        ("test-0", "vertical"),
        ("test-2", "diagonal_down_right"),
        ("test-6", "diagonal_up_right"),
    ],
)
def test_camera_direction_uses_first_identity_digest_byte_modulo_four(composition_id, expected):
    assert camera_direction("short", composition_id) == expected
    assert camera_direction("short", composition_id) == expected


def test_camera_direction_rejects_missing_or_unknown_stable_identity():
    with pytest.raises(ValueError):
        camera_direction("video", "test-1")
    with pytest.raises(ValueError):
        camera_direction("album", "")


def test_creation_render_excerpt_accepts_full_length_outputs_beyond_preview_limits():
    assert CreationRenderExcerpt(0, 48_000 * 360).sample_count == 48_000 * 360


def test_atomic_job_persistence_retries_transient_windows_sharing_violation(tmp_path, monkeypatch):
    destination = tmp_path / "jobs" / "job.json"
    original_replace = creation_render_module.os.replace
    attempts = 0

    def intermittently_denied(source, target):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError(5, "Access is denied")
        original_replace(source, target)

    monkeypatch.setattr(creation_render_module.os, "replace", intermittently_denied)

    CreationRenderService._atomic(destination, {"state": "running"})

    assert attempts == 3
    assert json.loads(destination.read_text(encoding="utf-8")) == {"state": "running"}
    assert list(destination.parent.glob("*.tmp")) == []


def test_durable_json_reads_retry_transient_windows_sharing_violation(tmp_path, monkeypatch):
    path = tmp_path / "job.json"; path.write_text('{"state":"running"}', encoding="utf-8")
    original_read_text = creation_render_module.Path.read_text
    attempts = 0

    def intermittently_denied(self, *args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError(5, "Access is denied")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(creation_render_module.Path, "read_text", intermittently_denied)

    assert CreationRenderService._read_json(path) == {"state": "running"}
    assert attempts == 3


def test_unexpected_render_failure_details_redact_server_paths():
    details = CreationRenderService._unexpected_error_details(
        PermissionError(5, r"Access is denied: 'C:\private\state\job.json'")
    )

    assert "C:\\private" not in details["reason"]
    assert "<path>" in details["reason"]


def test_visual_configuration_maps_to_approved_landscape_effects():
    visual = {
        "canvas": {"aspect_ratio": "16:9"},
        "camera": {"mode": "bounded", "max_zoom": 1.04},
        "visualizer": {"enabled": True, "bar_count": 24, "opacity": 0.65},
        "progress": {"enabled": True},
    }
    effects = effects_from_visual_configuration({"kind": "album", "composition_id": "album-1"}, visual)
    assert effects.pan_zoom.enabled is True
    assert effects.pan_zoom.path == camera_direction("album", "album-1")
    assert effects.pan_zoom.cycle_seconds == 180.0
    assert effects.pan_zoom.return_duration_seconds == 5.0
    assert effects.audio_bars.zone_width_px == 640
    assert effects.audio_bars.zone_height_px == 180
    assert effects.track_progress.enabled is True


def test_visual_configuration_preserves_inactive_zoom_and_maps_portrait_zone():
    visual = {
        "canvas": {"aspect_ratio": "9:16"},
        "camera": {"mode": "static", "max_zoom": 1.03},
        "visualizer": {"enabled": False, "bar_count": 32, "opacity": 0.7},
        "progress": {"enabled": False},
    }
    effects = effects_from_visual_configuration({"kind": "short", "composition_id": "short-1"}, visual)
    assert effects.pan_zoom.enabled is False
    assert effects.pan_zoom.max_zoom == 1.03
    assert effects.audio_bars.zone_width_px == 720
    assert effects.audio_bars.zone_height_px == 240
    assert effects.track_progress.enabled is False


def _render_service(tmp_path, verifier=None):
    audio_sha, image_sha = "1" * 64, "2" * 64
    visual = {
        "canvas": {"aspect_ratio": "16:9"},
        "background_image": {"asset_id": "image-1", "expected_sha256": image_sha},
        "geometry": {"fit_mode": "contain", "focal_x": 0.5, "focal_y": 0.5},
        "camera": {"mode": "bounded", "max_zoom": 1.04},
        "visualizer": {"enabled": True, "bar_count": 24, "opacity": 0.65},
        "progress": {"enabled": True}, "color_treatment": {"mode": "none"},
    }
    state = {
        "contract_version": "wrld-creation-state/4.0", "revision": 3, "state_digest": "3" * 64,
        "albums": [{"album_plan_id": "album-1", "label": "Album", "status": "active", "assignments": [
            {"assignment_id": "assignment-1", "asset_id": "audio-1", "expected_sha256": audio_sha, "duplicate_acknowledged": False},
            {"assignment_id": "assignment-2", "asset_id": "audio-1", "expected_sha256": audio_sha, "duplicate_acknowledged": True},
        ], "visual_configuration": visual, "source_visual_template_id": None}],
        "singles": [], "shorts": [],
    }
    inventory = {"assets": [
        {"asset_id": "audio-1", "relative_path": "audio.wav", "kind": "audio", "presence": "present", "sha256": audio_sha, "probe_status": "ok", "media": {"duration_seconds": 10.0}},
        {"asset_id": "image-1", "relative_path": "cover.png", "kind": "image", "presence": "present", "sha256": image_sha, "probe_status": "ok", "capabilities": {"inspection": {"status": "supported"}}},
    ]}
    project = tmp_path / "project"; project.mkdir()
    runtime = SimpleNamespace(
        catalogs=SimpleNamespace(resolve=lambda _project_id: (object(), project)),
        creation=SimpleNamespace(get=lambda _project_id: state),
        inventories=SimpleNamespace(read=lambda _project_id: inventory),
        preferences=SimpleNamespace(get=lambda _project_id: {"excluded_asset_ids": []}),
    )
    toolchain = SimpleNamespace(resolve=lambda name: SimpleNamespace(version=f"{name} 9.0", path=tmp_path / name))
    prober = RecoveryProber()
    return CreationRenderService(runtime, tmp_path / "state", toolchain, prober, EncodingForbidden(), verifier or RecoveryVerifier(prober)), state


def _preflight_request(state):
    return {
        "contract_version": "wrld-creation-render-request/1.0", "mode": "preflight",
        "target": {"kind": "album", "composition_id": "album-1"},
        "expected_creation_revision": state["revision"], "expected_creation_state_digest": state["state_digest"],
        "profile_id": "wrld-album-1080p30-v1", "expected_plan_fingerprint": None,
        "submission_id": None, "output_action": "reuse_verified_or_fail", "replacement": None,
    }


def _failed_recovery(service, state):
    project_id = "00000000-0000-4000-8000-000000000001"
    plan = service.preflight(project_id, _preflight_request(state))["plan"]
    service.prober.fingerprint = plan["plan_fingerprint"]
    job_id = "11111111-1111-4111-8111-111111111111"
    attempt_id = "22222222-2222-4222-8222-222222222222"
    request = {**_preflight_request(state), "mode": "submit", "expected_plan_fingerprint": plan["plan_fingerprint"], "submission_id": "33333333-3333-4333-8333-333333333333"}
    now = "2026-11-04T12:00:00Z"
    job = service._job_document(project_id, request, plan, job_id, attempt_id, now)
    job.update({"state": "failed", "phase": "probing_output", "started_at": now, "finished_at": now, "updated_at": now, "result_available": True})
    record = {"job": job, "request": request, "plan": plan, "result": None, "publication": {"state": "none", "artifact": None}}
    record["result"] = service._terminal_result(record, "failed", [service._diagnostic("RENDER_FAILED", "probe timeout", job["target"], {})])
    service._save_record(job_id, record)
    staged = service._recovery_stage_path(job_id, attempt_id); staged.parent.mkdir(parents=True); staged.write_bytes(b"complete staged video")
    return project_id, job_id, attempt_id, plan, staged


def _recovery_request(state, job_id, attempt_id, plan, *, mode="preflight", fingerprint=None, submission=None):
    return {"contract_version": "wrld-creation-render-recovery-request/1.0", "mode": mode, "target": plan["target"], "failed_job_id": job_id, "failed_attempt_id": attempt_id, "expected_creation_revision": state["revision"], "expected_creation_state_digest": state["state_digest"], "profile_id": plan["profile"]["profile_id"], "expected_recovery_fingerprint": fingerprint, "submission_id": submission, "output_action": "reuse_verified_or_fail", "replacement": None}


def _wait_terminal(service, project_id, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = service.get_job(project_id, job_id)
        if job["state"] in {"succeeded", "failed", "cancelled"}: return job
        time.sleep(0.01)
    raise AssertionError("job did not become terminal")


def test_preflight_preserves_album_assignment_order_and_duplicate_identities(tmp_path):
    service, state = _render_service(tmp_path)
    try:
        result = service.preflight("00000000-0000-4000-8000-000000000001", _preflight_request(state))
    finally:
        service.close()
    assert result["status"] == "ready"
    plan = result["plan"]
    assert [source["assignment_id"] for source in plan["audio_sources"]] == ["assignment-1", "assignment-2"]
    assert [entry["output_start_sample"] for entry in plan["timeline"]["entries"]] == [0, 480_000]
    assert plan["timeline"]["total_samples"] == 960_000
    assert plan["output"]["relative_path"] == "output/album/album-1.mp4"


def test_unrelated_creation_changes_do_not_change_reconstructed_plan_fingerprint(tmp_path):
    service, state = _render_service(tmp_path)
    try:
        first = service.preflight("00000000-0000-4000-8000-000000000001", _preflight_request(state))["plan"]
        state["revision"] = 4; state["state_digest"] = "4" * 64
        state["singles"].append({"single_id": "unrelated"})
        request = _preflight_request(state)
        second = service.preflight("00000000-0000-4000-8000-000000000001", request)["plan"]
    finally:
        service.close()
    assert first["plan_fingerprint"] == second["plan_fingerprint"]
    assert first["creation_basis"]["revision"] != second["creation_basis"]["revision"]


def test_preflight_requires_exact_compare_and_swap_receipt_for_replacement(tmp_path):
    service, state = _render_service(tmp_path)
    project_id = "00000000-0000-4000-8000-000000000001"
    output = tmp_path / "project" / "output" / "album" / "album-1.mp4"
    output.parent.mkdir(parents=True); output.write_bytes(b"prior verified output")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    artifact_id = "artifact-" + "9" * 64
    service._publish_artifact(project_id, {"artifact_id": artifact_id, "relative_path": "output/album/album-1.mp4", "sha256": digest, "plan_fingerprint": "8" * 64, "target": {"kind": "album", "composition_id": "album-1"}})
    try:
        initial = service.preflight(project_id, _preflight_request(state))
        assert initial["status"] == "replacement_required"
        authorized_request = {**_preflight_request(state), "output_action": "replace_verified", "replacement": {"artifact_id": artifact_id, "expected_sha256": digest, "expected_report_revision": 1}}
        assert service.preflight(project_id, authorized_request)["status"] == "ready"
        authorized_request["replacement"] = {**authorized_request["replacement"], "expected_report_revision": 0}
        stale = service.preflight(project_id, authorized_request)
    finally:
        service.close()
    assert stale["status"] == "blocked"
    assert stale["diagnostics"][0]["code"] == "OUTPUT_REPLACEMENT_STALE"


def test_staged_recovery_creates_linked_attempt_skips_encoding_and_is_idempotent(tmp_path):
    service, state = _render_service(tmp_path)
    project_id, failed_job, failed_attempt, plan, staged = _failed_recovery(service, state)
    try:
        preflight = service.recovery_preflight(project_id, _recovery_request(state, failed_job, failed_attempt, plan))
        assert preflight["status"] == "ready"
        request = _recovery_request(state, failed_job, failed_attempt, plan, mode="submit", fingerprint=preflight["recovery_fingerprint"], submission="44444444-4444-4444-8444-444444444444")
        job, created = service.submit_recovery(project_id, request)
        terminal = _wait_terminal(service, project_id, job["job_id"])
        repeated, repeated_created = service.submit_recovery(project_id, request)
        historical = service.get_job(project_id, failed_job)
    finally:
        service.close()
    assert created is True and repeated_created is False and repeated["job_id"] == job["job_id"]
    assert terminal["state"] == "succeeded" and terminal["retry_of_attempt_id"] == failed_attempt
    assert historical["state"] == "failed"
    assert not staged.exists()
    assert service.runtime.catalogs.resolve(project_id)[1].joinpath(plan["output"]["relative_path"]).is_file()


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("attempt", "RECOVERY_ATTEMPT_MISMATCH"),
        ("job", "RECOVERY_JOB_NOT_FOUND"),
        ("project", "RECOVERY_PROJECT_MISMATCH"),
        ("plan", "RECOVERY_PLAN_STALE"),
        ("partial", "RECOVERY_STAGING_INCOMPLETE"),
    ],
)
def test_staged_recovery_rejects_wrong_ownership_stale_plan_and_partial_media(tmp_path, mutation, code):
    service, state = _render_service(tmp_path)
    project_id, failed_job, failed_attempt, plan, _staged = _failed_recovery(service, state)
    request = _recovery_request(state, failed_job, failed_attempt, plan)
    if mutation == "attempt": request["failed_attempt_id"] = "99999999-9999-4999-8999-999999999999"
    elif mutation == "job": request["failed_job_id"] = "99999999-9999-4999-8999-999999999999"
    elif mutation == "project": project_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    elif mutation == "plan": state["albums"][0]["visual_configuration"]["camera"]["max_zoom"] = 1.03
    else: service.prober.fail = True
    try: result = service.recovery_preflight(project_id, request)
    finally: service.close()
    assert result["status"] == "blocked" and result["diagnostics"][0]["code"] == code


def test_staged_recovery_receipt_detects_changed_bytes(tmp_path):
    service, state = _render_service(tmp_path)
    project_id, failed_job, failed_attempt, plan, staged = _failed_recovery(service, state)
    preflight = service.recovery_preflight(project_id, _recovery_request(state, failed_job, failed_attempt, plan))
    staged.write_bytes(b"different complete video")
    request = _recovery_request(state, failed_job, failed_attempt, plan, mode="submit", fingerprint=preflight["recovery_fingerprint"], submission="55555555-5555-4555-8555-555555555555")
    try:
        with pytest.raises(Exception) as caught: service.submit_recovery(project_id, request)
    finally: service.close()
    assert getattr(caught.value, "code", None) == "RECOVERY_RECEIPT_STALE"


def test_render_preflight_blocks_when_conservative_disk_estimate_exceeds_free_space(tmp_path, monkeypatch):
    service, state = _render_service(tmp_path)
    monkeypatch.setattr(creation_render_module.shutil, "disk_usage", lambda _path: SimpleNamespace(free=1))
    try: result = service.preflight("00000000-0000-4000-8000-000000000001", _preflight_request(state))
    finally: service.close()
    assert result["status"] == "blocked"
    assert result["diagnostics"][0]["code"] == "RENDER_FAILED"
    assert result["diagnostics"][0]["details"]["estimate_basis"] == "source_snapshots_plus_three_pcm_equivalents"


def test_recovery_preflight_blocks_when_record_reserve_is_unavailable(tmp_path, monkeypatch):
    service, state = _render_service(tmp_path)
    project_id, failed_job, failed_attempt, plan, _staged = _failed_recovery(service, state)
    monkeypatch.setattr(creation_render_module.shutil, "disk_usage", lambda _path: SimpleNamespace(free=creation_render_module.RECOVERY_RECORD_RESERVE_BYTES - 1))
    try: result = service.recovery_preflight(project_id, _recovery_request(state, failed_job, failed_attempt, plan))
    finally: service.close()
    assert result["status"] == "blocked"
    assert result["diagnostics"][0]["code"] == "RECOVERY_DISK_SPACE_INSUFFICIENT"


def test_success_cleanup_retains_unledgered_staging_files(tmp_path):
    service, state = _render_service(tmp_path)
    project_id, job_id, _attempt, _plan, _staged = _failed_recovery(service, state)
    record = service._load_record(job_id)
    owned = service.root / "staging" / job_id / record["job"]["attempt_id"]
    unknown = owned / "unledgered-intermediate.bin"; unknown.write_bytes(b"retain")
    service._cleanup_success_staging(record)
    service.close()
    assert unknown.read_bytes() == b"retain"


def test_render_preflight_does_not_read_or_modify_wu5_metadata(tmp_path):
    service, state = _render_service(tmp_path)
    project_id = "00000000-0000-4000-8000-000000000001"
    project_root = service.runtime.catalogs.resolve(project_id)[1]
    metadata = project_root / "youtube_metadata.json"; metadata.write_bytes(b"opaque WU5 state")
    before = metadata.read_bytes()
    try: result = service.preflight(project_id, _preflight_request(state))
    finally: service.close()
    assert result["status"] == "ready"
    assert metadata.read_bytes() == before


def test_committed_publication_receipt_reconciles_without_file_only_inference(tmp_path):
    service, state = _render_service(tmp_path)
    project_id, job_id, _attempt, plan, staged = _failed_recovery(service, state)
    record = service._load_record(job_id)
    final = service.runtime.catalogs.resolve(project_id)[1] / plan["output"]["relative_path"]
    final.parent.mkdir(parents=True); staged.replace(final)
    digest = hashlib.sha256(final.read_bytes()).hexdigest()
    artifact = {"artifact_id": "artifact-" + "9" * 64, "relative_path": plan["output"]["relative_path"], "sha256": digest, "plan_fingerprint": plan["plan_fingerprint"]}
    service._publish_artifact(project_id, artifact)
    record["publication"] = {"state": "verified", "artifact": artifact}; service._save_record(job_id, record)
    try:
        assert service._committed_artifact(record)["artifact_id"] == artifact["artifact_id"]
        record["publication"]["artifact"] = {**artifact, "artifact_id": "artifact-" + "8" * 64}
        assert service._committed_artifact(record) is None
    finally: service.close()


def test_recovery_decode_heartbeat_and_cancellation_preserve_failed_staging(tmp_path):
    service, state = _render_service(tmp_path)
    blocker = BlockingRecoveryVerifier(service.prober); service.verifier = blocker
    project_id, failed_job, failed_attempt, plan, staged = _failed_recovery(service, state)
    preflight = service.recovery_preflight(project_id, _recovery_request(state, failed_job, failed_attempt, plan))
    request = _recovery_request(state, failed_job, failed_attempt, plan, mode="submit", fingerprint=preflight["recovery_fingerprint"], submission="66666666-6666-4666-8666-666666666666")
    job, _created = service.submit_recovery(project_id, request)
    assert blocker.started.wait(2)
    running = service.get_job(project_id, job["job_id"])
    assert running["phase"] == "decoding_output" and running["last_heartbeat_at"] is not None
    service.cancel(project_id, job["job_id"])
    try: terminal = _wait_terminal(service, project_id, job["job_id"])
    finally: service.close()
    assert terminal["state"] == "cancelled"
    assert staged.is_file()


def test_recovery_verification_failure_creates_new_failed_result_and_keeps_history(tmp_path):
    service, state = _render_service(tmp_path)
    service.verifier = FailingRecoveryVerifier()
    project_id, failed_job, failed_attempt, plan, staged = _failed_recovery(service, state)
    preflight = service.recovery_preflight(project_id, _recovery_request(state, failed_job, failed_attempt, plan))
    request = _recovery_request(state, failed_job, failed_attempt, plan, mode="submit", fingerprint=preflight["recovery_fingerprint"], submission="77777777-7777-4777-8777-777777777777")
    job, _created = service.submit_recovery(project_id, request)
    try:
        terminal = _wait_terminal(service, project_id, job["job_id"])
        result = service.result(project_id, job["job_id"])
        historical = service.get_job(project_id, failed_job)
    finally: service.close()
    assert terminal["state"] == "failed" and result["diagnostics"][0]["details"]["infrastructure_code"] == "OUTPUT_DECODE_FAILED"
    assert historical["state"] == "failed" and staged.is_file()


def test_restart_reconciliation_requires_registered_artifact_receipt(tmp_path):
    service, state = _render_service(tmp_path)
    project_id, job_id, _attempt, plan, staged = _failed_recovery(service, state)
    record = service._load_record(job_id); record["job"].update({"state": "running", "phase": "publishing_artifact", "result_available": False}); record["result"] = None
    final = service.runtime.catalogs.resolve(project_id)[1] / plan["output"]["relative_path"]
    final.parent.mkdir(parents=True); staged.replace(final)
    digest = hashlib.sha256(final.read_bytes()).hexdigest()
    artifact = {"artifact_id": "artifact-" + "7" * 64, "relative_path": plan["output"]["relative_path"], "sha256": digest, "plan_fingerprint": plan["plan_fingerprint"]}
    record["publication"] = {"state": "verified", "artifact": artifact}; service._save_record(job_id, record)
    service._recover()
    try:
        recovered = service.get_job(project_id, job_id)
        result = service.result(project_id, job_id)
    finally: service.close()
    assert recovered["state"] == "failed" and recovered["recovery"] == "indeterminate"
    assert result["diagnostics"][0]["code"] == "RECOVERY_INDETERMINATE"
    assert staged.is_file() and not final.exists()


@pytest.mark.parametrize("publication_state", ["verified", "artifact_committed"])
def test_restart_reconciliation_completes_report_committed_publication(tmp_path, publication_state):
    service, state = _render_service(tmp_path)
    project_id, job_id, _attempt, plan, staged = _failed_recovery(service, state)
    record = service._load_record(job_id); record["job"].update({"state": "running", "phase": "publishing_report", "result_available": False}); record["result"] = None
    final = service.runtime.catalogs.resolve(project_id)[1] / plan["output"]["relative_path"]
    final.parent.mkdir(parents=True); staged.replace(final)
    digest = hashlib.sha256(final.read_bytes()).hexdigest()
    artifact = {"artifact_id": "artifact-" + "6" * 64, "relative_path": plan["output"]["relative_path"], "sha256": digest, "plan_fingerprint": plan["plan_fingerprint"]}
    service._publish_artifact(project_id, artifact)
    record["publication"] = {"state": publication_state, "artifact": artifact}; service._save_record(job_id, record)
    service._recover()
    try:
        recovered = service.get_job(project_id, job_id)
        result = service.result(project_id, job_id)
    finally: service.close()
    assert recovered["state"] == "succeeded" and recovered["recovery"] == "reconciling"
    assert result["state"] == "succeeded" and result["artifacts"][0]["artifact_id"] == artifact["artifact_id"]
    assert final.is_file()


def test_restart_reconciliation_restores_replaced_artifact_before_report_commit(tmp_path):
    service, state = _render_service(tmp_path)
    project_id, job_id, _attempt, plan, staged = _failed_recovery(service, state)
    record = service._load_record(job_id); record["job"].update({"state": "running", "phase": "publishing_artifact", "result_available": False}); record["result"] = None
    project_root = service.runtime.catalogs.resolve(project_id)[1]
    final = project_root / plan["output"]["relative_path"]; final.parent.mkdir(parents=True)
    old_bytes = b"previous verified artifact"; final.write_bytes(old_bytes)
    old_digest = hashlib.sha256(old_bytes).hexdigest(); old_artifact_id = "artifact-" + "5" * 64
    old_artifact = {"artifact_id": old_artifact_id, "relative_path": plan["output"]["relative_path"], "sha256": old_digest, "plan_fingerprint": "4" * 64}
    service._publish_artifact(project_id, old_artifact)
    history = project_root / "output" / ".wrld-history" / old_artifact_id / f"{old_digest}.mp4"; history.parent.mkdir(parents=True); final.replace(history)
    staged.replace(final)
    new_digest = hashlib.sha256(final.read_bytes()).hexdigest()
    new_artifact = {"artifact_id": "artifact-" + "3" * 64, "relative_path": plan["output"]["relative_path"], "sha256": new_digest, "plan_fingerprint": plan["plan_fingerprint"]}
    record["request"].update({"output_action": "replace_verified", "replacement": {"artifact_id": old_artifact_id, "expected_sha256": old_digest, "expected_report_revision": service._artifact_revision(project_id)}})
    record["publication"] = {"state": "verified", "artifact": new_artifact}; service._save_record(job_id, record)
    service._recover()
    try: recovered = service.get_job(project_id, job_id)
    finally: service.close()
    recovery_stage = service.root / "staging" / job_id / record["job"]["attempt_id"] / "output.mp4"
    assert recovered["state"] == "failed" and recovered["recovery"] == "indeterminate"
    assert final.read_bytes() == old_bytes and recovery_stage.is_file() and not history.exists()

