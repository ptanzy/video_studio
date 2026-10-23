from __future__ import annotations

import copy
import json

import pytest
from jsonschema import Draft202012Validator, RefResolver
from pydantic import ValidationError

from wrld_video_studio.interfaces.http.models import PreviewRequestModel


def _fixture():
    return {
        "contract_version": "preview-request-v1",
        "target": {
            "album_id": "album-1",
            "artwork_asset_id": "artwork-1",
            "track_id": "track-1",
            "short_id": "short-1",
        },
        "treatment": {"mode": "custom", "hex": "#abcdef", "intensity": 0.3},
        "variant": "authoritative_still",
    }


def _schema_validator(schema_dir):
    preview = json.loads((schema_dir / "preview-v1.schema.json").read_text(encoding="utf-8"))
    color = json.loads((schema_dir / "color-resolution-v1.schema.json").read_text(encoding="utf-8"))
    resolver = RefResolver.from_schema(
        preview,
        store={"https://wrld.example/contracts/color-resolution-v1.schema.json": color},
    )
    return Draft202012Validator(preview["$defs"]["request"], resolver=resolver)


def test_pydantic_request_round_trips_through_existing_domain_and_json_schema(schema_dir):
    payload = _fixture()
    model = PreviewRequestModel.model_validate(payload)
    domain = model.to_domain()

    assert domain.to_dict() == payload | {
        "treatment": {"mode": "custom", "hex": "#ABCDEF", "intensity": 0.3}
    }
    _schema_validator(schema_dir).validate(model.model_dump(mode="json", exclude_none=True))


@pytest.mark.parametrize(
    "field",
    [
        "source_path",
        "cache_key",
        "correlation_id",
        "artifact_sha256",
        "retrieval_reference",
        "source_sha256",
        "ffmpeg_sha256",
        "renderer_version",
        "resolution",
        "context",
        "toolchain",
        "artifact_verified",
    ],
)
def test_http_request_rejects_every_server_owned_injection(field):
    payload = _fixture()
    payload[field] = "forged"
    with pytest.raises(ValidationError):
        PreviewRequestModel.model_validate(payload)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True, "0.3"])
def test_http_request_rejects_nonfinite_boolean_and_coerced_intensity(value):
    payload = _fixture()
    payload["treatment"]["intensity"] = value
    with pytest.raises(ValidationError):
        PreviewRequestModel.model_validate(payload)


def test_http_request_rejects_unknown_nested_fields():
    payload = _fixture()
    payload["target"]["path"] = "C:/private/art.png"
    payload["treatment"]["context"] = {}
    with pytest.raises(ValidationError):
        PreviewRequestModel.model_validate(payload)


@pytest.mark.parametrize("field", ["track_id", "short_id"])
def test_http_model_and_json_schema_both_reject_explicit_null_optional_ids(schema_dir, field):
    payload = _fixture()
    payload["target"][field] = None

    assert list(_schema_validator(schema_dir).iter_errors(payload))
    with pytest.raises(ValidationError):
        PreviewRequestModel.model_validate(payload)


@pytest.mark.parametrize("mode", ["auto", "preset", "custom"])
def test_http_model_and_schema_accept_same_treatment_shapes(schema_dir, mode):
    payload = _fixture()
    if mode == "auto":
        payload["treatment"] = {"mode": "auto", "intensity": 0}
    elif mode == "preset":
        payload["treatment"] = {"mode": "preset", "preset": "original", "intensity": 0}
    validator = _schema_validator(schema_dir)

    model = PreviewRequestModel.model_validate(payload)
    serialized = model.model_dump(mode="json", exclude_none=True)

    validator.validate(serialized)
    assert model.to_domain().to_dict()["treatment"]["mode"] == mode
