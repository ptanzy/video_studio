from __future__ import annotations

import copy
from pathlib import Path

import pytest
import json
from jsonschema import Draft202012Validator

from wrld_video_studio.application.wu4 import AlbumProjects, EditorStates, ProjectCatalogs
from wrld_video_studio.domain.video_export import AlbumIdentity, VideoTrack
from wrld_video_studio.domain.video_effects import VideoEffects
from wrld_video_studio.domain.video_export_v2 import MotionVideoManifest
from wrld_video_studio.domain.wu4 import TrustedProjectRoot, WU4Error
from wrld_video_studio.infrastructure.editor_state_store import EditorStateStore
from wrld_video_studio.infrastructure.override_store import OverrideStore
from wrld_video_studio.infrastructure.project_catalog import ProjectCatalogStore
from wrld_video_studio.infrastructure.project_resources import TrustedProjectResolver
from wrld_video_studio.infrastructure.project_sources import FilesystemVideoProject


ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "contracts" / "schemas"


class FakeLoader:
    def load(self, root: Path) -> FilesystemVideoProject:
        manifest = MotionVideoManifest(
            "wrld-video-album/2.0",
            AlbumIdentity("album-1", "Album", "Artist", "Channel"),
            "art.png", None, None,
            (VideoTrack("track-1", 1, "Track", "track.wav"),),
            "youtube-1080p30-motion-v1", VideoEffects(), (), {},
        )
        return FilesystemVideoProject(root, manifest, {}, normalized_sample_counts=(480_000,))


@pytest.fixture
def services(tmp_path):
    library = tmp_path / "library"; project = library / "album"
    project.mkdir(parents=True)
    (project / "video_manifest.json").write_text("{}", encoding="utf-8")
    (project / "art.png").write_bytes(b"image")
    (project / "track.wav").write_bytes(b"RIFF" + bytes(range(64)))
    resolver = TrustedProjectResolver((TrustedProjectRoot("music", "Music", library),))
    catalog_store = ProjectCatalogStore(OverrideStore(tmp_path / "state" / "catalog", SCHEMAS / "override-store-v1.schema.json"), SCHEMAS / "project-catalog-v2.schema.json")
    catalogs = ProjectCatalogs(resolver, catalog_store, FakeLoader())
    albums = AlbumProjects(catalogs, resolver)
    editor_store = EditorStateStore(OverrideStore(tmp_path / "state" / "editor", SCHEMAS / "override-store-v1.schema.json"), SCHEMAS / "editor-state-v1.schema.json")
    return catalogs, albums, EditorStates(albums, editor_store), project


def test_register_duplicate_remove_and_relink_preserve_opaque_identity(services):
    catalogs, _albums, _editors, _project = services
    created = catalogs.register("music", "album")
    assert Path(created["project_id"]).is_absolute() is False
    assert created["availability"] == "available"
    with pytest.raises(WU4Error, match="already registered"):
        catalogs.register("music", "album")
    catalogs.remove(created["project_id"])
    assert catalogs.list()["projects"][0]["availability"] == "removed"
    restored = catalogs.relink(created["project_id"], "music", "album")
    assert restored["project_id"] == created["project_id"]


def test_catalog_v1_migrates_atomically_and_idempotently(tmp_path):
    store = OverrideStore(tmp_path / "catalog", SCHEMAS / "override-store-v1.schema.json")
    record = store.create("wu4-project-catalog")
    legacy = {
        "contract_version": "wrld-project-catalog/1.0",
        "projects": [{"project_id": "project-1", "album_id": "album-1", "root_id": "music", "relative_path": "album", "active": True, "registered_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"}],
    }
    store.update("wu4-project-catalog", record["revision"], legacy)
    migrated_store = ProjectCatalogStore(store, SCHEMAS / "project-catalog-v2.schema.json")
    first = migrated_store.read(); second = migrated_store.read()
    assert first["contract_version"] == "wrld-project-catalog/2.0"
    assert first["projects"][0]["project_id"] == "project-1"
    assert first["projects"][0]["enrichment"]["album_id"] == "album-1"
    assert second == first
    backup = store.read("wu4-project-catalog-v1-backup")["overrides"]
    assert backup["catalog"] == legacy


def test_project_resolution_rejects_traversal_and_absolute_paths(services):
    catalogs, _albums, _editors, _project = services
    for invalid in ("../album", "C:/album", "/album", "album\\child"):
        with pytest.raises(WU4Error): catalogs.register("music", invalid)


def test_trusted_project_roots_must_not_overlap(tmp_path):
    library = tmp_path / "library"; nested = library / "nested"
    nested.mkdir(parents=True)
    with pytest.raises(ValueError, match="overlap"):
        TrustedProjectResolver((TrustedProjectRoot("one", "One", library), TrustedProjectRoot("two", "Two", nested)))


def test_album_read_is_normalized_and_contains_no_absolute_paths(services):
    catalogs, albums, _editors, project = services
    project_id = catalogs.register("music", "album")["project_id"]
    document = albums.read(project_id)
    assert document["tracks"][0]["normalized_sample_count"] == 480_000
    assert document["tracks"][0]["audio"] == "track.wav"
    assert str(project) not in repr(document)
    assert len(document["source_fingerprint"]) == 64
    schema = json.loads((SCHEMAS / "album-read-v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(document)


def test_audio_open_rejects_manifest_or_audio_replacement_after_read(services):
    catalogs, albums, _editors, project = services
    project_id = catalogs.register("music", "album")["project_id"]
    albums.read(project_id)
    (project / "track.wav").write_bytes(b"replacement")
    with pytest.raises(WU4Error) as failure:
        albums.open_audio(project_id, "track-1")
    assert failure.value.code == "SOURCE_CHANGED"


def test_editor_initializes_stable_short_and_revision_safe_updates(services):
    catalogs, _albums, editors, _project = services
    project_id = catalogs.register("music", "album")["project_id"]
    first = editors.get(project_id)
    short = first["shorts"]["track-1"]
    assert short["start_sample"] == 0
    assert short["sample_count"] == 480_000
    assert short["review_required"] is False
    candidate = copy.deepcopy(first)
    candidate["shorts"]["track-1"]["start_sample"] = 48_000
    candidate["shorts"]["track-1"]["sample_count"] = 432_000
    candidate["shorts"]["track-1"]["origin"] = "manual"
    saved = editors.put(project_id, first["revision"], "save-1", candidate)
    assert saved["revision"] == first["revision"] + 1
    assert saved["shorts"]["track-1"]["short_id"] == short["short_id"]
    with pytest.raises(WU4Error) as failure:
        editors.put(project_id, first["revision"], "stale", candidate)
    assert failure.value.code == "REVISION_CONFLICT"


def test_short_approval_is_invalidated_by_range_change(services):
    catalogs, _albums, editors, _project = services
    project_id = catalogs.register("music", "album")["project_id"]
    first = editors.get(project_id)
    candidate = copy.deepcopy(first)
    candidate["shorts"]["track-1"]["approval"] = {
        "approved_digest": first["resolved"]["track-1"]["approval_digest"],
        "approved_at": "2026-01-01T00:00:00Z",
    }
    approved = editors.put(project_id, first["revision"], "approve", candidate)
    assert approved["shorts"]["track-1"]["approval"] is not None
    changed = copy.deepcopy(approved)
    changed["shorts"]["track-1"]["start_sample"] = 1
    changed["shorts"]["track-1"]["sample_count"] -= 1
    saved = editors.put(project_id, approved["revision"], "edit", changed)
    assert saved["shorts"]["track-1"]["approval"] is None


def test_effect_inheritance_reports_field_provenance_and_reset(services):
    catalogs, _albums, editors, _project = services
    project_id = catalogs.register("music", "album")["project_id"]
    first = editors.get(project_id)
    candidate = copy.deepcopy(first)
    candidate["album_overrides"] = {"effects": {"pan_zoom": {"max_zoom": 1.02}}}
    candidate["track_overrides"] = {"track-1": {"effects": {"pan_zoom": {"max_zoom": 1.03}}}}
    saved = editors.put(project_id, first["revision"], "inherit", candidate)
    resolved = saved["resolved"]["track-1"]
    assert resolved["effects"]["pan_zoom"]["max_zoom"] == 1.03
    assert resolved["provenance"]["effects.pan_zoom.max_zoom"] == "track"
    reset = copy.deepcopy(saved)
    reset["track_overrides"] = {}
    inherited = editors.put(project_id, saved["revision"], "reset", reset)
    assert inherited["resolved"]["track-1"]["effects"]["pan_zoom"]["max_zoom"] == 1.02
    assert inherited["resolved"]["track-1"]["provenance"]["effects.pan_zoom.max_zoom"] == "album"


def test_short_under_five_seconds_requires_review_and_cannot_be_approved(services):
    catalogs, albums, _editors, _project = services
    project_id = catalogs.register("music", "album")["project_id"]
    class ShortAlbums:
        def read(self, _project_id):
            value = albums.read(project_id)
            value["tracks"][0]["normalized_sample_count"] = 4 * 48_000
            value["source_fingerprint"] = "1" * 64
            return value
    root = services[3].parents[1]
    store = EditorStateStore(OverrideStore(root / "state-short", SCHEMAS / "override-store-v1.schema.json"), SCHEMAS / "editor-state-v1.schema.json")
    editors = EditorStates(ShortAlbums(), store)
    first = editors.get(project_id)
    assert first["shorts"]["track-1"]["review_required"] is True
    candidate = copy.deepcopy(first)
    candidate["shorts"]["track-1"]["approval"] = {"approved_digest": first["resolved"]["track-1"]["approval_digest"], "approved_at": "2026-01-01T00:00:00Z"}
    with pytest.raises(WU4Error) as failure:
        editors.put(project_id, first["revision"], "approve", candidate)
    assert failure.value.code == "SHORT_REVIEW_REQUIRED"

