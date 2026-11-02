from __future__ import annotations

import copy
import hashlib

import pytest

from wrld_video_studio.application.project_workspace import (
    CreationStates,
    ProjectPreferences,
    migrate_creation_state_v1_to_v2,
    migrate_creation_state_v2_to_v3,
    migrate_creation_state_v3_to_v4,
)
from wrld_video_studio.application.creation_v4 import (
    analyze_legacy_visual_templates,
    apply_legacy_visual_template_cleanup,
    visual_configuration_from_template,
    visual_configurations_equivalent,
)
from wrld_video_studio.domain.wu4 import WU4Error


class Catalogs:
    def __init__(self, *, enriched: bool = False) -> None:
        self.enriched = enriched

    def resolve(self, project_id: str):
        if project_id != "project-1":
            raise WU4Error("PROJECT_NOT_FOUND", "Unknown project.")
        enrichment = {"status": "recognized"} if self.enriched else None
        return {"enrichment": enrichment}, None


class Inventories:
    def __init__(self) -> None:
        self.verified: list[str] = []
        self.document = {
            "project_id": "project-1", "inventory_revision": 1,
            "assets": [
                {"asset_id": "asset-a", "kind": "audio", "presence": "present", "relative_path": "a.wav", "sha256": "a" * 64, "media": {"duration_seconds": 90}},
                {"asset_id": "asset-b", "kind": "audio", "presence": "present", "relative_path": "b.wav", "sha256": "b" * 64, "media": {"duration_seconds": 4}},
                {"asset_id": "image-a", "kind": "image", "presence": "present", "relative_path": "cover.png", "sha256": "c" * 64, "media": {}, "capabilities": {"inspection": {"status": "supported"}}},
            ],
        }

    def read(self, project_id: str):
        assert project_id == "project-1"
        return copy.deepcopy(self.document)

    def verify_asset(self, project_id: str, asset_id: str):
        assert project_id == "project-1"
        self.verified.append(asset_id)
        asset = next(item for item in self.document["assets"] if item["asset_id"] == asset_id)
        return copy.deepcopy(asset), None, asset["sha256"]


class Documents:
    def __init__(self) -> None:
        self.values: dict[str, dict] = {}

    def read(self, project_id: str):
        if project_id not in self.values:
            raise WU4Error("PROJECT_DOCUMENT_NOT_FOUND", "Missing.")
        return copy.deepcopy(self.values[project_id])

    def create(self, project_id: str, document: dict):
        value = copy.deepcopy(document); value["revision"] = 1; value["state_digest"] = "1" * 64
        self.values.setdefault(project_id, value)
        return self.read(project_id)

    def update(self, project_id: str, expected_revision: int, document: dict):
        current = self.values[project_id]
        if current["revision"] != expected_revision:
            raise WU4Error("REVISION_CONFLICT", "Stale.")
        value = copy.deepcopy(document); value["revision"] = expected_revision + 1; value["state_digest"] = "2" * 64
        self.values[project_id] = value
        return self.read(project_id)


def test_preferences_default_include_and_exclusions_survive_rescan_and_relink_identity():
    inventories, documents = Inventories(), Documents()
    service = ProjectPreferences(Catalogs(), inventories, documents)
    initial = service.get("project-1")
    assert initial["excluded_asset_ids"] == []
    saved = service.put("project-1", initial["revision"], "exclude", {**initial, "excluded_asset_ids": ["asset-a"]})
    inventories.document["inventory_revision"] = 2
    inventories.document["assets"][0]["relative_path"] = "moved/a.wav"
    assert service.get("project-1")["excluded_asset_ids"] == ["asset-a"]
    restored = service.put("project-1", saved["revision"], "restore", {**saved, "excluded_asset_ids": []})
    assert restored["excluded_asset_ids"] == []


def test_preferences_reject_unknown_identity_and_v2_handoff_is_project_level():
    service = ProjectPreferences(Catalogs(), Inventories(), Documents())
    initial = service.get("project-1")
    with pytest.raises(WU4Error) as failure:
        service.put("project-1", 1, "bad", {**initial, "excluded_asset_ids": ["asset-unknown"]})
    assert failure.value.code == "PROJECT_PREFERENCES_INVALID"
    assert service.handoff("project-1", 3, 2) == {
        "contract_version": "wrld-import-handoff/2.0", "project_id": "project-1",
        "inventory_revision": 3, "preferences_revision": 2,
    }


def test_creation_initializes_one_single_per_included_audio_only_once():
    inventories = Inventories()
    preference_documents, creation_documents = Documents(), Documents()
    preferences = ProjectPreferences(Catalogs(), inventories, preference_documents)
    preference_state = preferences.get("project-1")
    preferences.put(
        "project-1",
        preference_state["revision"],
        "exclude-b",
        {**preference_state, "excluded_asset_ids": ["asset-b"]},
    )
    service = CreationStates(
        Catalogs(), inventories, creation_documents, preferences=preferences
    )

    created = service.get("project-1")
    assert [item["asset_id"] for item in created["singles"]] == ["asset-a"]
    assert created["singles"][0]["status"] == "active"
    assert created["singles"][0]["customized"] is False
    assert created["singles"][0]["approved"] is False
    stable_id = created["singles"][0]["single_id"]

    latest_preferences = preferences.get("project-1")
    preferences.put(
        "project-1",
        latest_preferences["revision"],
        "include-b",
        {**latest_preferences, "excluded_asset_ids": []},
    )
    reopened = service.get("project-1")
    assert [item["single_id"] for item in reopened["singles"]] == [stable_id]
    assert [item["asset_id"] for item in reopened["singles"]] == ["asset-a"]

    archived = service.put(
        "project-1",
        reopened["revision"],
        "archive-single",
        {
            **reopened,
            "singles": [{**reopened["singles"][0], "status": "archived"}],
        },
    )
    assert service.get("project-1")["singles"] == archived["singles"]


def test_creation_legacy_primary_initialization_respects_import_exclusions():
    class Albums:
        def read(self, project_id: str):
            return {"project_id": project_id, "tracks": [{"id": "track-a", "audio": "a.wav"}]}

    class Editors:
        def get(self, project_id: str):
            return {"shorts": {"track-a": {
                "short_id": "short-stable-primary", "start_sample": 0,
                "sample_count": 20 * 48_000, "origin": "manual",
                "review_required": False, "settings": {}, "approval": None,
            }}}

    inventories = Inventories()
    preferences = ProjectPreferences(Catalogs(), inventories, Documents())
    preference_state = preferences.get("project-1")
    preferences.put(
        "project-1", preference_state["revision"], "exclude-a",
        {**preference_state, "excluded_asset_ids": ["asset-a"]},
    )
    service = CreationStates(
        Catalogs(enriched=True), inventories, Documents(), albums=Albums(),
        editors=Editors(), preferences=preferences,
    )

    created = service.get("project-1")
    assert [item["asset_id"] for item in created["singles"]] == ["asset-b"]
    assert created["shorts"] == []

    latest = preferences.get("project-1")
    preferences.put(
        "project-1", latest["revision"], "include-a",
        {**latest, "excluded_asset_ids": []},
    )
    reopened = service.get("project-1")
    assert [item["short_id"] for item in reopened["shorts"]] == ["short-stable-primary"]


def test_creation_preserves_duplicate_assignments_and_independent_archived_drafts():
    inventories, documents = Inventories(), Documents()
    service = CreationStates(Catalogs(), inventories, documents)
    initial = service.get("project-1")
    assert initial["preferred_short_duration_seconds"] == 45
    candidate = {**initial, "albums": [{
        "album_plan_id": "album-plan-1", "label": "Album One", "status": "active",
        "assignments": [
            {"assignment_id": "assignment-1", "asset_id": "asset-a", "expected_sha256": "a" * 64, "duplicate_acknowledged": False},
            {"assignment_id": "assignment-2", "asset_id": "asset-a", "expected_sha256": "a" * 64, "duplicate_acknowledged": True},
        ],
    }], "singles": [
        {"single_id": "single-1", "asset_id": "asset-a", "expected_sha256": "a" * 64, "status": "active", "customized": True, "approved": False, "settings": {}},
        {"single_id": "single-2", "asset_id": "asset-a", "expected_sha256": "a" * 64, "status": "archived", "customized": True, "approved": True, "settings": {"label": "alternate"}},
    ], "shorts": [{
        "short_id": "short-1", "asset_id": "asset-a", "expected_sha256": "a" * 64, "status": "active",
        "start_sample": 0, "sample_count": 45 * 48_000, "origin": "manual_required", "review_required": True,
        "customized": False, "approved": False, "settings": {},
    }]}
    saved = service.put("project-1", 1, "save-1", candidate)
    assert [item["asset_id"] for item in saved["albums"][0]["assignments"]] == ["asset-a", "asset-a"]
    assert saved["singles"][1]["status"] == "archived"
    assert saved["singles"][1]["settings"] == {"label": "alternate"}


def test_creation_reports_changed_and_missing_sources_without_discarding_drafts():
    inventories, documents = Inventories(), Documents()
    service = CreationStates(Catalogs(), inventories, documents)
    initial = service.get("project-1")
    saved = service.put("project-1", 1, "save", {**initial, "singles": [
        {"single_id": "single-1", "asset_id": "asset-a", "expected_sha256": "a" * 64, "status": "active", "customized": False, "approved": False, "settings": {}},
        {"single_id": "single-2", "asset_id": "asset-b", "expected_sha256": "b" * 64, "status": "active", "customized": False, "approved": False, "settings": {}},
    ]})
    inventories.document["assets"][0]["sha256"] = "f" * 64
    inventories.document["assets"][1]["presence"] = "missing"
    view = service.get("project-1")
    assert view["singles"] == saved["singles"]
    assert view["issues"] == [
        {"draft_id": "single-1", "asset_id": "asset-a", "relative_path": "a.wav", "code": "SOURCE_CHANGED"},
        {"draft_id": "single-2", "asset_id": "asset-b", "relative_path": "b.wav", "code": "SOURCE_MISSING"},
    ]
    with pytest.raises(WU4Error) as failure:
        service.put("project-1", saved["revision"], "stale-save", view)
    assert failure.value.code == "SOURCE_CHANGED"


def test_creation_enforces_short_boundaries_and_analyzer_seam():
    service = CreationStates(Catalogs(), Inventories(), Documents())
    initial = service.get("project-1")
    base = {"short_id": "short-1", "asset_id": "asset-a", "expected_sha256": "a" * 64, "status": "active", "start_sample": 0, "sample_count": 5 * 48_000, "origin": "analyzer", "review_required": False, "customized": False, "approved": False, "settings": {}}
    with pytest.raises(WU4Error) as failure:
        service.put("project-1", 1, "analyzer", {**initial, "shorts": [base]})
    assert failure.value.code == "ANALYZER_UNAVAILABLE"
    with pytest.raises(WU4Error) as failure:
        service.put("project-1", 1, "short", {**initial, "shorts": [{**base, "origin": "manual", "sample_count": 4 * 48_000}]})
    assert failure.value.code == "CREATION_STATE_INVALID"


def test_creation_initialization_preserves_existing_primary_short_identity_and_edits():
    class Albums:
        def read(self, project_id: str):
            assert project_id == "project-1"
            return {
                "project_id": project_id,
                "tracks": [{"id": "track-a", "audio": "a.wav"}],
            }

    class Editors:
        def get(self, project_id: str):
            assert project_id == "project-1"
            return {"shorts": {"track-a": {
                "short_id": "short-stable-primary",
                "track_id": "track-a",
                "role": "primary",
                "start_sample": 48_000,
                "sample_count": 25 * 48_000,
                "origin": "manual",
                "review_required": False,
                "settings": {"effects": {"camera": {"enabled": False}}},
                "approval": {"approved_digest": "d" * 64},
            }}}

    service = CreationStates(
        Catalogs(enriched=True),
        Inventories(),
        Documents(),
        albums=Albums(),
        editors=Editors(),
    )
    created = service.get("project-1")
    assert created["shorts"] == [{
        "short_id": "short-stable-primary",
        "asset_id": "asset-a",
        "expected_sha256": "a" * 64,
        "status": "active",
        "start_sample": 48_000,
        "sample_count": 25 * 48_000,
        "origin": "manual",
        "review_required": False,
        "customized": True,
        "approved": True,
        "settings": {"effects": {"camera": {"enabled": False}}},
    }]


def test_creation_reconciles_legacy_primary_after_initial_empty_inventory():
    class Albums:
        def read(self, project_id: str):
            return {"project_id": project_id, "tracks": [{"id": "track-a", "audio": "a.wav"}]}

    class Editors:
        def get(self, project_id: str):
            return {"shorts": {"track-a": {
                "short_id": "short-stable-primary", "start_sample": 0, "sample_count": 20 * 48_000,
                "origin": "manual", "review_required": False, "settings": {}, "approval": None,
            }}}

    inventories, documents = Inventories(), Documents()
    assets = inventories.document["assets"]
    inventories.document["assets"] = []
    service = CreationStates(Catalogs(enriched=True), inventories, documents, albums=Albums(), editors=Editors())
    initial = service.get("project-1")
    assert initial["shorts"] == []
    assert initial["singles"] == []
    inventories.document["assets"] = assets
    inventories.document["inventory_revision"] = 2
    reconciled = service.get("project-1")
    assert [item["short_id"] for item in reconciled["shorts"]] == ["short-stable-primary"]
    assert reconciled["singles"] == []
    assert service.get("project-1")["shorts"] == reconciled["shorts"]


def test_creation_v2_migration_maps_absent_and_flat_effects_and_preserves_legacy_settings():
    v1 = {
        "contract_version": "wrld-creation-state/1.0", "project_id": "project-1",
        "revision": 7, "save_id": "saved", "preferred_short_duration_seconds": 45,
        "albums": [{"album_plan_id": "album-1", "label": "Album", "status": "active", "assignments": []}],
        "singles": [{"single_id": "single-1", "asset_id": "asset-a", "expected_sha256": "a" * 64, "status": "active", "customized": True, "approved": True, "settings": {"label": "keep"}}],
        "shorts": [
            {"short_id": "short-default", "asset_id": "asset-a", "expected_sha256": "a" * 64, "status": "active", "start_sample": 0, "sample_count": 48_000 * 20, "origin": "manual", "review_required": False, "customized": True, "approved": True, "settings": {"caption": "unchanged"}},
            {"short_id": "short-flat", "asset_id": "asset-a", "expected_sha256": "a" * 64, "status": "archived", "start_sample": 48_000, "sample_count": 48_000 * 20, "origin": "manual", "review_required": False, "customized": True, "approved": False, "settings": {"effects": {"camera": False, "zoom": 1.03, "positionX": 25, "tintIntensity": 30}, "other": {"unknown": True}}},
            {"short_id": "short-historical", "asset_id": "asset-a", "expected_sha256": "a" * 64, "status": "active", "start_sample": 0, "sample_count": 48_000 * 20, "origin": "manual", "review_required": False, "customized": True, "approved": True, "settings": {"effects": {"camera": {"enabled": False}}, "legacy": "keep"}},
        ],
        "state_digest": "0" * 64,
    }
    migrated = migrate_creation_state_v1_to_v2(v1)
    assert v1["contract_version"] == "wrld-creation-state/1.0"
    assert migrated["contract_version"] == "wrld-creation-state/2.0"
    assert migrated["albums"][0]["visual_template_id"] is None
    assert migrated["singles"][0]["settings"] == {"label": "keep"}
    assert [item["short_id"] for item in migrated["shorts"]] == ["short-default", "short-flat", "short-historical"]
    assert migrated["shorts"][2]["visual_template_id"] is None
    assert migrated["shorts"][2]["settings"] == v1["shorts"][2]["settings"]
    default_template = next(item for item in migrated["visual_templates"] if item["visual_template_id"] == migrated["shorts"][0]["visual_template_id"])
    assert default_template["camera"] == {"mode": "bounded", "max_zoom": 1.04}
    assert default_template["visualizer"] == {"enabled": True, "bar_count": 24, "opacity": 0.65}
    assert default_template["progress"] == {"enabled": True}
    assert default_template["color_treatment"] == {"mode": "custom", "hex": "#416E9D", "intensity": 0.18}
    flat_template = next(item for item in migrated["visual_templates"] if item["visual_template_id"] == migrated["shorts"][1]["visual_template_id"])
    assert flat_template["geometry"]["focal_x"] == 0.25
    assert flat_template["camera"] == {"mode": "static", "max_zoom": 1.03}
    assert flat_template["color_treatment"]["intensity"] == 0.3
    assert migrate_creation_state_v1_to_v2(v1) == migrated


def test_creation_v2_migration_rejects_invalid_flat_values_precisely():
    service = CreationStates(Catalogs(), Inventories(), Documents())
    state = service.get("project-1")
    state["shorts"] = [{
        "short_id": "short-invalid", "asset_id": "asset-a", "expected_sha256": "a" * 64,
        "status": "active", "start_sample": 0, "sample_count": 20 * 48_000,
        "origin": "manual", "review_required": False, "customized": True, "approved": False,
        "settings": {"effects": {"zoom": float("inf")}},
    }]
    with pytest.raises(WU4Error) as failure:
        migrate_creation_state_v1_to_v2(state)
    assert failure.value.code == "CREATION_STATE_INVALID"
    assert failure.value.details == {"short_id": "short-invalid", "path": "settings.effects", "reason": "zoom_out_of_range"}


def test_creation_v2_requires_exact_explicit_upgrade_and_validates_new_images_securely():
    inventories, documents = Inventories(), Documents()
    service = CreationStates(Catalogs(), inventories, documents)
    v1 = service.get("project-1")
    v1["shorts"] = [{
        "short_id": "short-1", "asset_id": "asset-a", "expected_sha256": "a" * 64,
        "status": "active", "start_sample": 0, "sample_count": 20 * 48_000,
        "origin": "manual", "review_required": False, "customized": True, "approved": True,
        "settings": {},
    }]
    documents.values["project-1"] = copy.deepcopy(v1)
    upgrade = migrate_creation_state_v1_to_v2(v1)
    altered = copy.deepcopy(upgrade)
    altered["shorts"][0]["approved"] = False
    with pytest.raises(WU4Error) as failure:
        service.put("project-1", 1, "bad-upgrade", altered)
    assert failure.value.code == "CREATION_STATE_INVALID"

    upgraded = service.put("project-1", 1, "upgrade", upgrade)
    assert upgraded["shorts"][0]["approved"] is True
    assert upgraded["issues"][0]["code"] == "VISUAL_SOURCE_REQUIRED"
    candidate = copy.deepcopy(upgraded)
    candidate["visual_templates"][0]["background_image"] = {"asset_id": "image-a", "expected_sha256": "c" * 64}
    with pytest.raises(WU4Error) as failure:
        service.put("project-1", 2, "image-with-stale-approval", candidate)
    assert failure.value.code == "CREATION_STATE_INVALID"
    candidate["shorts"][0]["approved"] = False
    candidate["shorts"][0]["customized"] = True
    saved = service.put("project-1", 2, "select-image", candidate)
    assert inventories.verified == ["image-a"]
    assert saved["issues"] == []

    inventories.document["assets"][2]["presence"] = "missing"
    assert service.get("project-1")["issues"][0]["code"] == "VISUAL_SOURCE_MISSING"
    inventories.document["assets"][2]["presence"] = "present"
    excluded_view = CreationStates._view(saved, inventories.read("project-1"), {"image-a"})
    assert excluded_view["issues"][0]["code"] == "VISUAL_SOURCE_EXCLUDED"
    inventories.document["assets"][2]["sha256"] = "d" * 64
    stale = service.get("project-1")
    assert stale["issues"][0]["code"] == "VISUAL_SOURCE_CHANGED"
    assert stale["issues"][0]["affected_targets"] == [{"kind": "short", "id": "short-1", "status": "active"}]
    # Unrelated changes remain saveable without silently accepting the stale image bytes.
    stale["preferred_short_duration_seconds"] = 50
    saved_stale = service.put("project-1", 3, "unrelated", stale)
    assert saved_stale["visual_templates"][0]["background_image"]["expected_sha256"] == "c" * 64
    assert saved_stale["issues"][0]["code"] == "VISUAL_SOURCE_CHANGED"
    repaired = copy.deepcopy(saved_stale)
    repaired["visual_templates"][0]["background_image"]["expected_sha256"] = "d" * 64
    repaired = service.put("project-1", 4, "accept-changed-image", repaired)
    assert repaired["issues"] == []
    assert inventories.verified == ["image-a", "image-a"]


def test_creation_v2_customize_copy_preserves_approval_but_later_pixel_edits_do_not():
    inventories, documents = Inventories(), Documents()
    service = CreationStates(Catalogs(), inventories, documents)
    v1 = service.get("project-1")
    v1["shorts"] = [{
        "short_id": "short-1", "asset_id": "asset-a", "expected_sha256": "a" * 64,
        "status": "active", "start_sample": 0, "sample_count": 20 * 48_000,
        "origin": "manual", "review_required": False, "customized": True, "approved": True,
        "settings": {},
    }]
    documents.values["project-1"] = copy.deepcopy(v1)
    upgraded = service.put("project-1", 1, "upgrade", migrate_creation_state_v1_to_v2(v1))
    copied = copy.deepcopy(upgraded)
    clone = copy.deepcopy(copied["visual_templates"][0])
    clone["visual_template_id"] = "visual-template-copy"
    clone["label"] = "Independent copy"
    copied["visual_templates"].append(clone)
    copied["shorts"][0]["visual_template_id"] = clone["visual_template_id"]
    customized = service.put("project-1", 2, "customize", copied)
    assert customized["shorts"][0]["approved"] is True

    edited = copy.deepcopy(customized)
    edited["visual_templates"][1]["geometry"]["focal_x"] = 0.2
    with pytest.raises(WU4Error) as failure:
        service.put("project-1", 3, "pixel-edit", edited)
    assert failure.value.code == "CREATION_STATE_INVALID"


def test_creation_v2_accepts_atomic_shared_assignment_and_preserves_archived_and_noop_targets():
    inventories, documents = Inventories(), Documents()
    service = CreationStates(Catalogs(), inventories, documents)
    v1 = service.get("project-1")
    v1["shorts"] = [
        {
            "short_id": "short-1", "asset_id": "asset-a", "expected_sha256": "a" * 64,
            "status": "active", "start_sample": 0, "sample_count": 20 * 48_000,
            "origin": "manual", "review_required": False, "customized": True, "approved": True,
            "settings": {},
        },
        {
            "short_id": "short-2", "asset_id": "asset-a", "expected_sha256": "a" * 64,
            "status": "active", "start_sample": 20 * 48_000, "sample_count": 20 * 48_000,
            "origin": "manual", "review_required": False, "customized": False, "approved": True,
            "settings": {},
        },
        {
            "short_id": "short-archived", "asset_id": "asset-a", "expected_sha256": "a" * 64,
            "status": "archived", "start_sample": 40 * 48_000, "sample_count": 20 * 48_000,
            "origin": "manual", "review_required": False, "customized": False, "approved": True,
            "settings": {},
        },
    ]
    documents.values["project-1"] = copy.deepcopy(v1)
    upgraded = service.put("project-1", 1, "upgrade", migrate_creation_state_v1_to_v2(v1))
    shared = copy.deepcopy(upgraded)
    shared_id = shared["shorts"][0]["visual_template_id"]
    archived_id = shared["shorts"][2]["visual_template_id"]
    shared["shorts"][1].update({"visual_template_id": shared_id, "customized": True, "approved": False})
    saved = service.put("project-1", 2, "bulk-shared", shared)
    assert saved["shorts"][0]["visual_template_id"] == shared_id
    assert saved["shorts"][0]["approved"] is True
    assert saved["shorts"][1]["visual_template_id"] == shared_id
    assert saved["shorts"][1]["customized"] is True
    assert saved["shorts"][1]["approved"] is False
    assert saved["shorts"][2]["visual_template_id"] == archived_id
    assert saved["shorts"][2]["approved"] is True


def test_creation_v2_rejects_unknown_template_references_and_wrong_aspect_ratios():
    inventories, documents = Inventories(), Documents()
    service = CreationStates(Catalogs(), inventories, documents)
    v1 = service.get("project-1")
    v1["shorts"] = [{
        "short_id": "short-1", "asset_id": "asset-a", "expected_sha256": "a" * 64,
        "status": "active", "start_sample": 0, "sample_count": 20 * 48_000,
        "origin": "manual", "review_required": False, "customized": True, "approved": False,
        "settings": {},
    }]
    documents.values["project-1"] = copy.deepcopy(v1)
    upgraded = service.put("project-1", 1, "upgrade", migrate_creation_state_v1_to_v2(v1))
    unknown = copy.deepcopy(upgraded)
    unknown["shorts"][0]["visual_template_id"] = "visual-template-unknown"
    with pytest.raises(WU4Error) as failure:
        service.put("project-1", 2, "unknown", unknown)
    assert failure.value.code == "CREATION_STATE_INVALID"
    wrong_aspect = copy.deepcopy(upgraded)
    wrong_aspect["visual_templates"][0]["canvas"]["aspect_ratio"] = "16:9"
    with pytest.raises(WU4Error) as failure:
        service.put("project-1", 2, "wrong-aspect", wrong_aspect)
    assert failure.value.code == "CREATION_STATE_INVALID"


def _visual_template(template_id: str, aspect: str, label: str) -> dict:
    return {
        "visual_template_id": template_id,
        "label": label,
        "canvas": {"aspect_ratio": aspect},
        "background_image": None,
        "geometry": {"fit_mode": "cover", "focal_x": 0.25, "focal_y": 0.75},
        "camera": {"mode": "bounded", "max_zoom": 1.03},
        "visualizer": {"enabled": True, "bar_count": 32, "opacity": 0.7},
        "progress": {"enabled": True},
        "color_treatment": {"mode": "custom", "hex": "#123456", "intensity": 0.2},
    }


def _creation_v2_family_fixture() -> dict:
    single = lambda identity, template, status="active", approved=True, customized=True: {
        "single_id": identity, "asset_id": "asset-a", "expected_sha256": "a" * 64,
        "status": status, "customized": customized, "approved": approved,
        "settings": {"preserve": identity}, "visual_template_id": template,
    }
    short = lambda identity, status="active": {
        "short_id": identity, "asset_id": "asset-a", "expected_sha256": "a" * 64,
        "status": status, "start_sample": 0, "sample_count": 20 * 48_000,
        "origin": "manual", "review_required": False, "customized": True,
        "approved": True, "settings": {"preserve": identity},
        "visual_template_id": "visual-short",
    }
    return {
        "contract_version": "wrld-creation-state/2.0", "project_id": "project-1",
        "revision": 2, "save_id": "v2", "preferred_short_duration_seconds": 45,
        "visual_templates": [
            _visual_template("visual-shared", "16:9", "Shared"),
            _visual_template("visual-album", "16:9", "Album only"),
            _visual_template("visual-single", "16:9", "Single only"),
            _visual_template("visual-short", "9:16", "Short only"),
            _visual_template("visual-unused", "16:9", "Unused"),
        ],
        "albums": [
            {"album_plan_id": "album-shared", "label": "Shared active", "status": "active", "assignments": [], "visual_template_id": "visual-shared"},
            {"album_plan_id": "album-shared-archived", "label": "Shared archived", "status": "archived", "assignments": [], "visual_template_id": "visual-shared"},
            {"album_plan_id": "album-only", "label": "Album only", "status": "active", "assignments": [], "visual_template_id": "visual-album"},
        ],
        "singles": [
            single("single-shared", "visual-shared", approved=True, customized=False),
            single("single-shared-archived", "visual-shared", status="archived"),
            single("single-only", "visual-single", approved=False),
        ],
        "shorts": [short("short-active"), short("short-archived", "archived")],
        "state_digest": "2" * 64,
    }


def _migration_id(source_id: str, role: str) -> str:
    preimage = f"project-1\0{source_id}\0wrld-creation-state/3.0\0{role}".encode("utf-8")
    prefix = "visual-template-family-" if role == "family" else "visual-template-"
    return prefix + hashlib.sha256(preimage).hexdigest()[:32]


def test_creation_v3_migration_is_deterministic_lossless_and_splits_shared_landscape_consumers():
    v2 = _creation_v2_family_fixture()
    original = copy.deepcopy(v2)
    migrated = migrate_creation_state_v2_to_v3(v2)

    assert v2 == original
    assert migrated == migrate_creation_state_v2_to_v3(v2)
    assert migrated["contract_version"] == "wrld-creation-state/3.0"
    assert [item["name"] for item in migrated["visual_template_families"]] == [
        "Shared", "Album only", "Single only", "Short only", "Unused",
    ]
    assert [item["visual_template_id"] for item in migrated["visual_templates"][:5]] == [
        "visual-shared", "visual-album", "visual-single", "visual-short", "visual-unused",
    ]

    families = {item["name"]: item for item in migrated["visual_template_families"]}
    shared = families["Shared"]
    assert shared["visual_template_family_id"] == _migration_id("visual-shared", "family")
    assert shared["members"]["single_visual_template_id"] == "visual-shared"
    assert shared["members"]["album_visual_template_id"] == _migration_id("visual-shared", "album")
    assert families["Album only"]["members"]["album_visual_template_id"] == "visual-album"
    assert families["Single only"]["members"]["single_visual_template_id"] == "visual-single"
    assert families["Short only"]["members"]["short_visual_template_id"] == "visual-short"
    assert families["Unused"]["members"]["album_visual_template_id"] == "visual-unused"

    assert [item["visual_template_id"] for item in migrated["visual_templates"][5:7]] == [
        _migration_id("visual-shared", "album"), _migration_id("visual-shared", "short"),
    ]
    shared_album = next(item for item in migrated["visual_templates"] if item["visual_template_id"] == _migration_id("visual-shared", "album"))
    expected_album = copy.deepcopy(original["visual_templates"][0])
    expected_album["visual_template_id"] = _migration_id("visual-shared", "album")
    assert shared_album == expected_album
    assert {item["visual_template_id"] for item in migrated["albums"][:2]} == {_migration_id("visual-shared", "album")}
    assert [item["visual_template_id"] for item in migrated["singles"][:2]] == ["visual-shared", "visual-shared"]
    assert [(item["status"], item["approved"], item["customized"]) for item in migrated["singles"][:2]] == [
        ("active", True, False), ("archived", True, True),
    ]
    assert [(item["status"], item["approved"], item["customized"]) for item in migrated["shorts"]] == [
        ("active", True, True), ("archived", True, True),
    ]


def test_creation_v3_migration_rejects_generated_identity_collision_and_v3_is_a_noop():
    v2 = _creation_v2_family_fixture()
    collision = _migration_id("visual-shared", "album")
    v2["albums"][0]["album_plan_id"] = collision
    with pytest.raises(WU4Error) as failure:
        migrate_creation_state_v2_to_v3(v2)
    assert failure.value.code == "CREATION_STATE_INVALID"
    assert failure.value.details == {
        "source_visual_template_id": "visual-shared",
        "generated_identity": collision,
        "role": "album",
    }

    migrated = migrate_creation_state_v2_to_v3(_creation_v2_family_fixture())
    assert migrate_creation_state_v2_to_v3(migrated) == migrated


def test_creation_upgrade_chain_requires_v1_to_v2_before_v3():
    service = CreationStates(Catalogs(), Inventories(), Documents())
    v1 = service.get("project-1")
    v2 = migrate_creation_state_v1_to_v2(v1)
    v3 = migrate_creation_state_v2_to_v3(v2)
    assert v2["contract_version"] == "wrld-creation-state/2.0"
    assert v3["contract_version"] == "wrld-creation-state/3.0"
    assert v3["visual_template_families"] == []
    with pytest.raises(WU4Error) as failure:
        service.put("project-1", v1["revision"], "direct-v3", v3)
    assert failure.value.code == "CREATION_STATE_INVALID"


def _saved_creation_v3() -> tuple[CreationStates, Documents, dict]:
    documents = Documents()
    v2 = _creation_v2_family_fixture()
    documents.values["project-1"] = copy.deepcopy(v2)
    service = CreationStates(Catalogs(), Inventories(), documents)
    saved = service.put("project-1", v2["revision"], "upgrade-v3", migrate_creation_state_v2_to_v3(v2))
    return service, documents, saved


def test_creation_v2_read_does_not_implicitly_upgrade_or_write_v3():
    documents = Documents()
    v2 = _creation_v2_family_fixture()
    documents.values["project-1"] = copy.deepcopy(v2)
    service = CreationStates(Catalogs(), Inventories(), documents)
    before = copy.deepcopy(documents.values)
    loaded = service.get("project-1")
    assert loaded["contract_version"] == "wrld-creation-state/2.0"
    assert documents.values == before


def test_creation_v3_read_does_not_implicitly_upgrade_or_write_v4():
    documents = Documents()
    v3 = migrate_creation_state_v2_to_v3(_creation_v2_family_fixture())
    documents.values["project-1"] = copy.deepcopy(v3)
    service = CreationStates(Catalogs(), Inventories(), documents)
    before = copy.deepcopy(documents.values)
    loaded = service.get("project-1")
    assert loaded["contract_version"] == "wrld-creation-state/3.0"
    assert documents.values == before


def test_creation_v3_upgrade_preserves_stale_visual_dependencies_without_reselecting_them():
    documents = Documents()
    v2 = _creation_v2_family_fixture()
    v2["visual_templates"][0]["background_image"] = {
        "asset_id": "image-missing", "expected_sha256": "f" * 64,
    }
    documents.values["project-1"] = copy.deepcopy(v2)
    service = CreationStates(Catalogs(), Inventories(), documents)
    saved = service.put("project-1", v2["revision"], "upgrade-stale", migrate_creation_state_v2_to_v3(v2))
    assert saved["contract_version"] == "wrld-creation-state/3.0"
    assert any(issue["code"] == "VISUAL_SOURCE_MISSING" for issue in saved["issues"])
    assert next(item for item in saved["visual_templates"] if item["visual_template_id"] == "visual-shared")["background_image"] == {
        "asset_id": "image-missing", "expected_sha256": "f" * 64,
    }


def test_creation_v3_persists_registry_allows_duplicate_names_and_ungrouped_templates():
    service, _documents, saved = _saved_creation_v3()
    assert saved["revision"] == 3
    assert service.get("project-1")["visual_template_families"] == saved["visual_template_families"]

    candidate = copy.deepcopy(saved)
    candidate["visual_template_families"][1]["name"] = candidate["visual_template_families"][0]["name"]
    candidate["visual_templates"].append(_visual_template("visual-standalone", "16:9", "Standalone"))
    updated = service.put("project-1", saved["revision"], "v3-round-trip", candidate)
    assert updated["visual_template_families"][0]["name"] == updated["visual_template_families"][1]["name"]
    assert updated["visual_templates"][-1]["visual_template_id"] == "visual-standalone"

    with pytest.raises(WU4Error) as failure:
        service.put("project-1", saved["revision"], "stale", updated)
    assert failure.value.code == "REVISION_CONFLICT"

    downgrade = copy.deepcopy(updated)
    downgrade.pop("issues", None)
    downgrade.pop("visual_template_families")
    downgrade["contract_version"] = "wrld-creation-state/2.0"
    before = copy.deepcopy(_documents.values["project-1"])
    with pytest.raises(WU4Error) as failure:
        service.put("project-1", updated["revision"], "lossy-v2", downgrade)
    assert failure.value.code == "CREATION_STATE_INVALID"
    assert _documents.values["project-1"] == before


@pytest.mark.parametrize("mutation", [
    lambda value: value["visual_template_families"][1].update({"visual_template_family_id": value["visual_template_families"][0]["visual_template_family_id"]}),
    lambda value: value["visual_template_families"][0]["members"].update({"single_visual_template_id": value["visual_template_families"][0]["members"]["album_visual_template_id"]}),
    lambda value: value["visual_template_families"][0]["members"].update({"album_visual_template_id": value["visual_template_families"][0]["members"]["short_visual_template_id"]}),
    lambda value: value["visual_template_families"][0]["members"].update({"single_visual_template_id": value["visual_template_families"][0]["members"]["short_visual_template_id"]}),
    lambda value: value["visual_template_families"][0]["members"].update({"short_visual_template_id": value["visual_template_families"][0]["members"]["album_visual_template_id"]}),
    lambda value: value["visual_template_families"][1]["members"].update({"album_visual_template_id": value["visual_template_families"][0]["members"]["album_visual_template_id"]}),
    lambda value: value["visual_template_families"][0]["members"].update({"album_visual_template_id": "visual-missing"}),
    lambda value: value["albums"][0].update({"visual_template_id": "visual-missing"}),
])
def test_creation_v3_rejects_invalid_family_graph_atomically(mutation):
    service, documents, saved = _saved_creation_v3()
    before = copy.deepcopy(documents.values["project-1"])
    candidate = copy.deepcopy(saved)
    mutation(candidate)
    with pytest.raises(WU4Error) as failure:
        service.put("project-1", saved["revision"], "invalid-family", candidate)
    assert failure.value.code == "CREATION_STATE_INVALID"
    assert documents.values["project-1"] == before


def _creation_v4_fixture() -> dict:
    return migrate_creation_state_v3_to_v4(
        migrate_creation_state_v2_to_v3(_creation_v2_family_fixture())
    )


def test_creation_v4_migration_is_deterministic_lossless_and_preserves_every_target():
    v3 = migrate_creation_state_v2_to_v3(_creation_v2_family_fixture())
    original = copy.deepcopy(v3)
    first = migrate_creation_state_v3_to_v4(v3)

    assert v3 == original
    assert first == migrate_creation_state_v3_to_v4(v3)
    assert migrate_creation_state_v3_to_v4(first) == first
    assert first["contract_version"] == "wrld-creation-state/4.0"
    assert first["visual_templates"] == v3["visual_templates"]
    assert first["visual_template_families"] == v3["visual_template_families"]
    for collection, identity in (("albums", "album_plan_id"), ("singles", "single_id"), ("shorts", "short_id")):
        source = {item[identity]: item for item in v3[collection]}
        for target in first[collection]:
            previous = source[target[identity]]
            template = next(item for item in v3["visual_templates"] if item["visual_template_id"] == previous["visual_template_id"])
            assert "visual_template_id" not in target
            assert target["source_visual_template_id"] == previous["visual_template_id"]
            assert target["visual_configuration"] == visual_configuration_from_template(template)
            assert visual_configurations_equivalent(target["visual_configuration"], template)
            for field in set(previous) - {"visual_template_id"}:
                assert target[field] == previous[field]


def test_creation_v4_dispatch_requires_v3_to_be_saved_before_v4():
    documents = Documents()
    v2 = _creation_v2_family_fixture()
    documents.values["project-1"] = copy.deepcopy(v2)
    service = CreationStates(Catalogs(), Inventories(), documents)
    v4 = migrate_creation_state_v3_to_v4(migrate_creation_state_v2_to_v3(v2))
    before = copy.deepcopy(documents.values["project-1"])
    with pytest.raises(WU4Error) as failure:
        service.put("project-1", v2["revision"], "skip-v3", v4)
    assert failure.value.code == "CREATION_STATE_INVALID"
    assert documents.values["project-1"] == before


def test_creation_v4_migration_distinguishes_dangling_null_and_direct_authoritative_settings():
    base = migrate_creation_state_v2_to_v3(_creation_v2_family_fixture())
    original = copy.deepcopy(base)
    base["shorts"][0]["visual_template_id"] = "visual-missing"
    dangling_source = copy.deepcopy(base)
    with pytest.raises(WU4Error) as dangling:
        migrate_creation_state_v3_to_v4(base)
    assert base == dangling_source
    assert dangling.value.details == {
        "target_kind": "short", "target_id": "short-active",
        "visual_template_id": "visual-missing", "reason": "dangling_visual_template_reference",
    }
    assert original["shorts"][0]["visual_template_id"] != "visual-missing"

    null_source = copy.deepcopy(original)
    null_source["shorts"][0]["visual_template_id"] = None
    null_snapshot = copy.deepcopy(null_source)
    with pytest.raises(WU4Error) as missing:
        migrate_creation_state_v3_to_v4(null_source)
    assert null_source == null_snapshot
    assert missing.value.details["reason"] == "authoritative_visual_configuration_missing"
    assert missing.value.details["target_id"] == "short-active"

    direct = copy.deepcopy(original)
    template = next(item for item in direct["visual_templates"] if item["visual_template_id"] == direct["shorts"][0]["visual_template_id"])
    direct["shorts"][0]["visual_template_id"] = None
    direct["shorts"][0]["visual_configuration"] = visual_configuration_from_template(template)
    migrated = migrate_creation_state_v3_to_v4(direct)
    assert migrated["shorts"][0]["source_visual_template_id"] is None
    assert migrated["shorts"][0]["visual_configuration"] == visual_configuration_from_template(template)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["background_image"].update({"expected_sha256": "d" * 64}),
        lambda value: value["geometry"].update({"focal_x": 0.75}),
        lambda value: value["camera"].update({"max_zoom": 1.05}),
        lambda value: value["visualizer"].update({"bar_count": 40}),
        lambda value: value["progress"].update({"enabled": False}),
        lambda value: value.update({"color_treatment": {"mode": "none"}}),
        lambda value: value.update({"unknown_visual_field": True}),
    ],
)
def test_visual_configuration_equivalence_includes_every_visual_field_and_rejects_unknowns(mutation):
    template = _visual_template("visual-a", "9:16", "A")
    template["background_image"] = {"asset_id": "image-a", "expected_sha256": "c" * 64}
    configuration = visual_configuration_from_template(template)
    assert visual_configurations_equivalent(template, configuration)
    renamed = copy.deepcopy(template)
    renamed.update({"visual_template_id": "visual-b", "label": "B"})
    assert visual_configurations_equivalent(template, renamed)
    changed = copy.deepcopy(configuration)
    mutation(changed)
    assert not visual_configurations_equivalent(template, changed)


def test_creation_v4_save_reload_conflict_aspect_and_approval_guards():
    service, documents, v3 = _saved_creation_v3()
    v4_candidate = migrate_creation_state_v3_to_v4(v3)
    saved = service.put("project-1", v3["revision"], "upgrade-v4", v4_candidate)
    assert saved["contract_version"] == "wrld-creation-state/4.0"
    assert service.get("project-1")["visual_template_families"] == saved["visual_template_families"]

    changed = copy.deepcopy(saved)
    changed["singles"][0]["visual_configuration"]["geometry"]["focal_x"] = 0.9
    with pytest.raises(WU4Error) as approval:
        service.put("project-1", saved["revision"], "approval-not-cleared", changed)
    assert approval.value.code == "CREATION_STATE_INVALID"
    assert documents.values["project-1"]["revision"] == saved["revision"]

    wrong_aspect = copy.deepcopy(saved)
    wrong_aspect["shorts"][0]["visual_configuration"]["canvas"]["aspect_ratio"] = "16:9"
    with pytest.raises(WU4Error) as aspect:
        service.put("project-1", saved["revision"], "wrong-aspect", wrong_aspect)
    assert aspect.value.code == "CREATION_STATE_INVALID"

    with pytest.raises(WU4Error) as conflict:
        service.put("project-1", saved["revision"] - 1, "stale", saved)
    assert conflict.value.code == "REVISION_CONFLICT"


def test_creation_v4_unresolved_provenance_is_historical_only_and_template_edits_do_not_change_approvals():
    service, _documents, v3 = _saved_creation_v3()
    saved = service.put("project-1", v3["revision"], "upgrade-v4", migrate_creation_state_v3_to_v4(v3))
    candidate = copy.deepcopy(saved)
    approved = next(item for item in candidate["singles"] if item["approved"])
    approved_configuration = copy.deepcopy(approved["visual_configuration"])
    approved["source_visual_template_id"] = "removed-template-history"
    candidate["visual_templates"][0]["geometry"]["focal_x"] = 0.875

    updated = service.put("project-1", saved["revision"], "provenance-only", candidate)
    updated_approved = next(item for item in updated["singles"] if item["single_id"] == approved["single_id"])
    assert updated_approved["approved"] is True
    assert updated_approved["source_visual_template_id"] == "removed-template-history"
    assert updated_approved["visual_configuration"] == approved_configuration


def test_creation_v4_validates_new_owned_backgrounds_and_preserves_unchanged_stale_dependencies():
    inventories = Inventories()
    documents = Documents()
    v3 = migrate_creation_state_v2_to_v3(_creation_v2_family_fixture())
    documents.values["project-1"] = copy.deepcopy(v3)
    service = CreationStates(Catalogs(), inventories, documents)
    saved = service.put("project-1", v3["revision"], "upgrade-v4", migrate_creation_state_v3_to_v4(v3))
    candidate = copy.deepcopy(saved)
    candidate["albums"][0]["visual_configuration"]["background_image"] = {
        "asset_id": "image-a", "expected_sha256": "c" * 64,
    }
    with_background = service.put("project-1", saved["revision"], "owned-background", candidate)
    assert inventories.verified == ["image-a"]

    inventories.document["assets"][2]["presence"] = "missing"
    unrelated = copy.deepcopy(with_background)
    unrelated["visual_template_families"][0]["name"] = "Renamed while source is missing"
    preserved = service.put("project-1", with_background["revision"], "preserve-stale", unrelated)
    assert preserved["albums"][0]["visual_configuration"]["background_image"] == {
        "asset_id": "image-a", "expected_sha256": "c" * 64,
    }
    assert any(issue["code"] == "VISUAL_SOURCE_MISSING" for issue in preserved["issues"])


def _v2_generated_template_id(short_id: str) -> str:
    preimage = f"project-1\0{short_id}\0wrld-creation-state/2.0".encode("utf-8")
    return "visual-template-" + hashlib.sha256(preimage).hexdigest()[:32]


def test_legacy_cleanup_is_conservative_previewable_authorized_and_stale_safe():
    v4 = _creation_v4_fixture()
    short = v4["shorts"][0]
    generated_id = _v2_generated_template_id(short["short_id"])
    generated = copy.deepcopy(v4["visual_templates"][0])
    generated.update({
        "visual_template_id": generated_id,
        "label": f"Short visual {short['short_id']}"[:128],
    })
    generated.update(copy.deepcopy(short["visual_configuration"]))
    v4["visual_templates"].append(generated)
    short["source_visual_template_id"] = generated_id
    short["visual_configuration"] = visual_configuration_from_template(generated)

    name_only = copy.deepcopy(generated)
    name_only["visual_template_id"] = "visual-name-only"
    name_only["label"] = "Short visual short-name-only"
    v4["visual_templates"].append(name_only)
    unique = copy.deepcopy(generated)
    unique["visual_template_id"] = "visual-unique"
    unique["label"] = "Intentional unique preset"
    unique["geometry"]["focal_x"] = 0.333
    v4["visual_templates"].append(unique)

    plan = analyze_legacy_visual_templates(v4)
    assert plan == analyze_legacy_visual_templates(v4)
    classification = {item.visual_template_id: item.classification for item in plan.candidates}
    assert classification[generated_id] == "PROVEN_DISPOSABLE"
    assert classification["visual-name-only"] == "REVIEW_REQUIRED"
    assert classification["visual-unique"] == "RETAIN"
    family_member = v4["visual_template_families"][0]["members"]["album_visual_template_id"]
    assert classification[family_member] == "RETAIN"
    assert next(item for item in plan.candidates if item.visual_template_id == generated_id).likely_generated is True
    assert any(item.archived_compositions for item in plan.candidates)
    assert plan.provenance_only_reference_count == plan.active_reference_count + plan.archived_reference_count
    assert plan.total_templates_after == plan.total_templates_before - 1

    snapshot = copy.deepcopy(v4)
    with pytest.raises(WU4Error) as unauthorized:
        apply_legacy_visual_template_cleanup(v4, plan, authorized=False)
    assert unauthorized.value.code == "CREATION_STATE_INVALID"
    assert v4 == snapshot

    stale = copy.deepcopy(v4)
    stale["revision"] += 1
    with pytest.raises(WU4Error) as stale_failure:
        apply_legacy_visual_template_cleanup(stale, plan, authorized=True)
    assert stale_failure.value.code == "REVISION_CONFLICT"

    cleaned = apply_legacy_visual_template_cleanup(v4, plan, authorized=True)
    assert v4 == snapshot
    assert generated_id not in {item["visual_template_id"] for item in cleaned["visual_templates"]}
    assert short["source_visual_template_id"] == generated_id
    cleaned_short = next(item for item in cleaned["shorts"] if item["short_id"] == short["short_id"])
    assert cleaned_short["source_visual_template_id"] == generated_id
    assert cleaned_short["visual_configuration"] == short["visual_configuration"]
    assert cleaned_short["approved"] == short["approved"]
