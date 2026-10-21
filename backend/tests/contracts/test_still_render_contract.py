import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

from wrld_video_studio.application.ports.still_images import (
    STILL_RENDER_REQUEST_VERSION,
    StillRenderRequest,
)
from wrld_video_studio.domain.color_resolution import (
    INPUT_CONTRACT_VERSION,
    PRESET_HEX_BY_ID,
    resolve_color_treatment,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator(schema_dir: Path) -> Draft202012Validator:
    color_schema = _load(schema_dir / "color-resolution-v1.schema.json")
    still_schema = _load(schema_dir / "still-render-v1.schema.json")
    registry = Registry().with_resource(
        color_schema["$id"], Resource.from_contents(color_schema)
    )
    return Draft202012Validator(still_schema, registry=registry)


def _resolution_input(treatment, context=None):
    value = {"contract_version": INPUT_CONTRACT_VERSION, "treatment": treatment}
    if context is not None:
        value["context"] = context
    return value


def test_still_render_schema_is_valid_and_resolves_phase_one_reference(schema_dir):
    color_schema = _load(schema_dir / "color-resolution-v1.schema.json")
    still_schema = _load(schema_dir / "still-render-v1.schema.json")

    Draft202012Validator.check_schema(color_schema)
    Draft202012Validator.check_schema(still_schema)
    _validator(schema_dir).validate(
        _load(FIXTURE_DIR / "still-render-request-valid.json")
    )


@pytest.mark.parametrize(
    "fixture_name",
    ["still-render-request-valid.json", "still-render-result-valid.json"],
)
def test_positive_still_render_fixtures_validate(schema_dir, fixture_name):
    _validator(schema_dir).validate(_load(FIXTURE_DIR / fixture_name))


@pytest.mark.parametrize(
    "fixture_name",
    [
        "still-render-request-invalid-contradictory.json",
        "still-render-request-invalid-version.json",
    ],
)
def test_negative_still_render_fixtures_are_rejected(schema_dir, fixture_name):
    with pytest.raises(ValidationError):
        _validator(schema_dir).validate(_load(FIXTURE_DIR / fixture_name))


def test_every_phase_one_resolution_branch_is_valid_when_nested(schema_dir):
    inputs = [
        _resolution_input({"mode": "custom", "hex": "#aBcDeF", "intensity": 0.6}),
        *[
            _resolution_input(
                {"mode": "preset", "preset": preset_id, "intensity": 0.3}
            )
            for preset_id in PRESET_HEX_BY_ID
        ],
        _resolution_input(
            {"mode": "auto", "intensity": 0.3},
            {"track_preference": {"hex": "#123456"}},
        ),
        _resolution_input(
            {"mode": "auto", "intensity": 0.3},
            {"album_palette": [{"hex": "#234567"}]},
        ),
        _resolution_input(
            {"mode": "auto", "intensity": 0.3},
            {"album_default_preset": "warm"},
        ),
        _resolution_input(
            {"mode": "auto", "intensity": 0.3},
            {"album_default_preset": "original"},
        ),
        _resolution_input({"mode": "auto", "intensity": 0.3}),
    ]
    validator = _validator(schema_dir)

    for index, input_value in enumerate(inputs):
        resolution = resolve_color_treatment(input_value)
        request = StillRenderRequest(
            contract_version=STILL_RENDER_REQUEST_VERSION,
            source_path=Path(f"artwork/source-{index}.png"),
            output_relative_path=f"previews/result-{index}.png",
            resolution=resolution,
        )
        validator.validate(request.to_dict())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contract_version", "still-render-request-v2"),
        ("renderer_version", "invented-renderer"),
        ("transform_version", "invented-transform"),
        ("output_relative_path", "../escape.png"),
        ("output_relative_path", "..\\escape.png"),
        ("output_relative_path", "C:\\escape.png"),
        ("output_relative_path", "/escape.png"),
        ("output_relative_path", "preview/result.PNG"),
    ],
)
def test_request_envelope_rejects_unsupported_versions_and_paths(
    schema_dir, field, value
):
    request = _load(FIXTURE_DIR / "still-render-request-valid.json")
    request[field] = value

    with pytest.raises(ValidationError):
        _validator(schema_dir).validate(request)


@pytest.mark.parametrize("field", ["resolver_version", "preset_mapping_version"])
def test_phase_one_schema_itself_rejects_fabricated_versions(schema_dir, field):
    color_schema = _load(schema_dir / "color-resolution-v1.schema.json")
    value = _load(FIXTURE_DIR / "color-resolution-output-valid-custom.json")
    value[field] = "fabricated"

    with pytest.raises(ValidationError):
        Draft202012Validator(color_schema).validate(value)


def test_result_rejects_impossible_metadata(schema_dir):
    validator = _validator(schema_dir)
    result = _load(FIXTURE_DIR / "still-render-result-valid.json")
    mutations = [
        {"width": 1025},
        {"height": 0},
        {"output_format": "jpeg"},
        {"orientation": "orientation unknown"},
        {"sanitized_command": []},
    ]

    for mutation in mutations:
        invalid = deepcopy(result)
        invalid.update(mutation)
        with pytest.raises(ValidationError):
            validator.validate(invalid)
