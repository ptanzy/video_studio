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
