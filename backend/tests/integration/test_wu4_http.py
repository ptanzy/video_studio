from __future__ import annotations

import os
import shutil
import time
import wave
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from wrld_video_studio.domain.wu4 import TrustedProjectRoot, WU4Error
from wrld_video_studio.infrastructure.project_resources import SecureProjectFile
from wrld_video_studio.interfaces.http.app import WU4ApplicationConfig, create_import_app
from wrld_video_studio.interfaces.http.wu4 import error_response, router


class Albums:
    def open_audio(self, project_id: str, track_id: str):
        if track_id != "track-1": raise WU4Error("TRACK_NOT_FOUND", "Unknown track.")
        data = b"RIFF" + bytes(range(100))
        return SecureProjectFile(BytesIO(data), size=len(data)), {"size": len(data), "etag": '"sha256-test"'}


class Assets:
    def open_audio(self, project_id: str, asset_id: str):
        data = b"ID3" + bytes(range(40))
        return SecureProjectFile(BytesIO(data), size=len(data)), {"size": len(data), "etag": '"sha256-audio"', "content_type": "audio/mpeg"}

    def open_image(self, project_id: str, asset_id: str):
        data = b"image"
        return SecureProjectFile(BytesIO(data), size=len(data)), {"size": len(data), "etag": '"sha256-image"', "content_type": "image/webp"}

    def thumbnail(self, project_id: str, asset_id: str, variant: str):
        assert variant in {"small", "large"}
        return b"\x89PNG\r\n\x1a\n" + bytes(20), '"sha256-thumb"'


class Inventories:
    def read(self, project_id: str): return {"contract_version": "wrld-project-inventory/1.0", "project_id": project_id, "assets": []}
    def relink(self, project_id: str, asset_id: str, relative_path: str): return {"asset_id": asset_id, "relative_path": relative_path}


class Scans:
    def start(self, project_id: str, retry): return {"scan_id": "scan-1", "project_id": project_id, "status": "queued"}
    def get(self, project_id: str, scan_id: str): return {"scan_id": scan_id, "project_id": project_id, "status": "running"}
    def cancel(self, project_id: str, scan_id: str): return {"scan_id": scan_id, "project_id": project_id, "status": "cancel_requested"}


class ProjectDocumentService:
    def __init__(self, contract_version: str) -> None:
        self.contract_version = contract_version

    def get(self, project_id: str):
        base = {"contract_version": self.contract_version, "project_id": project_id, "revision": 1, "save_id": "initial", "state_digest": "0" * 64}
        if self.contract_version == "wrld-project-preferences/1.0": return {**base, "excluded_asset_ids": []}
        return {**base, "preferred_short_duration_seconds": 45, "albums": [], "singles": [], "shorts": [], "issues": []}

    def put(self, project_id: str, expected_revision: int, save_id: str, state: dict):
        return {**state, "project_id": project_id, "revision": expected_revision + 1, "save_id": save_id}


class YouTubeMetadata:
    def get(self, project_id: str): return {"contract_version": "wrld-youtube-metadata-editor/1.0", "project_id": project_id, "revision": 1, "targets": []}
    def initialize(self, project_id: str, save_id: str, creation_revision: int, creation_state_digest: str): return {"project_id": project_id, "save_id": save_id, "revision": 1, "creation_revision": creation_revision, "creation_state_digest": creation_state_digest}
    def put(self, project_id: str, expected_revision: int, save_id: str, state: dict): return {**state, "project_id": project_id, "revision": expected_revision + 1, "save_id": save_id}
    def validate(self, project_id: str, state: dict, mode: str, target_keys): return {"project_id": project_id, "mode": mode, "target_keys": target_keys, "valid": True}
    def reconcile_preview(self, project_id: str, expected_revision: int, refresh_fields, carry_chapter_labels): return {"project_id": project_id, "editor_revision": expected_revision, "refresh_fields": refresh_fields, "carry_chapter_labels": carry_chapter_labels, "preview_fingerprint": "a" * 64}
    def reconcile(self, project_id: str, expected_revision: int, save_id: str, preview_fingerprint: str, refresh_fields, carry_chapter_labels): return {"project_id": project_id, "revision": expected_revision + 1, "save_id": save_id, "preview_fingerprint": preview_fingerprint}
    def export_preview(self, project_id: str, expected_revision: int, target_keys): return {"project_id": project_id, "editor_revision": expected_revision, "target_keys": target_keys, "preview_fingerprint": "a" * 64}
    def export(self, project_id: str, expected_revision: int, target_keys, preview_fingerprint: str, replace_existing: bool, expected_existing_sha256): return {"project_id": project_id, "target_keys": target_keys, "preview_fingerprint": preview_fingerprint, "replace_existing": replace_existing, "expected_existing_sha256": expected_existing_sha256}


class CreationRender:
    def targets(self, project_id: str): return {"contract_version": "wrld-creation-render-targets/1.0", "project_id": project_id, "targets": []}
    def preflight(self, project_id: str, payload: dict): return {"contract_version": "wrld-creation-render-preflight/1.0", "project_id": project_id, "mode": payload["mode"]}
    def submit(self, project_id: str, payload: dict): return ({"job_id": "job-1", "project_id": project_id, "state": "queued"}, True)
    def recovery_preflight(self, project_id: str, payload: dict): return {"contract_version": "wrld-creation-render-recovery-preflight/1.0", "project_id": project_id, "mode": payload["mode"]}
    def submit_recovery(self, project_id: str, payload: dict): return ({"job_id": "recovery-job-1", "project_id": project_id, "state": "queued"}, True)
    def list_jobs(self, project_id: str): return [{"job_id": "job-1", "project_id": project_id, "state": "queued", "target": {"composition_id": "single-1"}}]
    def get_job(self, project_id: str, job_id: str): return {"job_id": job_id, "project_id": project_id, "state": "running"}
    def result(self, project_id: str, job_id: str): return {"job_id": job_id, "project_id": project_id, "state": "succeeded"}
    def cancel(self, project_id: str, job_id: str): return {"job_id": job_id, "project_id": project_id, "state": "cancel_requested"}
    def artifact(self, project_id: str, artifact_id: str): return {"artifact_id": artifact_id, "project_id": project_id}


def app() -> FastAPI:
    value = FastAPI()
    value.state.wu4_runtime = SimpleNamespace(albums=Albums(), assets=Assets(), inventories=Inventories(), scans=Scans(), preferences=ProjectDocumentService("wrld-project-preferences/1.0"), creation=ProjectDocumentService("wrld-creation-state/1.0"), youtube_metadata=YouTubeMetadata(), creation_render=CreationRender())
    value.include_router(router)
    value.add_exception_handler(WU4Error, lambda _request, error: error_response(error))
    return value


def test_wav_stream_supports_get_head_single_range_and_conditional_request():
    with TestClient(app()) as client:
        full = client.get("/api/v1/projects/p/tracks/track-1/audio")
        assert full.status_code == 200 and len(full.content) == 104
        assert full.headers["accept-ranges"] == "bytes"
        partial = client.get("/api/v1/projects/p/tracks/track-1/audio", headers={"Range": "bytes=4-13"})
        assert partial.status_code == 206 and partial.content == bytes(range(10))
        assert partial.headers["content-range"] == "bytes 4-13/104"
        stale_if_range = client.get("/api/v1/projects/p/tracks/track-1/audio", headers={"Range": "bytes=4-13", "If-Range": '"old"'})
        assert stale_if_range.status_code == 200 and len(stale_if_range.content) == 104
        head = client.head("/api/v1/projects/p/tracks/track-1/audio")
        assert head.status_code == 200 and head.content == b""
        unchanged = client.get("/api/v1/projects/p/tracks/track-1/audio", headers={"If-None-Match": '"sha256-test"'})
        assert unchanged.status_code == 304


def test_wav_stream_rejects_multiple_or_unsatisfiable_ranges():
    with TestClient(app()) as client:
        for value in ("bytes=0-1,3-4", "bytes=999-1000"):
            response = client.get("/api/v1/projects/p/tracks/track-1/audio", headers={"Range": value})
            assert response.status_code == 416
            assert response.json()["error"]["code"] == "RANGE_NOT_SATISFIABLE"
            assert response.headers["content-range"] == "bytes */104"


def test_opaque_asset_resources_support_ranges_mime_etag_and_thumbnails():
    with TestClient(app()) as client:
        audio = client.get("/api/v1/projects/p/assets/a/audio", headers={"Range": "bytes=3-7"})
        assert audio.status_code == 206 and audio.content == bytes(range(5))
        assert audio.headers["content-type"] == "audio/mpeg"
        assert audio.headers["x-content-type-options"] == "nosniff"
        assert client.head("/api/v1/projects/p/assets/a/image").headers["content-type"] == "image/webp"
        thumbnail = client.get("/api/v1/projects/p/assets/i/thumbnails/large")
        assert thumbnail.status_code == 200 and thumbnail.headers["etag"] == '"sha256-thumb"'
        assert client.get("/api/v1/projects/p/assets/i/thumbnails/large", headers={"If-None-Match": '"sha256-thumb"'}).status_code == 304


def test_inventory_scan_and_explicit_asset_relink_routes():
    with TestClient(app()) as client:
        assert client.get("/api/v1/projects/p/inventory").status_code == 200
        started = client.post("/api/v1/projects/p/inventory-scans", json={"retry_of_scan_id": None})
        assert started.status_code == 202 and started.json()["status"] == "queued"
        assert client.get("/api/v1/projects/p/inventory-scans/scan-1").json()["status"] == "running"
        assert client.delete("/api/v1/projects/p/inventory-scans/scan-1").json()["status"] == "cancel_requested"
        relinked = client.put("/api/v1/projects/p/assets/asset-missing/location", json={"relative_path": "moved/song.wav"})
        assert relinked.status_code == 200
        assert relinked.json() == {"asset_id": "asset-missing", "relative_path": "moved/song.wav"}


def test_project_preferences_and_creation_state_routes_are_revision_safe_shapes():
    with TestClient(app()) as client:
        preferences = client.get("/api/v1/projects/p/preferences").json()
        assert preferences["excluded_asset_ids"] == []
        saved = client.put("/api/v1/projects/p/preferences", json={"expected_revision": 1, "save_id": "exclude", "state": {**preferences, "excluded_asset_ids": ["asset-a"]}})
        assert saved.status_code == 200 and saved.json()["revision"] == 2
        creation = client.get("/api/v1/projects/p/creation-state").json()
        assert creation["preferred_short_duration_seconds"] == 45
        saved_creation = client.put("/api/v1/projects/p/creation-state", json={"expected_revision": 1, "save_id": "creation", "state": creation})
        assert saved_creation.status_code == 200 and saved_creation.json()["revision"] == 2


def test_youtube_metadata_routes_are_project_scoped_and_revision_safe_shapes():
    with TestClient(app()) as client:
        base = "/api/v1/projects/p/youtube-metadata"
        assert client.get(base).json()["project_id"] == "p"
        initialized = client.post(f"{base}/initialize", json={"save_id": "initialize", "creation_revision": 4, "creation_state_digest": "a" * 64})
        assert initialized.status_code == 201 and initialized.json()["creation_revision"] == 4
        saved = client.put(base, json={"expected_revision": 1, "save_id": "save", "state": {"targets": []}})
        assert saved.json()["revision"] == 2
        checked = client.post(f"{base}/validate", json={"state": {"targets": []}, "mode": "draft", "target_keys": None})
        assert checked.json()["mode"] == "draft"
        preview = client.post(f"{base}/reconcile-preview", json={"expected_revision": 1, "refresh_fields": [{"target_key": "single:s", "field": "title"}], "carry_chapter_labels": []})
        assert preview.json()["refresh_fields"] == [{"target_key": "single:s", "field": "title"}]
        reconciled = client.post(f"{base}/reconcile", json={"expected_revision": 1, "save_id": "reconcile", "preview_fingerprint": "a" * 64, "refresh_fields": [], "carry_chapter_labels": []})
        assert reconciled.json()["revision"] == 2
        export_preview = client.post(f"{base}/export-preview", json={"expected_revision": 2, "target_keys": ["single:s"]})
        assert export_preview.json()["target_keys"] == ["single:s"]
        exported = client.post(f"{base}/exports", json={"expected_revision": 2, "target_keys": ["single:s"], "preview_fingerprint": "a" * 64, "replace_existing": False, "expected_existing_sha256": None})
        assert exported.json()["replace_existing"] is False


def test_creation_render_routes_are_project_scoped_and_preserve_async_statuses():
    with TestClient(app()) as client:
        base = "/api/v1/projects/p"
        assert client.get(f"{base}/render-targets").json()["project_id"] == "p"
        assert client.post(f"{base}/render-preflights", json={"mode": "preflight"}).json()["mode"] == "preflight"
        submitted = client.post(f"{base}/render-jobs", json={"mode": "submit"})
        assert submitted.status_code == 202 and submitted.json()["state"] == "queued"
        recovery = client.post(f"{base}/render-recovery-preflights", json={"mode": "preflight"})
        assert recovery.status_code == 200 and recovery.json()["mode"] == "preflight"
        recovered = client.post(f"{base}/render-recovery-jobs", json={"mode": "submit"})
        assert recovered.status_code == 202 and recovered.json()["job_id"] == "recovery-job-1"
        assert client.get(f"{base}/render-jobs?state=queued&composition_id=single-1").json()[0]["job_id"] == "job-1"
        assert client.get(f"{base}/render-jobs/job-1").json()["state"] == "running"
        assert client.get(f"{base}/render-jobs/job-1/result").json()["state"] == "succeeded"
        cancelled = client.delete(f"{base}/render-jobs/job-1")
        assert cancelled.status_code == 202 and cancelled.json()["state"] == "cancel_requested"
        assert client.get(f"{base}/render-artifacts/artifact-1").json()["artifact_id"] == "artifact-1"


@pytest.mark.integration_ffmpeg
def test_standalone_import_runtime_scans_and_serves_real_temporary_media(tmp_path):
    ffmpeg = os.environ.get("WRLD_FFMPEG_PATH"); ffprobe = os.environ.get("WRLD_FFPROBE_PATH")
    if not ffmpeg or not ffprobe:
        pytest.skip("WRLD_FFMPEG_PATH and WRLD_FFPROBE_PATH are required")
    repository = Path(__file__).resolve().parents[3]
    schemas = repository / "contracts/schemas"
    library = tmp_path / "library"; project = library / "free-form"; project.mkdir(parents=True)
    with wave.open(str(project / "tone.wav"), "wb") as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(48_000); output.writeframes(b"\x00\x00" * 4_800)
    shutil.copyfile(repository / "docs/ui/import.png", project / "cover.png")
    config = WU4ApplicationConfig(
        project_roots=(TrustedProjectRoot("music", "Temporary music", library),), state_root=tmp_path / "state",
        manifest_schemas=tuple(schemas / name for name in ("video-manifest-v1.schema.json", "video-manifest-v2.schema.json", "video-manifest-v3.schema.json", "video-manifest-v4.schema.json")),
        override_schema=schemas / "override-store-v1.schema.json", catalog_schema=schemas / "project-catalog-v2.schema.json",
        editor_state_schema=schemas / "editor-state-v1.schema.json", inventory_schema=schemas / "project-inventory-v1.schema.json",
        ffmpeg_path=Path(ffmpeg), ffprobe_path=Path(ffprobe),
    )
    with TestClient(create_import_app(config)) as client:
        registered = client.post("/api/v1/projects", json={"root_id": "music", "relative_path": "free-form"})
        assert registered.status_code == 201
        project_id = registered.json()["project_id"]
        started = client.post(f"/api/v1/projects/{project_id}/inventory-scans", json={"retry_of_scan_id": None})
        assert started.status_code == 202
        scan_id = started.json()["scan_id"]
        for _ in range(200):
            status = client.get(f"/api/v1/projects/{project_id}/inventory-scans/{scan_id}").json()
            if status["status"] in {"completed", "failed", "cancelled"}: break
            time.sleep(0.025)
        assert status["status"] == "completed", status
        inventory = client.get(f"/api/v1/projects/{project_id}/inventory").json()
        audio = next(item for item in inventory["assets"] if item["kind"] == "audio")
        image = next(item for item in inventory["assets"] if item["kind"] == "image")
        ranged = client.get(f"/api/v1/projects/{project_id}/assets/{audio['asset_id']}/audio", headers={"Range": "bytes=0-15"})
        assert ranged.status_code == 206 and len(ranged.content) == 16
        thumbnail = client.get(f"/api/v1/projects/{project_id}/assets/{image['asset_id']}/thumbnails/small")
        assert thumbnail.status_code == 200 and thumbnail.content.startswith(b"\x89PNG\r\n\x1a\n")
        preferences = client.get(f"/api/v1/projects/{project_id}/preferences").json()
        preferences["excluded_asset_ids"] = [image["asset_id"]]
        saved_preferences = client.put(
            f"/api/v1/projects/{project_id}/preferences",
            json={"expected_revision": preferences["revision"], "save_id": "smoke-exclude", "state": preferences},
        )
        assert saved_preferences.status_code == 200
        creation = client.get(f"/api/v1/projects/{project_id}/creation-state").json()
        creation["singles"] = [{
            "single_id": "single-smoke", "asset_id": audio["asset_id"],
            "expected_sha256": audio["sha256"], "status": "active",
            "customized": False, "approved": False, "settings": {},
        }]
        creation["shorts"] = [{
            "short_id": "short-smoke", "asset_id": audio["asset_id"],
            "expected_sha256": audio["sha256"], "status": "active",
            "start_sample": 0, "sample_count": 4_800, "origin": "manual_required",
            "review_required": True, "customized": False, "approved": False,
            "settings": {},
        }]
        saved_creation = client.put(
            f"/api/v1/projects/{project_id}/creation-state",
            json={"expected_revision": creation["revision"], "save_id": "smoke-creation", "state": creation},
        )
        assert saved_creation.status_code == 200

    with TestClient(create_import_app(config)) as client:
        projects = client.get("/api/v1/projects").json()["projects"]
        assert [item["project_id"] for item in projects] == [project_id]
        restored_preferences = client.get(f"/api/v1/projects/{project_id}/preferences").json()
        assert restored_preferences["excluded_asset_ids"] == [image["asset_id"]]
        restored_creation = client.get(f"/api/v1/projects/{project_id}/creation-state").json()
        assert restored_creation["singles"][0]["single_id"] == "single-smoke"
        assert restored_creation["shorts"][0]["short_id"] == "short-smoke"

