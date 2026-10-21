import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from wrld_video_studio.domain.color_resolution import (
    INPUT_CONTRACT_VERSION,
    PRESET_HEX_BY_ID,
    ColorResolutionError,
    resolve_color_treatment,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def make_input(treatment=None, context=None):
    payload = {
        "contract_version": INPUT_CONTRACT_VERSION,
        "treatment": treatment or {"mode": "auto", "intensity": 0.3},
    }
    if context is not None:
        payload["context"] = context
    return payload


def test_color_resolution_schema_accepts_input_and_generated_output(schema_dir):
    schema = json.loads((schema_dir / "color-resolution-v1.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    input_value = make_input(
        {"mode": "custom", "hex": "#AbCdEf", "intensity": 0.3},
        {"mood": "free form mood", "album_palette": [{"name": "sample", "hex": "#123456"}]},
    )
    output_value = resolve_color_treatment(input_value).to_dict()

    validator.validate(input_value)
    validator.validate(output_value)


def test_color_resolution_positive_contract_fixtures_and_runtime_agree(schema_dir):
    schema = json.loads((schema_dir / "color-resolution-v1.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    input_value = json.loads((FIXTURE_DIR / "color-resolution-input-valid.json").read_text(encoding="utf-8"))
    output_fixture = json.loads((FIXTURE_DIR / "color-resolution-output-valid-custom.json").read_text(encoding="utf-8"))

    validator.validate(input_value)
    validator.validate(output_fixture)
    validator.validate(resolve_color_treatment(input_value).to_dict())


def test_every_generated_mode_and_auto_branch_validates_as_output(schema_dir):
    schema = json.loads((schema_dir / "color-resolution-v1.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    inputs = [
        make_input({"mode": "custom", "hex": "#aBcDeF", "intensity": 0.2}),
        *[
            make_input({"mode": "preset", "preset": preset_id, "intensity": 0.2})
            for preset_id in PRESET_HEX_BY_ID
        ],
        make_input({"mode": "auto", "intensity": 0.2}, {"track_preference": {"hex": "#123456"}}),
        make_input({"mode": "auto", "intensity": 0.2}, {"album_palette": [{"hex": "#123456"}]}),
        make_input({"mode": "auto", "intensity": 0.2}, {"album_default_preset": "warm"}),
        make_input({"mode": "auto", "intensity": 0.2}, {"album_default_preset": "original"}),
        make_input({"mode": "auto", "intensity": 0.2}),
    ]

    for input_value in inputs:
        validator.validate(input_value)
        validator.validate(resolve_color_treatment(input_value).to_dict())


@pytest.mark.parametrize(
    "invalid_input",
    [
        make_input({"mode": "custom", "hex": "#abc", "intensity": 0.3}),
        make_input({"mode": "auto", "intensity": 0.7}),
        make_input({"mode": "preset", "preset": "not-a-preset", "intensity": 0.2}),
        {"contract_version": "color-resolution-input-v2", "treatment": {"mode": "auto", "intensity": 0.2}},
        make_input({"mode": "auto", "intensity": 0.2, "unexpected": True}),
        make_input(context={"track_preference": {}}),
        make_input(context={"track_preference": {"hex": "#123456", "extra": True}}),
        make_input(context={"album_default_preset": 17}),
        make_input(context={"album_palette": None}),
        make_input(context={"album_palette": [{"hex": "bad"}, {"hex": "#ABCDEF"}]}),
        make_input(context={"album_palette": [{"hex": "#123456", "name": 9}]}),
        make_input(context={"features": None}),
        make_input(context={"features": {"energy": True}}),
    ],
)
def test_color_resolution_schema_rejects_invalid_input(invalid_input, schema_dir):
    schema = json.loads((schema_dir / "color-resolution-v1.schema.json").read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(invalid_input)
    with pytest.raises(ColorResolutionError):
        resolve_color_treatment(invalid_input)


@pytest.mark.parametrize(
    "fixture_name",
    [
        "color-resolution-input-invalid-palette.json",
    ],
)
def test_invalid_input_fixtures_fail_both_schema_and_resolver(fixture_name, schema_dir):
    schema = json.loads((schema_dir / "color-resolution-v1.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    value = json.loads((FIXTURE_DIR / fixture_name).read_text(encoding="utf-8"))

    with pytest.raises(ValidationError):
        validator.validate(value)
    with pytest.raises(ColorResolutionError) as raised:
        resolve_color_treatment(value)
    assert raised.value.code == "COLOR_INVALID_HEX"


def test_contradictory_output_fixture_is_rejected(schema_dir):
    schema = json.loads((schema_dir / "color-resolution-v1.schema.json").read_text(encoding="utf-8"))
    value = json.loads((FIXTURE_DIR / "color-resolution-output-invalid-contradictory.json").read_text(encoding="utf-8"))

    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(value)


@pytest.mark.parametrize(
    ("token", "python_value"),
    [("NaN", float("nan")), ("Infinity", float("inf")), ("-Infinity", -float("inf"))],
)
def test_nonstandard_nonfinite_json_tokens_are_rejected_before_schema_validation(token, python_value):
    raw = (
        '{"contract_version":"color-resolution-input-v1",'
        f'"treatment":{{"mode":"auto","intensity":{token}}}'
        '}'
    )

    with pytest.raises(ValueError):
        json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))

    with pytest.raises(ColorResolutionError) as raised:
        resolve_color_treatment(make_input({"mode": "auto", "intensity": python_value}))
    assert raised.value.code == "COLOR_INVALID_INTENSITY"


@pytest.mark.parametrize(
    "mutations",
    [
        {"mode": "auto"},
        {"resolved_hex": None},
        {"preset_id": "original"},
        {"source": "fallback"},
        {"reason": "explicit_preset"},
        {"intensity": 0.7},
        {"resolved_hex": "#abcdef"},
    ],
)
def test_output_schema_rejects_contradictory_custom_combinations(schema_dir, mutations):
    schema = json.loads((schema_dir / "color-resolution-v1.schema.json").read_text(encoding="utf-8"))
    value = json.loads((FIXTURE_DIR / "color-resolution-output-valid-custom.json").read_text(encoding="utf-8"))
    value.update(mutations)

    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(value)


@pytest.mark.parametrize(
    ("preset_id", "wrong_hex"),
    [("cool", "#B47B55"), ("warm", "#71869A"), ("lavender", "#5F817B"), ("teal", "#887A9B"), ("dark", "#123456")],
)
def test_output_schema_rejects_preset_hex_mismatch(schema_dir, preset_id, wrong_hex):
    schema = json.loads((schema_dir / "color-resolution-v1.schema.json").read_text(encoding="utf-8"))
    value = resolve_color_treatment(
        make_input({"mode": "preset", "preset": preset_id, "intensity": 0.2})
    ).to_dict()
    value["resolved_hex"] = wrong_hex

    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(value)


@pytest.mark.parametrize(
    ("input_value", "mutations"),
    [
        (make_input({"mode": "preset", "preset": "original", "intensity": 0.2}), {"intensity": 0.1}),
        (make_input({"mode": "auto", "intensity": 0.2}), {"reason": "first_palette_entry"}),
        (make_input({"mode": "auto", "intensity": 0.2}, {"track_preference": {"hex": "#123456"}}), {"source": "fallback"}),
        (make_input({"mode": "custom", "hex": "#123456", "intensity": 0.2}), {"reason": "explicit_preset"}),
    ],
)
def test_schema_rejects_auto_original_and_provenance_contradictions(schema_dir, input_value, mutations):
    schema = json.loads((schema_dir / "color-resolution-v1.schema.json").read_text(encoding="utf-8"))
    value = resolve_color_treatment(input_value).to_dict()
    value.update(mutations)

    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(value)


def test_existing_wu1_and_wu2_contract_schemas_remain_valid(schema_dir):
    for schema_name in (
        "manifest-v2.schema.json",
        "override-store-v1.schema.json",
        "api-error-v1.schema.json",
        "render-job-snapshot-v1.schema.json",
        "render-job-status-v1.schema.json",
    ):
        schema = json.loads((schema_dir / schema_name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)