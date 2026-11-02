import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource


FIXTURES = Path(__file__).parent / "fixtures"


def contract_validator(schema_dir, schema_name):
    documents = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in schema_dir.glob("*.schema.json")
    ]
    registry = Registry().with_resources(
        (document["$id"], Resource.from_contents(document))
        for document in documents
        if "$id" in document
    )
    schema = next(
        document for document in documents if document.get("$id", "").endswith(schema_name)
    )
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema, registry=registry, format_checker=FormatChecker()
    )


@pytest.mark.parametrize(
    ("schema_name", "fixture_name"),
    [
        ("video-manifest-v1.schema.json", "video-manifest-v1-valid.json"),
        ("video-export-request-v1.schema.json", "video-export-request-v1-valid.json"),
        ("video-export-result-v1.schema.json", "video-export-result-v1-valid.json"),
        ("render-report-v1.schema.json", "render-report-v1-valid.json"),
        ("render-progress-v1.schema.json", "render-progress-v1-valid.json"),
        ("render-diagnostic-v1.schema.json", "render-diagnostic-v1-valid.json"),
        ("video-effects-v1.schema.json", "video-effects-v1-valid.json"),
        ("video-manifest-v2.schema.json", "video-manifest-v2-valid.json"),
        ("video-export-request-v2.schema.json", "video-export-request-v2-valid.json"),
        ("video-export-result-v2.schema.json", "video-export-result-v2-valid.json"),
        ("motion-preview-request-v1.schema.json", "motion-preview-request-v1-valid.json"),
        ("video-effects-v2.schema.json", "video-effects-v2-valid.json"),
        ("video-manifest-v3.schema.json", "video-manifest-v3-valid.json"),
        ("video-export-request-v3.schema.json", "video-export-request-v3-valid.json"),
        ("video-export-result-v3.schema.json", "video-export-result-v3-valid.json"),
        ("motion-preview-request-v2.schema.json", "motion-preview-request-v2-valid.json"),
        ("video-effects-v3.schema.json", "video-effects-v3-valid.json"),
        ("video-manifest-v4.schema.json", "video-manifest-v4-valid.json"),
        ("video-export-request-v4.schema.json", "video-export-request-v4-valid.json"),
    ],
)
def test_video_export_schemas_accept_valid_fixtures(schema_dir, schema_name, fixture_name):
    payload = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
    contract_validator(schema_dir, schema_name).validate(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(format="wrld-video-album/0.1-draft"),
        lambda value: value.update(output={"filename": "override.mp4"}),
        lambda value: value["visual"].update(background="../escape.png"),
        lambda value: value["render"].update(profile_id="arbitrary"),
        lambda value: value["tracks"][0].update(audio="C:/private/audio.wav"),
    ],
)
def test_manifest_schema_rejects_obsolete_or_unsafe_shapes(schema_dir, mutation):
    schema = json.loads((schema_dir / "video-manifest-v1.schema.json").read_text())
    payload = json.loads((FIXTURES / "video-manifest-v1-valid.json").read_text())
    mutation(payload)
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(payload)


def test_request_schema_enforces_exact_target_union(schema_dir):
    schema = json.loads((schema_dir / "video-export-request-v1.schema.json").read_text())
    payload = json.loads((FIXTURES / "video-export-request-v1-valid.json").read_text())
    invalid = copy.deepcopy(payload)
    invalid["target"] = {"kind": "track"}
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(invalid)


def test_v1_contracts_reject_effect_fields(schema_dir):
    manifest = json.loads((FIXTURES / "video-manifest-v1-valid.json").read_text())
    manifest["render"]["effects"] = json.loads(
        (FIXTURES / "video-effects-v1-valid.json").read_text()
    )
    with pytest.raises(ValidationError):
        contract_validator(schema_dir, "video-manifest-v1.schema.json").validate(manifest)

    request = json.loads((FIXTURES / "video-export-request-v1-valid.json").read_text())
    request["effects"] = manifest["render"]["effects"]
    with pytest.raises(ValidationError):
        contract_validator(schema_dir, "video-export-request-v1.schema.json").validate(request)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("pan_zoom", "max_zoom"), 1.050001),
        (("pan_zoom", "cycle_seconds"), 14.999),
        (("pan_zoom", "cycle_seconds"), 600.001),
        (("pan_zoom", "path"), "random"),
        (("audio_bars", "bar_count"), 7),
        (("audio_bars", "opacity"), 1.01),
        (("audio_bars", "rms_window_samples"), 4801),
        (("track_progress", "thickness_px"), 17),
        (("track_progress", "style"), "circle"),
        (("track_progress", "segment_count"), 4),
    ],
)
def test_effect_schema_rejects_invalid_values(schema_dir, path, value):
    payload = json.loads((FIXTURES / "video-effects-v1-valid.json").read_text())
    payload[path[0]][path[1]] = value
    with pytest.raises(ValidationError):
        contract_validator(schema_dir, "video-effects-v1.schema.json").validate(payload)


def test_v2_contracts_reject_unknown_fields(schema_dir):
    for schema_name, fixture_name in (
        ("video-effects-v1.schema.json", "video-effects-v1-valid.json"),
        ("video-manifest-v2.schema.json", "video-manifest-v2-valid.json"),
        ("video-export-request-v2.schema.json", "video-export-request-v2-valid.json"),
        ("video-export-result-v2.schema.json", "video-export-result-v2-valid.json"),
        ("motion-preview-request-v1.schema.json", "motion-preview-request-v1-valid.json"),
        ("video-effects-v2.schema.json", "video-effects-v2-valid.json"),
        ("video-manifest-v3.schema.json", "video-manifest-v3-valid.json"),
        ("video-export-request-v3.schema.json", "video-export-request-v3-valid.json"),
        ("video-export-result-v3.schema.json", "video-export-result-v3-valid.json"),
        ("motion-preview-request-v2.schema.json", "motion-preview-request-v2-valid.json"),
        ("video-effects-v3.schema.json", "video-effects-v3-valid.json"),
        ("video-manifest-v4.schema.json", "video-manifest-v4-valid.json"),
        ("video-export-request-v4.schema.json", "video-export-request-v4-valid.json"),
    ):
        payload = json.loads((FIXTURES / fixture_name).read_text())
        payload["unknown"] = True
        with pytest.raises(ValidationError):
            contract_validator(schema_dir, schema_name).validate(payload)


@pytest.mark.parametrize("sample_count", [143999, 720001, True])
def test_motion_preview_schema_enforces_sample_bounds_and_integer_types(
    schema_dir, sample_count
):
    payload = json.loads((FIXTURES / "motion-preview-request-v1-valid.json").read_text())
    payload["excerpt"]["sample_count"] = sample_count
    with pytest.raises(ValidationError):
        contract_validator(schema_dir, "motion-preview-request-v1.schema.json").validate(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("audio_bars", "variation_mode"), "frequency"),
        (("audio_bars", "color"), "#fff"),
        (("audio_bars", "gap_px"), 33),
        (("audio_bars", "bottom_margin_px"), 63),
        (("audio_bars", "glow", "intensity"), 1.01),
        (("track_progress", "color"), "white"),
        (("track_progress", "rail_color"), "#FFFFFFFF"),
        (("track_progress", "rail_contrast_strength"), -0.01),
        (("track_progress", "rail_opacity"), 0.09),
    ],
)
def test_effects_v2_schema_rejects_invalid_values(schema_dir, path, value):
    payload = json.loads((FIXTURES / "video-effects-v2-valid.json").read_text())
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        contract_validator(schema_dir, "video-effects-v2.schema.json").validate(payload)


def test_legacy_motion_contracts_reject_refined_effects(schema_dir):
    effects = json.loads((FIXTURES / "video-effects-v2-valid.json").read_text())
    for schema_name, fixture_name in (
        ("video-manifest-v2.schema.json", "video-manifest-v2-valid.json"),
        ("video-export-request-v2.schema.json", "video-export-request-v2-valid.json"),
        ("motion-preview-request-v1.schema.json", "motion-preview-request-v1-valid.json"),
    ):
        payload = json.loads((FIXTURES / fixture_name).read_text())
        if "render" in payload:
            payload["render"]["effects"] = effects
        else:
            payload["effects"] = effects
        with pytest.raises(ValidationError):
            contract_validator(schema_dir, schema_name).validate(payload)


def test_player_preview_and_result_schemas_accept_v4_payload(schema_dir):
    preview = json.loads((FIXTURES / "motion-preview-request-v3-valid.json").read_text())
    contract_validator(schema_dir, "motion-preview-request-v3.schema.json").validate(preview)
    result = json.loads((FIXTURES / "video-export-result-v4-valid.json").read_text())
    contract_validator(schema_dir, "video-export-result-v4.schema.json").validate(result)


def test_player_v4_rejects_unknown_fields_and_unsafe_font_paths(schema_dir):
    payload = json.loads((FIXTURES / "video-manifest-v4-valid.json").read_text())
    payload["render"]["effects"]["player"]["font"]["path"] = "../Segoe UI.ttf"
    with pytest.raises(ValidationError):
        contract_validator(schema_dir, "video-manifest-v4.schema.json").validate(payload)
    payload = json.loads((FIXTURES / "video-export-request-v4-valid.json").read_text())
    payload["resolved_player"]["unknown"] = True
    with pytest.raises(ValidationError):
        contract_validator(schema_dir, "video-export-request-v4.schema.json").validate(payload)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.__setitem__("target", {"kind": "track"}),
        lambda value: value.__setitem__("target", {"kind": "album", "track_id": "extra"}),
        lambda value: value.__setitem__("artifacts", [{"kind": "album_video"}]),
        lambda value: value.__setitem__(
            "timeline",
            [{
                "track_id": "track-01", "number": 1, "title": "First Track",
                "start_sample": 0, "sample_count": 0, "display_seconds": 0,
            }],
        ),
        lambda value: value.__setitem__("started_at", "not-a-date-time"),
    ),
)
def test_player_result_v4_rejects_runtime_invalid_nested_values(schema_dir, mutate):
    payload = json.loads((FIXTURES / "video-export-result-v4-valid.json").read_text())
    mutate(payload)
    with pytest.raises(ValidationError):
        contract_validator(schema_dir, "video-export-result-v4.schema.json").validate(payload)
