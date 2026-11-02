from __future__ import annotations

import threading
import os
import copy
from pathlib import Path

import pytest

from wrld_video_studio.application.project_inventory import ProjectInventoryService
from wrld_video_studio.application.wu4 import ProjectCatalogs
from wrld_video_studio.domain.jobs import MediaProbe, MediaStream
from wrld_video_studio.domain.wu4 import InventoryScanPolicy, TrustedProjectRoot, WU4Error
from wrld_video_studio.infrastructure.override_store import OverrideStore
from wrld_video_studio.infrastructure.project_catalog import ProjectCatalogStore
from wrld_video_studio.infrastructure.project_inventory import ProjectInventoryStore
from wrld_video_studio.infrastructure.project_resources import TrustedProjectResolver


ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "contracts" / "schemas"


class UnusedLoader:
    def load(self, _root: Path):
        raise AssertionError("manifest loading is not required for flexible Import")


class FakeProber:
    def probe(self, path: Path) -> MediaProbe:
        suffix = path.suffix.casefold()
        if suffix in {".wav", ".mp3", ".flac", ".m4a"}:
            codec = {".wav": "pcm_s16le", ".mp3": "mp3", ".flac": "flac", ".m4a": "aac"}[suffix]
            streams = [MediaStream(0, "audio", codec, 48_000, 2)]
            if path.name == "video.m4a": streams.append(MediaStream(1, "video", "h264", width=640, height=360))
            return MediaProbe(str(path), "fake", 2.0, tuple(streams), suffix[1:])
        codec = {".png": "png", ".jpg": "mjpeg", ".jpeg": "mjpeg", ".webp": "webp", ".mp4": "h264"}[suffix]
        frames = 2 if path.name.startswith("animated") else 1
        return MediaProbe(str(path), "fake", 2.0 if suffix == ".mp4" else None, (MediaStream(0, "video", codec, width=640, height=360, frame_count=frames),), suffix[1:])


@pytest.fixture
def inventory_services(tmp_path: Path):
    library = tmp_path / "library"; project = library / "free-form"
    project.mkdir(parents=True)
    resolver = TrustedProjectResolver((TrustedProjectRoot("music", "Music", library),))
    catalogs = ProjectCatalogs(
        resolver,
        ProjectCatalogStore(OverrideStore(tmp_path / "state/catalog", SCHEMAS / "override-store-v1.schema.json"), SCHEMAS / "project-catalog-v2.schema.json"),
        UnusedLoader(),
    )
    project_id = catalogs.register("music", "free-form")["project_id"]
    store = ProjectInventoryStore(OverrideStore(tmp_path / "state/inventory", SCHEMAS / "override-store-v1.schema.json"), SCHEMAS / "project-inventory-v1.schema.json")
    service = ProjectInventoryService(catalogs, resolver, store, FakeProber(), InventoryScanPolicy())
    return service, project_id, project


def scan(service: ProjectInventoryService, project_id: str):
    return service.scan(project_id, "scan-one", threading.Event(), lambda _visited, _found: None)


def test_manifestless_empty_project_scans_transactionally(inventory_services):
    service, project_id, _project = inventory_services
    result = scan(service, project_id)
    assert result["inventory_revision"] == 1
    assert result["assets"] == []
    assert result["counts"] == {"audio": 0, "image": 0, "video": 0, "unknown": 0, "missing": 0}


def test_recursive_discovery_exclusions_capabilities_and_stable_ids(inventory_services):
    service, project_id, project = inventory_services
    (project / "nested").mkdir(); (project / "output").mkdir()
    (project / "nested/song.mp3").write_bytes(b"audio")
    (project / "nested/cover.png").write_bytes(b"image")
    (project / "clip.mp4").write_bytes(b"video")
    (project / "output/ignored.wav").write_bytes(b"ignored")
    first = scan(service, project_id)
    assert [item["relative_path"] for item in first["assets"]] == ["clip.mp4", "nested/cover.png", "nested/song.mp3"]
    assert next(item for item in first["assets"] if item["kind"] == "audio")["capabilities"]["server_stream"]["status"] == "supported"
    ids = {item["relative_path"]: item["asset_id"] for item in first["assets"]}
    second = service.scan(project_id, "scan-two", threading.Event(), lambda *_: None)
    assert {item["relative_path"]: item["asset_id"] for item in second["assets"]} == ids
    assert all(item["verification_state"] == "carried_forward" for item in second["assets"])


def test_missing_asset_can_be_explicitly_relinked_without_changing_identity(inventory_services):
    service, project_id, project = inventory_services
    source = project / "old.wav"; source.write_bytes(b"old")
    original = scan(service, project_id)["assets"][0]
    source.unlink(); service.scan(project_id, "scan-two", threading.Event(), lambda *_: None)
    (project / "new.wav").write_bytes(b"old")
    replacement = service.relink(project_id, original["asset_id"], "new.wav")
    assert replacement["asset_id"] == original["asset_id"]
    assert replacement["relative_path"] == "new.wav"


def test_missing_asset_relink_rejects_different_content_without_reassigning_identity(inventory_services):
    service, project_id, project = inventory_services
    source = project / "old.wav"; source.write_bytes(b"old")
    original = scan(service, project_id)["assets"][0]
    source.unlink(); service.scan(project_id, "scan-two", threading.Event(), lambda *_: None)
    (project / "different.wav").write_bytes(b"different")
    with pytest.raises(WU4Error) as failure:
        service.relink(project_id, original["asset_id"], "different.wav")
    assert failure.value.code == "ASSET_RELINK_INVALID"
    missing = next(item for item in service.read(project_id)["assets"] if item["asset_id"] == original["asset_id"])
    assert missing["presence"] == "missing"


def test_fatal_scan_limit_does_not_publish_partial_inventory(inventory_services):
    service, project_id, project = inventory_services
    (project / "one.wav").write_bytes(b"one"); (project / "two.wav").write_bytes(b"two")
    service.policy = InventoryScanPolicy(max_entries=1)
    with pytest.raises(WU4Error, match="entry limit"):
        scan(service, project_id)
    assert service.read(project_id)["inventory_revision"] == 0


@pytest.mark.skipif(os.name == "nt", reason="case-distinct paths require a case-sensitive host filesystem")
def test_case_distinct_paths_receive_distinct_asset_identities(inventory_services):
    service, project_id, project = inventory_services
    (project / "A.wav").write_bytes(b"upper")
    (project / "a.wav").write_bytes(b"lower")
    result = scan(service, project_id)
    assert {item["relative_path"] for item in result["assets"]} == {"A.wav", "a.wav"}
    assert len({item["asset_id"] for item in result["assets"]}) == 2


def test_legacy_inventory_identity_collision_stops_without_reassignment(inventory_services, monkeypatch):
    service, project_id, project = inventory_services
    (project / "song.wav").write_bytes(b"audio")
    published = scan(service, project_id)
    collision = copy.deepcopy(published)
    duplicate = copy.deepcopy(collision["assets"][0])
    duplicate["asset_id"] = "asset-distinct-legacy"
    collision["assets"].append(duplicate)
    monkeypatch.setattr(service.store, "read", lambda _project_id: copy.deepcopy(collision))
    with pytest.raises(WU4Error) as failure:
        service.scan(project_id, "scan-collision", threading.Event(), lambda *_: None)
    assert failure.value.code == "ASSET_ID_COLLISION"


def test_m4a_with_video_and_multiframe_images_are_not_served(inventory_services):
    service, project_id, project = inventory_services
    (project / "video.m4a").write_bytes(b"audio-video")
    (project / "animated.webp").write_bytes(b"animated")
    result = scan(service, project_id)
    by_path = {item["relative_path"]: item for item in result["assets"]}
    assert by_path["video.m4a"]["capabilities"]["server_stream"]["status"] == "unsupported"
    assert by_path["animated.webp"]["capabilities"]["inspection"]["status"] == "unsupported"
