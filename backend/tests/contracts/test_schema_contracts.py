import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from wrld_video_studio.domain.errors import ERROR_CODES, StudioError


ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / "fixtures"


def test_wu1_schemas_are_valid_draft_2020_12_documents(schema_dir):
    for schema_path in schema_dir.glob("*.schema.json"):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)


def test_override_store_example_matches_contract(override_schema):
    schema = json.loads(override_schema.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    example = json.loads((FIXTURES / "override-store-valid.json").read_text(encoding="utf-8"))
    validator.validate(example)


@pytest.mark.parametrize(
    "invalid",
    [
        {"schema_version": "2.0", "album_id": "a", "revision": 0, "overrides": {}},
        {"schema_version": "1.0", "album_id": "a", "revision": -1, "overrides": {}},
        {"schema_version": "1.0", "album_id": "a", "revision": 0, "overrides": [], "extra": True},
    ],
)
def test_override_store_schema_rejects_invalid_payloads(override_schema, invalid):
    schema = json.loads(override_schema.read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(invalid)


def test_api_error_shape_matches_contract(schema_dir):
    schema = json.loads((schema_dir / "api-error-v1.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    error = StudioError(
        "REVISION_CONFLICT",
        "Stored revision differs from expected revision.",
        correlation_id="local-request-001",
    )
    validator.validate(error.to_dict())
    assert set(schema["properties"]["error"]["properties"]["code"]["enum"]) == ERROR_CODES


@pytest.mark.parametrize(
    "invalid",
    [
        {"error": {"code": "NOT_A_WU1_CODE", "message": "x", "details": {}, "correlation_id": "id"}},
        {"error": {"code": "STORAGE_ERROR", "message": "x", "details": {}, "correlation_id": ""}},
        {"error": {"code": "STORAGE_ERROR", "message": "x", "details": [] , "correlation_id": "id"}},
    ],
)
def test_api_error_schema_rejects_invalid_payloads(schema_dir, invalid):
    schema = json.loads((schema_dir / "api-error-v1.schema.json").read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(invalid)


@pytest.mark.parametrize(
    "details",
    [
        {"count": float("nan")},
        {1: "bad key"},
        {"value": object()},
        {"value": "lone surrogate: \ud800"},
    ],
)
def test_typed_error_rejects_non_json_details(details):
    with pytest.raises(ValueError):
        StudioError("INTERNAL_ERROR", "Safe error", details)


def test_typed_errors_generate_distinct_valid_correlation_ids():
    first = StudioError("INTERNAL_ERROR", "Safe error")
    second = StudioError("INTERNAL_ERROR", "Safe error")

    assert first.correlation_id
    assert first.correlation_id != second.correlation_id


def test_typed_error_rejects_invalid_utf8_message():
    with pytest.raises(ValueError):
        StudioError("INTERNAL_ERROR", "lone surrogate: \ud800")


def test_manifest_proposed_example_matches_structural_manifest_schema(schema_dir):
    schema = json.loads((schema_dir / "manifest-v2.schema.json").read_text(encoding="utf-8"))
    example = json.loads((ROOT / "manifest.proposed.example.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(example)


def test_new_override_and_error_examples_match_their_schemas(schema_dir):
    override_schema = json.loads((schema_dir / "override-store-v1.schema.json").read_text(encoding="utf-8"))
    error_schema = json.loads((schema_dir / "api-error-v1.schema.json").read_text(encoding="utf-8"))
    override_example = json.loads((FIXTURES / "override-store-valid.json").read_text(encoding="utf-8"))
    error_example = json.loads((FIXTURES / "api-error-valid.json").read_text(encoding="utf-8"))
    Draft202012Validator(override_schema).validate(override_example)
    Draft202012Validator(error_schema).validate(error_example)


def test_wu4_catalog_and_editor_schemas_are_strict(schema_dir):
    catalog = json.loads((schema_dir / "project-catalog-v1.schema.json").read_text(encoding="utf-8"))
    editor = json.loads((schema_dir / "editor-state-v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(catalog).validate({"contract_version": "wrld-project-catalog/1.0", "projects": []})
    with pytest.raises(ValidationError):
        Draft202012Validator(catalog).validate({"contract_version": "wrld-project-catalog/1.0", "projects": [], "absolute_path": "C:/private"})
    Draft202012Validator(editor).validate({
        "contract_version": "wrld-editor-state/1.0", "project_id": "p", "album_id": "a", "revision": 1,
        "save_id": "initial", "source_fingerprint": "0" * 64, "profile_id": "youtube-1080p30-v1",
        "base_effects": {}, "album_overrides": {}, "track_overrides": {}, "shorts": {}, "state_digest": "1" * 64,
    })


def test_wu4_flexible_import_schemas_are_strict(schema_dir):
    catalog = Draft202012Validator(json.loads((schema_dir / "project-catalog-v2.schema.json").read_text(encoding="utf-8")))
    catalog.validate({"contract_version": "wrld-project-catalog/2.0", "projects": []})
    inventory = Draft202012Validator(json.loads((schema_dir / "project-inventory-v1.schema.json").read_text(encoding="utf-8")))
    inventory.validate({
        "contract_version": "wrld-project-inventory/1.0", "project_id": "project-1", "inventory_revision": 0,
        "scan_id": None, "completed_at": None, "policy_version": "inventory-policy/1.0", "assets": [], "diagnostics": [],
        "counts": {"audio": 0, "image": 0, "video": 0, "unknown": 0, "missing": 0},
    })
    handoff = Draft202012Validator(json.loads((schema_dir / "import-handoff-v1.schema.json").read_text(encoding="utf-8")))
    with pytest.raises(ValidationError):
        handoff.validate({"contract_version": "wrld-import-handoff/1.0", "project_id": "p", "absolute_path": "C:/private"})


def test_wu4_project_workspace_schemas_are_strict(schema_dir):
    preferences = Draft202012Validator(json.loads((schema_dir / "project-preferences-v1.schema.json").read_text(encoding="utf-8")))
    preferences.validate({"contract_version": "wrld-project-preferences/1.0", "project_id": "p", "revision": 1, "save_id": "initial", "excluded_asset_ids": ["asset-1"], "state_digest": "0" * 64})
    handoff = Draft202012Validator(json.loads((schema_dir / "import-handoff-v2.schema.json").read_text(encoding="utf-8")))
    handoff.validate({"contract_version": "wrld-import-handoff/2.0", "project_id": "p", "inventory_revision": 2, "preferences_revision": 3})
    with pytest.raises(ValidationError):
        handoff.validate({"contract_version": "wrld-import-handoff/2.0", "project_id": "p", "inventory_revision": 2, "preferences_revision": 3, "workflow": "individual"})
    creation = Draft202012Validator(json.loads((schema_dir / "creation-state-v1.schema.json").read_text(encoding="utf-8")))
    creation.validate({"contract_version": "wrld-creation-state/1.0", "project_id": "p", "revision": 1, "save_id": "initial", "preferred_short_duration_seconds": 45, "albums": [], "singles": [], "shorts": [], "state_digest": "0" * 64})


def test_wu4_creation_v2_schema_enforces_typed_templates_and_references(schema_dir):
    creation = Draft202012Validator(json.loads((schema_dir / "creation-state-v2.schema.json").read_text(encoding="utf-8")))
    document = {
        "contract_version": "wrld-creation-state/2.0", "project_id": "p", "revision": 1,
        "save_id": "upgrade", "preferred_short_duration_seconds": 45,
        "visual_templates": [{
            "visual_template_id": "visual-1", "label": "Portrait",
            "canvas": {"aspect_ratio": "9:16"}, "background_image": None,
            "geometry": {"fit_mode": "contain", "focal_x": 0.5, "focal_y": 0.5},
            "camera": {"mode": "static", "max_zoom": 1.04},
            "visualizer": {"enabled": False, "bar_count": 24, "opacity": 0.65},
            "progress": {"enabled": False}, "color_treatment": {"mode": "none"},
        }],
        "albums": [], "singles": [],
        "shorts": [{
            "short_id": "short-1", "asset_id": "asset-1", "expected_sha256": "a" * 64,
            "status": "active", "start_sample": 0, "sample_count": 240_000,
            "origin": "manual", "review_required": False, "customized": True,
            "approved": False, "settings": {"legacy": {"preserved": True}},
            "visual_template_id": "visual-1",
        }],
        "state_digest": "0" * 64,
    }
    creation.validate(document)
    invalid = copy.deepcopy(document)
    invalid["visual_templates"][0]["geometry"]["focal_x"] = 1.1
    with pytest.raises(ValidationError):
        creation.validate(invalid)
    invalid = copy.deepcopy(document)
    del invalid["shorts"][0]["visual_template_id"]
    with pytest.raises(ValidationError):
        creation.validate(invalid)
    invalid = copy.deepcopy(document)
    invalid["visual_templates"][0]["background_image"] = {
        "asset_id": "asset-image", "expected_sha256": "b" * 64,
        "absolute_path": "C:/outside/project/cover.png",
    }
    with pytest.raises(ValidationError):
        creation.validate(invalid)


def test_wu4_creation_v3_schema_is_strict_and_exposes_template_families(schema_dir):
    creation = Draft202012Validator(json.loads((schema_dir / "creation-state-v3.schema.json").read_text(encoding="utf-8")))
    template = {
        "visual_template_id": "visual-album", "label": "Family visual",
        "canvas": {"aspect_ratio": "16:9"}, "background_image": None,
        "geometry": {"fit_mode": "contain", "focal_x": 0.5, "focal_y": 0.5},
        "camera": {"mode": "static", "max_zoom": 1.04},
        "visualizer": {"enabled": False, "bar_count": 24, "opacity": 0.65},
        "progress": {"enabled": False}, "color_treatment": {"mode": "none"},
    }
    document = {
        "contract_version": "wrld-creation-state/3.0", "project_id": "p", "revision": 1,
        "save_id": "upgrade", "preferred_short_duration_seconds": 45,
        "visual_templates": [
            template,
            {**copy.deepcopy(template), "visual_template_id": "visual-single"},
            {**copy.deepcopy(template), "visual_template_id": "visual-short", "canvas": {"aspect_ratio": "9:16"}},
            {**copy.deepcopy(template), "visual_template_id": "visual-ungrouped"},
            {**copy.deepcopy(template), "visual_template_id": "visual-standalone"},
        ],
        "visual_template_families": [
            {
                "visual_template_family_id": "family-a", "name": "Duplicate name",
                "members": {
                    "album_visual_template_id": "visual-album",
                    "single_visual_template_id": "visual-single",
                    "short_visual_template_id": "visual-short",
                },
            },
            {
                "visual_template_family_id": "family-b", "name": "Duplicate name",
                "members": {
                    "album_visual_template_id": "visual-ungrouped",
                    "single_visual_template_id": "visual-single",
                    "short_visual_template_id": "visual-short",
                },
            },
        ],
        "albums": [], "singles": [], "shorts": [], "state_digest": "0" * 64,
    }
    creation.validate(document)

    for mutate in (
        lambda value: value["visual_template_families"][0].pop("members"),
        lambda value: value["visual_template_families"][0].update({"unknown": True}),
        lambda value: value["visual_template_families"][0]["members"].update({"general_visual_template_id": "visual-album"}),
    ):
        invalid = copy.deepcopy(document)
        mutate(invalid)
        with pytest.raises(ValidationError):
            creation.validate(invalid)


def test_wu4_creation_v4_schema_requires_strict_composition_owned_visual_settings(schema_dir):
    creation = Draft202012Validator(json.loads((schema_dir / "creation-state-v4.schema.json").read_text(encoding="utf-8")))
    configuration = {
        "canvas": {"aspect_ratio": "9:16"}, "background_image": None,
        "geometry": {"fit_mode": "contain", "focal_x": 0.5, "focal_y": 0.5},
        "camera": {"mode": "static", "max_zoom": 1.04},
        "visualizer": {"enabled": False, "bar_count": 24, "opacity": 0.65},
        "progress": {"enabled": False}, "color_treatment": {"mode": "none"},
    }
    document = {
        "contract_version": "wrld-creation-state/4.0", "project_id": "p", "revision": 4,
        "save_id": "upgrade-v4", "preferred_short_duration_seconds": 45,
        "visual_templates": [], "visual_template_families": [], "albums": [], "singles": [],
        "shorts": [{
            "short_id": "short-1", "asset_id": "asset-1", "expected_sha256": "a" * 64,
            "status": "archived", "start_sample": 0, "sample_count": 240_000,
            "origin": "manual", "review_required": False, "customized": True, "approved": True,
            "settings": {"legacy": {"preserved": True}},
            "visual_configuration": configuration,
            "source_visual_template_id": "removed-template-history-is-valid",
        }],
        "state_digest": "0" * 64,
    }
    creation.validate(document)

    invalid = copy.deepcopy(document)
    del invalid["shorts"][0]["visual_configuration"]
    with pytest.raises(ValidationError):
        creation.validate(invalid)
    invalid = copy.deepcopy(document)
    invalid["shorts"][0]["visual_configuration"]["unknown_visual_field"] = True
    with pytest.raises(ValidationError):
        creation.validate(invalid)
    invalid = copy.deepcopy(document)
    invalid["shorts"][0]["visual_template_id"] = "legacy-live-reference"
    with pytest.raises(ValidationError):
        creation.validate(invalid)
