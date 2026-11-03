from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from wrld_video_studio.application.youtube_metadata import YouTubeMetadataService
from wrld_video_studio.domain.canonical_json import canonical_sha256
from wrld_video_studio.domain.wu4 import WU4Error


SHA_A = "a" * 64
SHA_B = "b" * 64


class Catalogs:
    def __init__(self, root: Path) -> None:
        self.root = root

    def resolve(self, project_id: str):
        return {"project_id": project_id}, self.root


class Inventories:
    def read(self, project_id: str):
        return {
            "project_id": project_id,
            "assets": [
                {"asset_id": "asset-1", "relative_path": "audio/one.wav", "sha256": SHA_A},
                {"asset_id": "asset-2", "relative_path": "audio/two.wav", "sha256": SHA_B},
            ],
        }


class Albums:
    def read(self, project_id: str):
        return {
            "project_id": project_id,
            "source_fingerprint": "c" * 64,
            "album": {"id": "source-album", "title": "Source Album", "artist": "Artist", "channel": "Channel"},
            "tracks": [
                {"id": "track-1", "number": 1, "title": "One", "audio": "audio/one.wav", "audio_sha256": SHA_A, "normalized_sample_count": 480_000},
                {"id": "track-2", "number": 2, "title": "Two", "audio": "audio/two.wav", "audio_sha256": SHA_B, "normalized_sample_count": 480_000},
            ],
        }


class Creation:
    def __init__(self) -> None:
        self.state = {
            "contract_version": "wrld-creation-state/4.0",
            "project_id": "project-1",
            "revision": 7,
            "state_digest": "d" * 64,
            "albums": [
                {"album_plan_id": "album-canonical", "label": "Canonical", "status": "active", "assignments": [
                    {"assignment_id": "assignment-1", "asset_id": "asset-1", "expected_sha256": SHA_A},
                    {"assignment_id": "assignment-2", "asset_id": "asset-2", "expected_sha256": SHA_B},
                ]},
                {"album_plan_id": "album-custom", "label": "Custom", "status": "active", "assignments": [
                    {"assignment_id": "assignment-3", "asset_id": "asset-2", "expected_sha256": SHA_B},
                ]},
            ],
            "singles": [{"single_id": "single-1", "asset_id": "asset-1", "expected_sha256": SHA_A, "status": "active"}],
            "shorts": [{"short_id": "short-1", "asset_id": "asset-1", "expected_sha256": SHA_A, "status": "active"}],
            "issues": [],
        }

    def get(self, project_id: str):
        return copy.deepcopy(self.state)


class Store:
    def __init__(self) -> None:
        self.value = None

    def read(self, project_id: str):
        if self.value is None:
            raise WU4Error("PROJECT_DOCUMENT_NOT_FOUND", "missing")
        return copy.deepcopy(self.value)

    def create(self, project_id: str, document):
        self.value = copy.deepcopy(document)
        self.value["revision"] = 1
        self._digest()
        return copy.deepcopy(self.value)

    def update(self, project_id: str, expected_revision: int, document):
        assert self.value["revision"] == expected_revision
        self.value = copy.deepcopy(document)
        self.value["revision"] = expected_revision + 1
        self._digest()
        return copy.deepcopy(self.value)

    def _digest(self):
        self.value["state_digest"] = "0" * 64
        self.value["state_digest"] = canonical_sha256({key: value for key, value in self.value.items() if key != "state_digest"})


@pytest.fixture
def service(tmp_path):
    creation = Creation()
    return YouTubeMetadataService(Catalogs(tmp_path), Inventories(), Albums(), creation, Store()), creation


def initialize(service):
    metadata, creation = service
    return metadata.initialize("project-1", "initialize", creation.state["revision"], creation.state["state_digest"])


def test_initializes_all_creation_v4_targets_with_deterministic_drafts_and_chapter_boundary(service):
    metadata, _creation = service
    state = initialize(service)
    assert [item["target_key"] for item in state["targets"]] == [
        "album:album-canonical", "album:album-custom", "single:single-1", "short:short-1",
    ]
    canonical, custom, single, short = state["targets"]
    assert canonical["chapters"]["entries"][1]["start_seconds"] == 10
    assert custom["chapters"] is None
    assert single["content"]["title"]["value"] == "One"
    assert short["content"]["title"]["value"] == "One #Shorts"
    assert "{{compilation_url}}" in short["content"]["description"]["value"]
    report = metadata.validate("project-1", state, "draft", None)
    assert any(item["code"] == "CHAPTER_SOURCE_REQUIRED" and item["target_key"] == "album:album-custom" for item in report["diagnostics"])
    saved = metadata.put("project-1", state["revision"], "save-noncanonical", state)
    assert saved["revision"] == 2


def test_approval_placeholders_revision_conflicts_and_selected_atomic_export(service, tmp_path):
    metadata, _creation = service
    state = initialize(service)
    short = next(item for item in state["targets"] if item["target_key"] == "short:short-1")
    blocked = metadata.validate("project-1", state, "approval", [short["target_key"]])
    assert any(item["code"] == "PLACEHOLDER_UNRESOLVED" for item in blocked["diagnostics"])
    with pytest.raises(WU4Error) as ineligible:
        metadata.export_preview("project-1", state["revision"], [short["target_key"]])
    assert ineligible.value.code == "METADATA_VALIDATION_FAILED"
    assert any(item["code"] == "PLACEHOLDER_UNRESOLVED" for item in ineligible.value.details["diagnostics"])

    single = next(item for item in state["targets"] if item["target_key"] == "single:single-1")
    checked = metadata.validate("project-1", state, "approval", [single["target_key"]])
    fingerprint = checked["target_fingerprints"][0]["approval_fingerprint"]
    single["approval"] = {"approved_fingerprint": fingerprint, "approved_at": "2026-11-02T00:00:00Z"}
    state = metadata.put("project-1", state["revision"], "approve-single", state)

    with pytest.raises(WU4Error, match="changed before this save"):
        metadata.put("project-1", 1, "stale", state)

    preview = metadata.export_preview("project-1", state["revision"], ["single:single-1"])
    assert preview["eligible"] is True
    result = metadata.export("project-1", state["revision"], ["single:single-1"], preview["preview_fingerprint"], False, None)
    assert result["path"] == "output/metadata/youtube_metadata.json"
    exported = json.loads((tmp_path / result["path"]).read_text(encoding="utf-8"))
    assert exported["singles"][0]["single_id"] == "single-1"
    assert exported["albums"] == [] and exported["shorts"] == []
    reused = metadata.export("project-1", state["revision"], ["single:single-1"], metadata.export_preview("project-1", state["revision"], ["single:single-1"])["preview_fingerprint"], False, None)
    assert reused["reused"] is True


def test_reconcile_adds_new_target_and_preserves_existing_edits(service):
    metadata, creation = service
    state = initialize(service)
    state["targets"][2]["content"]["title"] = {"value": "Custom title", "origin": "edited", "source_fingerprint": None}
    state = metadata.put("project-1", state["revision"], "edit", state)
    creation.state["revision"] += 1
    creation.state["state_digest"] = "e" * 64
    creation.state["shorts"].append({"short_id": "short-2", "asset_id": "asset-2", "expected_sha256": SHA_B, "status": "active"})
    preview = metadata.reconcile_preview("project-1", state["revision"], [], [])
    assert any(item["kind"] == "add_target" and item["target_key"] == "short:short-2" for item in preview["changes"])
    reconciled = metadata.reconcile("project-1", state["revision"], "reconcile", preview["preview_fingerprint"], [], [])
    single = next(item for item in reconciled["targets"] if item["target_key"] == "single:single-1")
    assert single["content"]["title"]["value"] == "Custom title"
    assert any(item["target_key"] == "short:short-2" for item in reconciled["targets"])


def test_initialization_is_explicit_v4_only_and_basis_checked(service):
    metadata, creation = service
    with pytest.raises(WU4Error) as stale:
        metadata.initialize("project-1", "initialize", creation.state["revision"] - 1, creation.state["state_digest"])
    assert stale.value.code == "SOURCE_CHANGED"
    state = initialize(service)
    with pytest.raises(WU4Error) as duplicate:
        metadata.initialize("project-1", "again", creation.state["revision"], creation.state["state_digest"])
    assert duplicate.value.code == "METADATA_ALREADY_INITIALIZED"
    metadata.store.value = None
    creation.state["contract_version"] = "wrld-creation-state/3.0"
    with pytest.raises(WU4Error) as upgrade:
        initialize(service)
    assert upgrade.value.code == "CREATION_UPGRADE_REQUIRED"
    assert state["creation_basis"]["contract_version"] == "wrld-creation-state/4.0"


def test_approval_is_server_verified_and_active_release_association_is_required(service):
    metadata, creation = service
    state = initialize(service)
    single = next(item for item in state["targets"] if item["target_key"] == "single:single-1")
    single["approval"] = {"approved_fingerprint": "f" * 64, "approved_at": "2026-11-02T00:00:00Z"}
    with pytest.raises(WU4Error) as invented:
        metadata.put("project-1", state["revision"], "invented", state)
    assert invented.value.code == "METADATA_APPROVAL_INVALID"
    single["approval"] = None
    single["content"]["release_album_plan_id"] = {"value": "missing-album", "origin": "edited", "source_fingerprint": None}
    report = metadata.validate("project-1", state, "approval", [single["target_key"]])
    assert any(item["code"] == "TARGET_REFERENCE_INVALID" for item in report["diagnostics"])
    creation.state["albums"][0]["status"] = "archived"
    state["targets"][0]["lifecycle"] = "archived"
    single["content"]["release_album_plan_id"]["value"] = "album-canonical"
    report = metadata.validate("project-1", state, "approval", [single["target_key"]])
    assert any(item["code"] == "TARGET_REFERENCE_INVALID" for item in report["diagnostics"])


def test_export_collision_requires_explicit_compare_and_swap_replacement(service):
    metadata, _creation = service
    state = initialize(service)
    single = next(item for item in state["targets"] if item["target_key"] == "single:single-1")
    checked = metadata.validate("project-1", state, "approval", [single["target_key"]])
    single["approval"] = {"approved_fingerprint": checked["target_fingerprints"][0]["approval_fingerprint"], "approved_at": "2026-11-02T00:00:00Z"}
    state = metadata.put("project-1", state["revision"], "approve", state)
    first = metadata.export_preview("project-1", state["revision"], [single["target_key"]])
    metadata.export("project-1", state["revision"], [single["target_key"]], first["preview_fingerprint"], False, None)

    single = next(item for item in state["targets"] if item["target_key"] == "single:single-1")
    single["content"]["title"] = {"value": "Changed", "origin": "edited", "source_fingerprint": None}
    single["approval"] = None
    checked = metadata.validate("project-1", state, "approval", [single["target_key"]])
    single["approval"] = {"approved_fingerprint": checked["target_fingerprints"][0]["approval_fingerprint"], "approved_at": "2026-11-02T01:00:00Z"}
    state = metadata.put("project-1", state["revision"], "change", state)
    replacement = metadata.export_preview("project-1", state["revision"], [single["target_key"]])
    with pytest.raises(WU4Error) as collision:
        metadata.export("project-1", state["revision"], [single["target_key"]], replacement["preview_fingerprint"], False, None)
    assert collision.value.code == "METADATA_EXPORT_EXISTS"
    with pytest.raises(WU4Error) as changed:
        metadata.export("project-1", state["revision"], [single["target_key"]], replacement["preview_fingerprint"], True, "f" * 64)
    assert changed.value.code == "METADATA_EXPORT_CHANGED"
    result = metadata.export("project-1", state["revision"], [single["target_key"]], replacement["preview_fingerprint"], True, replacement["existing_sha256"])
    assert result["revision"] == 2 and result["reused"] is False
