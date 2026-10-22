import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

from wrld_video_studio.domain.color_resolution import INPUT_CONTRACT_VERSION, resolve_color_treatment
from wrld_video_studio.domain.preview_cache import (
    PREVIEW_ERROR_CODES,
    PreviewError,
    PreviewRequest,
    PreviewResult,
    PreviewToolchainIdentity,
    build_preview_cache_identity,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator(schema_dir: Path) -> Draft202012Validator:
    color_schema = _load(schema_dir / "color-resolution-v1.schema.json")
    preview_schema = _load(schema_dir / "preview-v1.schema.json")
    registry = Registry().with_resource(color_schema["$id"], Resource.from_contents(color_schema))
    return Draft202012Validator(preview_schema, registry=registry)


def _resolution():
    return resolve_color_treatment(
        {
            "contract_version": INPUT_CONTRACT_VERSION,
            "treatment": {"mode": "custom", "hex": "#ABCDEF", "intensity": 0.3},
        }
    )


def _identity(resolution=None):
    return build_preview_cache_identity(
        source_sha256="3" * 64,
        resolution=resolution or _resolution(),
        toolchain=PreviewToolchainIdentity.create(ffmpeg_sha256="5" * 64, ffprobe_sha256="6" * 64),
    )


def _result(identity=None):
    bound_identity = identity or _identity()
    return PreviewResult.create(
        identity=bound_identity,
        cache_status="miss",
        width=1024,
        height=512,
        artifact_sha256="2" * 64,
    )


def test_preview_schema_and_all_positive_fixtures_validate(schema_dir):
    schema = _load(schema_dir / "preview-v1.schema.json")
    Draft202012Validator.check_schema(schema)
    validator = _validator(schema_dir)

    for fixture_name in (
        "preview-request-valid.json",
        "preview-result-valid.json",
        "preview-error-valid.json",
        "preview-cache-descriptor-valid.json",
    ):
        validator.validate(_load(FIXTURE_DIR / fixture_name))


def test_python_models_generate_schema_valid_payloads(schema_dir):
    validator = _validator(schema_dir)
    request = PreviewRequest.from_dict(_load(FIXTURE_DIR / "preview-request-valid.json"))
    resolution = _resolution()
    identity = _identity(resolution)
    result = PreviewResult.create(
        identity=identity,
        cache_status="miss",
        width=1024,
        height=512,
        artifact_sha256="2" * 64,
    )
    error = PreviewError.create(
        code="PREVIEW_SOURCE_UNAVAILABLE",
        message="The requested artwork source is unavailable.",
        correlation_id="local-preview-001",
        details={"asset_id": "album-artwork-primary"},
    )

    validator.validate(request.to_dict())
    validator.validate(identity.descriptor.to_dict())
    validator.validate(result.to_dict())
    assert PreviewResult.from_dict(result.to_dict(), identity=identity) == result
    validator.validate(error.to_dict())


@pytest.mark.parametrize(
    "artwork_asset_id",
    [
        "",
        "a" * 129,
        "C:/Users/person/art.png",
        r"\\server\share\art.png",
        "/var/tmp/art.png",
        "../art.png",
        "folder/art",
        r"folder\art",
        "https://example.test/art.png",
        "album art",
        "album.art",
        "album\uff0fart",
        "album\u2215art",
        "album\uff3cart",
    ],
)
def test_artwork_asset_id_is_opaque_in_schema_and_model(schema_dir, artwork_asset_id):
    payload = _load(FIXTURE_DIR / "preview-request-valid.json")
    payload["target"]["artwork_asset_id"] = artwork_asset_id

    with pytest.raises(ValidationError):
        _validator(schema_dir).validate(payload)
    with pytest.raises(ValueError):
        PreviewRequest.from_dict(payload)


@pytest.mark.parametrize("artwork_asset_id", ["a", "A_Z-09", "x" * 128])
def test_artwork_asset_id_approved_grammar_is_consistent(schema_dir, artwork_asset_id):
    payload = _load(FIXTURE_DIR / "preview-request-valid.json")
    payload["target"]["artwork_asset_id"] = artwork_asset_id

    _validator(schema_dir).validate(payload)
    assert PreviewRequest.from_dict(payload).target.artwork_asset_id == artwork_asset_id


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("contract_version",), "preview-request-v2"),
        (("variant",), "motion"),
        (("treatment", "intensity"), 0.7),
        (("treatment", "hex"), "#123"),
        (("target", "album_id"), ""),
    ],
)
def test_request_schema_and_model_reject_invalid_values(schema_dir, path, value):
    payload = _load(FIXTURE_DIR / "preview-request-valid.json")
    target = payload
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value

    with pytest.raises(ValidationError):
        _validator(schema_dir).validate(payload)
    with pytest.raises(ValueError):
        PreviewRequest.from_dict(payload)


@pytest.mark.parametrize(
    "forbidden_field",
    [
        "source_path",
        "source_sha256",
        "resolved_hex",
        "resolver_version",
        "preset_mapping_version",
        "renderer_version",
        "transform_version",
        "ffmpeg_sha256",
        "ffprobe_sha256",
        "cache_key",
        "output_path",
        "verified",
    ],
)
def test_request_rejects_unknown_and_server_derived_fields(schema_dir, forbidden_field):
    payload = _load(FIXTURE_DIR / "preview-request-valid.json")
    payload[forbidden_field] = "caller-controlled"

    with pytest.raises(ValidationError):
        _validator(schema_dir).validate(payload)
    with pytest.raises(ValueError):
        PreviewRequest.from_dict(payload)


def test_request_rejects_unknown_nested_fields(schema_dir):
    payload = _load(FIXTURE_DIR / "preview-request-valid.json")
    payload["target"]["source_path"] = "C:/private/art.png"

    with pytest.raises(ValidationError):
        _validator(schema_dir).validate(payload)
    with pytest.raises(ValueError):
        PreviewRequest.from_dict(payload)


@pytest.mark.parametrize(
    ("fixture_name", "missing_path"),
    [
        ("preview-request-valid.json", ("target",)),
        ("preview-request-valid.json", ("target", "artwork_asset_id")),
        ("preview-result-valid.json", ("artifact_sha256",)),
        ("preview-result-valid.json", ("provenance", "toolchain_fingerprint")),
        ("preview-error-valid.json", ("error", "details")),
        ("preview-cache-descriptor-valid.json", ("render_policy", "output_pixel_format")),
    ],
)
def test_required_contract_fields_are_enforced(schema_dir, fixture_name, missing_path):
    payload = _load(FIXTURE_DIR / fixture_name)
    target = payload
    for part in missing_path[:-1]:
        target = target[part]
    del target[missing_path[-1]]

    with pytest.raises(ValidationError):
        _validator(schema_dir).validate(payload)


@pytest.mark.parametrize("code", sorted(PREVIEW_ERROR_CODES))
def test_every_preview_error_code_has_a_valid_model_and_schema(schema_dir, code):
    payload = PreviewError.create(
        code=code,
        message="Preview operation did not complete.",
        correlation_id="correlation-001",
    ).to_dict()
    _validator(schema_dir).validate(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        {"contract_version": "preview-error-v2"},
        {"unexpected": True},
        {"error": {"code": "UNKNOWN", "message": "bad", "details": {}, "correlation_id": "id"}},
        {"error": {"code": "PREVIEW_TIMEOUT", "message": "", "details": {}, "correlation_id": "id"}},
    ],
)
def test_invalid_error_payloads_are_rejected(schema_dir, mutation):
    payload = _load(FIXTURE_DIR / "preview-error-valid.json")
    if "error" in mutation:
        payload["error"] = mutation["error"]
    else:
        payload.update(mutation)
    with pytest.raises(ValidationError):
        _validator(schema_dir).validate(payload)


@pytest.mark.parametrize(
    "arguments",
    [
        {"code": "UNKNOWN", "message": "bad", "correlation_id": "id"},
        {"code": "PREVIEW_TIMEOUT", "message": "", "correlation_id": "id"},
        {"code": "PREVIEW_TIMEOUT", "message": "bad", "correlation_id": ""},
        {
            "code": "PREVIEW_TIMEOUT",
            "message": "bad",
            "correlation_id": "id",
            "details": {"duration": float("nan")},
        },
    ],
)
def test_invalid_error_models_are_rejected(arguments):
    with pytest.raises(ValueError):
        PreviewError.create(**arguments)


def test_result_rejects_paths_commands_and_unknown_diagnostics(schema_dir):
    validator = _validator(schema_dir)
    original = _load(FIXTURE_DIR / "preview-result-valid.json")
    for field in ("artifact_path", "source_path", "sanitized_command", "stderr_tail"):
        payload = deepcopy(original)
        payload[field] = "C:/private/value"
        with pytest.raises(ValidationError):
            validator.validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contract_version", "preview-result-v2"),
        ("preview_id", "A" * 64),
        ("cache_status", "generated"),
        ("media_type", "image/jpeg"),
        ("width", 1025),
        ("height", 0),
    ],
)
def test_result_rejects_invalid_contract_values(schema_dir, field, value):
    payload = _load(FIXTURE_DIR / "preview-result-valid.json")
    payload[field] = value
    with pytest.raises(ValidationError):
        _validator(schema_dir).validate(payload)


def test_result_semantic_parser_rejects_mismatched_retrieval_reference(schema_dir):
    identity = _identity()
    payload = _result(identity).to_dict()
    payload["retrieval_reference"] = "preview:" + "9" * 64

    _validator(schema_dir).validate(payload)
    with pytest.raises(ValueError):
        PreviewResult.from_dict(payload, identity=identity)


@pytest.mark.parametrize(
    "mutation",
    [
        {"unexpected": True},
        {"provenance": {"unexpected": True}},
        {"treatment": {"unexpected": True}},
    ],
)
def test_result_semantic_parser_rejects_unknown_fields(mutation):
    identity = _identity()
    payload = _result(identity).to_dict()
    if "provenance" in mutation:
        payload["provenance"].update(mutation["provenance"])
    elif "treatment" in mutation:
        payload["treatment"].update(mutation["treatment"])
    else:
        payload.update(mutation)
    with pytest.raises(ValueError):
        PreviewResult.from_dict(payload, identity=identity)


def test_result_semantic_parser_maps_structural_type_errors_to_contract_errors():
    identity = _identity()
    payload = _result(identity).to_dict()
    payload["cache_status"] = []
    with pytest.raises(ValueError):
        PreviewResult.from_dict(payload, identity=identity)


def _cool_resolution():
    return resolve_color_treatment(
        {
            "contract_version": INPUT_CONTRACT_VERSION,
            "treatment": {"mode": "preset", "preset": "cool", "intensity": 0.3},
        }
    )


FORGED_RESULT_MUTATIONS = [
    pytest.param(
        {"preview_id": "9" * 64, "retrieval_reference": "preview:" + "9" * 64},
        True,
        id="preview-id-and-reference",
    ),
    pytest.param({"source_sha256": "8" * 64}, True, id="source-sha256"),
    pytest.param({"treatment": _cool_resolution().to_dict()}, True, id="treatment-provenance"),
    pytest.param({"provenance": {"cache_key_version": "preview-cache-key-v2"}}, False, id="cache-version"),
    pytest.param({"provenance": {"resolver_version": "1.0.0-provisional.2"}}, False, id="resolver-version"),
    pytest.param({"provenance": {"preset_mapping_version": "provisional-2"}}, False, id="mapping-version"),
    pytest.param({"provenance": {"renderer_version": "ffmpeg-still-v2"}}, False, id="renderer-version"),
    pytest.param({"provenance": {"transform_version": "linear-luma-chroma-v2"}}, False, id="transform-version"),
    pytest.param({"provenance": {"toolchain_fingerprint": "7" * 64}}, True, id="toolchain-fingerprint"),
]


@pytest.mark.parametrize(("mutation", "schema_valid"), FORGED_RESULT_MUTATIONS)
def test_result_parser_rejects_forged_identity_metadata(schema_dir, mutation, schema_valid):
    identity = _identity()
    payload = _result(identity).to_dict()
    if "provenance" in mutation:
        payload["provenance"].update(mutation["provenance"])
    else:
        payload.update(mutation)

    if schema_valid:
        _validator(schema_dir).validate(payload)
    else:
        with pytest.raises(ValidationError):
            _validator(schema_dir).validate(payload)
    with pytest.raises(ValueError):
        PreviewResult.from_dict(payload, identity=identity)


def test_schema_integer_representation_is_normalized_during_trusted_parse(schema_dir):
    identity = _identity()
    payload = _result(identity).to_dict()
    payload["width"] = 1.0

    _validator(schema_dir).validate(payload)
    parsed = PreviewResult.from_dict(payload, identity=identity)
    assert parsed.width == 1
    assert type(parsed.width) is int


@pytest.mark.parametrize(
    ("treatment", "context"),
    [
        ({"mode": "custom", "hex": "#ABCDEF", "intensity": 0.3}, None),
        ({"mode": "preset", "preset": "cool", "intensity": 0.3}, None),
        ({"mode": "preset", "preset": "original", "intensity": 0.3}, None),
        ({"mode": "auto", "intensity": 0.3}, {"track_preference": {"hex": "#ABCDEF"}}),
        ({"mode": "auto", "intensity": 0.3}, {"album_palette": [{"hex": "#ABCDEF"}]}),
        ({"mode": "auto", "intensity": 0.3}, {"album_default_preset": "cool"}),
        ({"mode": "auto", "intensity": 0.3}, {"album_default_preset": "original"}),
        ({"mode": "auto", "intensity": 0.3}, None),
    ],
)
def test_every_factory_result_branch_is_schema_valid_and_semantically_parseable(schema_dir, treatment, context):
    payload = {"contract_version": INPUT_CONTRACT_VERSION, "treatment": treatment}
    if context is not None:
        payload["context"] = context
    resolution = resolve_color_treatment(payload)
    identity = build_preview_cache_identity(
        source_sha256="3" * 64,
        resolution=resolution,
        toolchain=PreviewToolchainIdentity.create(ffmpeg_sha256="5" * 64, ffprobe_sha256="6" * 64),
    )
    result = PreviewResult.create(
        identity=identity,
        cache_status="miss",
        width=1024,
        height=512,
        artifact_sha256="2" * 64,
    )
    represented = result.to_dict()

    _validator(schema_dir).validate(represented)
    assert PreviewResult.from_dict(represented, identity=identity) == result
