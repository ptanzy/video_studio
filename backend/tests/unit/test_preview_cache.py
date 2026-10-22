import hashlib
import json
from copy import copy
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import MappingProxyType

import pytest

from wrld_video_studio.application.ports.still_images import (
    STILL_OUTPUT_MAX_DIMENSION as PHASE2_OUTPUT_MAX_DIMENSION,
    STILL_RENDERER_VERSION as PHASE2_RENDERER_VERSION,
    STILL_RENDER_REQUEST_VERSION,
    StillRenderRequest,
)
from wrld_video_studio.domain.canonical_json import canonical_sha256
from wrld_video_studio.domain.color_resolution import (
    INPUT_CONTRACT_VERSION,
    ColorResolution,
    resolve_color_treatment,
)
from wrld_video_studio.domain.preview_cache import (
    DEFAULT_PREVIEW_CACHE_MAX_BYTES,
    DEFAULT_PREVIEW_CACHE_MAX_ENTRIES,
    DEFAULT_PREVIEW_MAX_WAITING_REQUESTS,
    GEOMETRY_POLICY_VERSION,
    PREVIEW_CACHE_KEY_VERSION,
    STILL_OUTPUT_MAX_DIMENSION as PREVIEW_OUTPUT_MAX_DIMENSION,
    STILL_RENDERER_VERSION as PREVIEW_RENDERER_VERSION,
    PreviewContractError,
    PreviewError,
    PreviewRenderPolicy,
    PreviewRequest,
    PreviewResult,
    PreviewToolchainIdentity,
    build_preview_cache_identity,
)
from wrld_video_studio.infrastructure.still_image_renderer import (
    FFmpegStillImageRenderer,
    _scaled_dimensions,
)


SOURCE_SHA = "3" * 64
FFMPEG_SHA = "5" * 64
FFPROBE_SHA = "6" * 64
FIXED_EXPECTED_KEY = "7c2eadb17a2cfab9ed55570d6e68f72ee848b26d29af8307045df02cd60e84b3"


def _resolution(treatment=None, context=None):
    payload = {
        "contract_version": INPUT_CONTRACT_VERSION,
        "treatment": treatment or {"mode": "custom", "hex": "#ABCDEF", "intensity": 0.3},
    }
    if context is not None:
        payload["context"] = context
    return resolve_color_treatment(payload)


def _toolchain(ffmpeg=FFMPEG_SHA, ffprobe=FFPROBE_SHA):
    return PreviewToolchainIdentity.create(ffmpeg_sha256=ffmpeg, ffprobe_sha256=ffprobe)


def _identity(source=SOURCE_SHA, resolution=None, toolchain=None):
    return build_preview_cache_identity(
        source_sha256=source,
        resolution=resolution or _resolution(),
        toolchain=toolchain or _toolchain(),
    )


def _result(identity=None):
    return PreviewResult.create(
        identity=identity or _identity(),
        cache_status="miss",
        width=100,
        height=50,
        artifact_sha256="2" * 64,
    )


def _direct_result(result, **changes):
    values = {
        "_identity": result._identity,
        "contract_version": result.contract_version,
        "preview_id": result.preview_id,
        "cache_status": result.cache_status,
        "retrieval_reference": result.retrieval_reference,
        "media_type": result.media_type,
        "width": result.width,
        "height": result.height,
        "artifact_sha256": result.artifact_sha256,
        "source_sha256": result.source_sha256,
        "treatment": result.treatment,
        "cache_key_version": result.cache_key_version,
        "resolver_version": result.resolver_version,
        "preset_mapping_version": result.preset_mapping_version,
        "renderer_version": result.renderer_version,
        "transform_version": result.transform_version,
        "toolchain_fingerprint": result.toolchain_fingerprint,
    }
    values.update(changes)
    return PreviewResult(**values)


def test_fixed_reference_vector_uses_independently_constructed_descriptor():
    expected_descriptor = {
        "contract_version": "preview-cache-key-v1",
        "source_sha256": "3" * 64,
        "treatment": {
            "state": "treated",
            "resolved_hex": "#ABCDEF",
            "intensity": 0.3,
            "resolver_version": "1.0.0-provisional.1",
            "preset_mapping_version": "provisional-1",
        },
        "render_policy": {
            "renderer_version": "ffmpeg-still-v1",
            "transform_version": "linear-luma-chroma-v1",
            "geometry_policy_version": "phase2-still-geometry-v1",
            "orientation_policy_version": "phase2-exif-orientation-v1",
            "max_longest_side": 1024,
            "no_upscale": True,
            "scale_filter": "lanczos",
            "dither": "none",
            "output_format": "png",
            "output_pixel_format": "rgba",
            "color_primaries": "bt709",
            "color_transfer": "iec61966-2-1",
            "color_space": "rgb",
        },
        "toolchain": {
            "ffmpeg_sha256": "5" * 64,
            "ffprobe_sha256": "6" * 64,
        },
    }
    independently_encoded = json.dumps(
        expected_descriptor,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert hashlib.sha256(independently_encoded).hexdigest() == FIXED_EXPECTED_KEY

    actual = _identity()
    assert actual.preview_id == FIXED_EXPECTED_KEY
    assert actual.descriptor.to_dict() == expected_descriptor


def test_equivalent_inputs_and_mapping_order_produce_identical_identity():
    left = _identity()
    right = _identity(resolution=_resolution({"intensity": 0.3, "hex": "#abcdef", "mode": "custom"}))
    reordered = dict(reversed(list(left.descriptor.to_dict().items())))

    assert left.preview_id == right.preview_id
    assert canonical_sha256(reordered) == left.preview_id


@pytest.mark.parametrize(
    "changed",
    [
        {"source": "4" * 64},
        {"resolution": {"mode": "custom", "hex": "#ABCDEE", "intensity": 0.3}},
        {"resolution": {"mode": "custom", "hex": "#ABCDEF", "intensity": 0.2}},
        {"toolchain": ("7" * 64, FFPROBE_SHA)},
        {"toolchain": (FFMPEG_SHA, "8" * 64)},
    ],
)
def test_every_variable_authoritative_input_changes_identity(changed):
    arguments = {}
    if "source" in changed:
        arguments["source"] = changed["source"]
    if "resolution" in changed:
        arguments["resolution"] = _resolution(changed["resolution"])
    if "toolchain" in changed:
        arguments["toolchain"] = _toolchain(*changed["toolchain"])
    assert _identity(**arguments).preview_id != _identity().preview_id


def test_context_identifiers_and_paths_are_not_cache_inputs():
    first = PreviewRequest.from_dict(
        {
            "contract_version": "preview-request-v1",
            "target": {"album_id": "album-a", "artwork_asset_id": "art-a", "track_id": "track-a"},
            "treatment": {"mode": "custom", "hex": "#ABCDEF", "intensity": 0.3},
            "variant": "authoritative_still",
        }
    )
    second = PreviewRequest.from_dict(
        {
            "contract_version": "preview-request-v1",
            "target": {"album_id": "album-b", "artwork_asset_id": "art-b", "short_id": "short-b"},
            "treatment": {"mode": "custom", "hex": "#ABCDEF", "intensity": 0.3},
            "variant": "authoritative_still",
        }
    )

    assert first.target != second.target
    first_identity = _identity()
    second_identity = _identity()
    assert first_identity.preview_id == second_identity.preview_id
    descriptor_text = json.dumps(first_identity.descriptor.to_dict(), sort_keys=True)
    assert "album-a" not in descriptor_text
    assert "track-a" not in descriptor_text
    assert "short-b" not in descriptor_text
    assert "path" not in descriptor_text.casefold()


def test_untreated_and_treated_resolutions_never_share_identity():
    untreated = _resolution({"mode": "preset", "preset": "original", "intensity": 0.3})
    treated = _resolution({"mode": "custom", "hex": "#000000", "intensity": 0.3})

    assert _identity(resolution=untreated).preview_id != _identity(resolution=treated).preview_id
    assert _identity(resolution=untreated).descriptor.treatment.state == "untreated"
    assert _identity(resolution=treated).descriptor.treatment.state == "treated"


def test_negative_zero_normalizes_consistently_and_nonfinite_is_rejected():
    negative_zero = _resolution({"mode": "custom", "hex": "#ABCDEF", "intensity": -0.0})
    positive_zero = _resolution({"mode": "custom", "hex": "#ABCDEF", "intensity": 0.0})
    assert _identity(resolution=negative_zero).preview_id == _identity(resolution=positive_zero).preview_id
    assert _identity(resolution=negative_zero).descriptor.treatment.intensity == 0.0

    invalid = replace(_resolution(), intensity=float("nan"))
    with pytest.raises(PreviewContractError):
        _identity(resolution=invalid)


@pytest.mark.parametrize(
    "field_value",
    [
        "A" * 64,
        "0" * 63,
        "0" * 65,
        "not-a-hash",
    ],
)
def test_invalid_hashes_are_rejected(field_value):
    with pytest.raises(PreviewContractError):
        _identity(source=field_value)
    with pytest.raises(PreviewContractError):
        _toolchain(field_value, FFPROBE_SHA)


def test_unsupported_resolution_and_render_policy_versions_are_rejected():
    with pytest.raises(PreviewContractError):
        _identity(resolution=replace(_resolution(), resolver_version="future-resolver"))
    with pytest.raises(PreviewContractError):
        _identity(resolution=replace(_resolution(), preset_mapping_version="future-mapping"))
    with pytest.raises(PreviewContractError):
        replace(PreviewRenderPolicy(), renderer_version="future-renderer")
    with pytest.raises(PreviewContractError):
        replace(PreviewRenderPolicy(), transform_version="future-transform")
    with pytest.raises(PreviewContractError):
        replace(PreviewRenderPolicy(), geometry_policy_version="future-geometry")


def test_cache_descriptor_rejects_fabricated_versions_and_inconsistent_identity():
    identity = _identity()
    with pytest.raises(PreviewContractError):
        replace(identity.descriptor, contract_version="preview-cache-key-v2")
    with pytest.raises(PreviewContractError):
        replace(identity, preview_id="9" * 64)


@pytest.mark.parametrize(
    "fabricated",
    [
        replace(_resolution(), contract_version="color-resolution-output-v2"),
        replace(_resolution(), mode="unknown"),
        replace(_resolution(), mode=[]),
        replace(_resolution(), resolved_hex="#abcdef"),
        replace(_resolution(), preset_id="cool"),
        replace(_resolution(), intensity=True),
        replace(_resolution(), intensity=float("nan")),
        replace(_resolution(), source="fallback"),
        replace(_resolution(), reason="explicit_preset"),
        replace(_resolution(), resolver_version="future-resolver"),
        replace(_resolution(), preset_mapping_version="future-mapping"),
        replace(_resolution(), input_fingerprint="A" * 64),
        replace(_resolution({"mode": "preset", "preset": "cool", "intensity": 0.3}), resolved_hex="#ABCDEF"),
        replace(_resolution({"mode": "preset", "preset": "original", "intensity": 0.3}), intensity=0.3),
        replace(
            _resolution({"mode": "auto", "intensity": 0.3}, {"track_preference": {"hex": "#ABCDEF"}}),
            preset_id="cool",
        ),
        replace(_resolution({"mode": "auto", "intensity": 0.3}), resolved_hex="#ABCDEF"),
    ],
)
def test_complete_phase1_resolution_invariants_are_enforced(fabricated):
    with pytest.raises(PreviewContractError):
        _identity(resolution=fabricated)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (
            _resolution({"mode": "custom", "hex": "#71869A", "intensity": 0.3}),
            _resolution({"mode": "preset", "preset": "cool", "intensity": 0.3}),
        ),
        (
            _resolution(
                {"mode": "auto", "intensity": 0.3},
                {"track_preference": {"hex": "#ABCDEF"}},
            ),
            _resolution({"mode": "custom", "hex": "#ABCDEF", "intensity": 0.3}),
        ),
        (
            _resolution(
                {"mode": "auto", "intensity": 0.3},
                {"track_preference": {"hex": "#ABCDEF"}},
            ),
            _resolution(
                {"mode": "auto", "intensity": 0.3},
                {"album_palette": [{"hex": "#ABCDEF"}]},
            ),
        ),
        (
            _resolution({"mode": "custom", "hex": "#ABCDEF", "intensity": 0.3}),
            _resolution(
                {"mode": "custom", "hex": "#ABCDEF", "intensity": 0.3},
                {"mood": "same pixels, different input fingerprint"},
            ),
        ),
    ],
)
def test_equal_pixel_identity_retains_request_specific_resolution_provenance(left, right):
    left_identity = _identity(resolution=left)
    right_identity = _identity(resolution=right)

    assert left_identity.preview_id == right_identity.preview_id
    assert left_identity.resolution == left
    assert right_identity.resolution == right
    assert left_identity.resolution != right_identity.resolution
    left_result = PreviewResult.create(
        identity=left_identity,
        cache_status="miss",
        width=100,
        height=100,
        artifact_sha256="2" * 64,
    )
    right_result = PreviewResult.create(
        identity=right_identity,
        cache_status="hit",
        width=100,
        height=100,
        artifact_sha256="2" * 64,
    )
    assert left_result.treatment == left
    assert right_result.treatment == right


IDENTITY_DERIVED_REPLACEMENTS = [
    pytest.param(
        {"preview_id": "9" * 64, "retrieval_reference": "preview:" + "9" * 64},
        id="preview-id-and-reference",
    ),
    pytest.param({"source_sha256": "8" * 64}, id="source-sha256"),
    pytest.param(
        {"treatment": _resolution({"mode": "preset", "preset": "cool", "intensity": 0.3})},
        id="treatment-provenance",
    ),
    pytest.param({"cache_key_version": "preview-cache-key-v2"}, id="cache-key-version"),
    pytest.param({"resolver_version": "1.0.0-provisional.2"}, id="resolver-version"),
    pytest.param({"preset_mapping_version": "provisional-2"}, id="preset-mapping-version"),
    pytest.param({"renderer_version": "ffmpeg-still-v2"}, id="renderer-version"),
    pytest.param({"transform_version": "linear-luma-chroma-v2"}, id="transform-version"),
    pytest.param({"toolchain_fingerprint": "7" * 64}, id="toolchain-fingerprint"),
    pytest.param({"retrieval_reference": "preview:" + "9" * 64}, id="retrieval-reference"),
]


@pytest.mark.parametrize("changes", IDENTITY_DERIVED_REPLACEMENTS)
def test_direct_result_construction_rejects_forged_identity_metadata(changes):
    with pytest.raises(PreviewContractError):
        _direct_result(_result(), **changes)


@pytest.mark.parametrize("changes", IDENTITY_DERIVED_REPLACEMENTS)
def test_dataclass_replace_rejects_forged_identity_metadata(changes):
    with pytest.raises(PreviewContractError):
        replace(_result(), **changes)


def test_result_requires_trusted_identity_and_shallow_copy_preserves_binding():
    result = _result()
    values = result.to_dict()
    with pytest.raises(TypeError):
        PreviewResult.from_dict(values)
    copied = copy(result)
    assert copied == result
    assert copied._identity is result._identity
    with pytest.raises(FrozenInstanceError):
        copied.preview_id = "9" * 64


def test_equal_pixel_key_cannot_substitute_different_request_provenance():
    custom = _resolution({"mode": "custom", "hex": "#71869A", "intensity": 0.3})
    preset = _resolution({"mode": "preset", "preset": "cool", "intensity": 0.3})
    custom_identity = _identity(resolution=custom)
    preset_identity = _identity(resolution=preset)
    custom_result = _result(custom_identity)
    preset_result = _result(preset_identity)

    assert custom_identity.preview_id == preset_identity.preview_id
    assert custom_result.treatment == custom
    assert preset_result.treatment == preset
    assert PreviewResult.from_dict(custom_result.to_dict(), identity=custom_identity) == custom_result
    assert PreviewResult.from_dict(preset_result.to_dict(), identity=preset_identity) == preset_result
    with pytest.raises(PreviewContractError):
        PreviewResult.from_dict(custom_result.to_dict(), identity=preset_identity)
    with pytest.raises(PreviewContractError):
        replace(custom_result, _identity=preset_identity)


def test_models_are_frozen_and_nested_error_details_are_immutable():
    identity = _identity()
    error = PreviewError.create(
        code="PREVIEW_CACHE_CORRUPT",
        message="Cache entry is invalid.",
        correlation_id="correlation-1",
        details={"checks": ["metadata", "artifact"]},
    )

    with pytest.raises(FrozenInstanceError):
        identity.preview_id = "9" * 64
    with pytest.raises(TypeError):
        error.details["new"] = True
    assert isinstance(error.details["checks"], tuple)

    directly_constructed = PreviewError(
        code="PREVIEW_INTERNAL_ERROR",
        message="Unexpected failure.",
        details={"nested": ["value"]},
        correlation_id="correlation-2",
    )
    with pytest.raises(TypeError):
        directly_constructed.details["new"] = True
    assert isinstance(directly_constructed.details["nested"], tuple)


def test_error_details_accept_mappings_and_none_without_mutability():
    no_details = PreviewError.create(
        code="PREVIEW_TIMEOUT", message="Timed out.", correlation_id="correlation-1", details=None
    )
    mapped = PreviewError.create(
        code="PREVIEW_TIMEOUT",
        message="Timed out.",
        correlation_id="correlation-2",
        details=MappingProxyType({"nested": {"items": [1, 2]}}),
    )

    assert no_details.to_dict()["error"]["details"] == {}
    assert mapped.to_dict()["error"]["details"] == {"nested": {"items": [1, 2]}}
    with pytest.raises(TypeError):
        mapped.details["nested"]["items"] += (3,)


@pytest.mark.parametrize("details", [[], [("key", "value")], (("key", "value"),), "text", 1])
def test_error_details_reject_non_mappings(details):
    with pytest.raises(PreviewContractError):
        PreviewError.create(
            code="PREVIEW_TIMEOUT", message="Timed out.", correlation_id="correlation-1", details=details
        )


@pytest.mark.parametrize(
    "details",
    [
        {1: "value"},
        {"value": float("inf")},
        {"value": float("-inf")},
        {"value": float("nan")},
        {"value": "\ud800"},
        {"\ud800": "value"},
        {"value": ("not", "a", "json", "array")},
    ],
)
def test_error_details_reject_non_json_or_malformed_values(details):
    with pytest.raises(PreviewContractError):
        PreviewError.create(
            code="PREVIEW_TIMEOUT", message="Timed out.", correlation_id="correlation-1", details=details
        )


def test_phase3_versions_and_policy_are_pinned_to_phase2_contract():
    descriptor = _identity().descriptor.to_dict()
    assert descriptor["contract_version"] == PREVIEW_CACHE_KEY_VERSION
    assert descriptor["render_policy"]["geometry_policy_version"] == GEOMETRY_POLICY_VERSION
    assert PREVIEW_RENDERER_VERSION == PHASE2_RENDERER_VERSION
    assert PREVIEW_OUTPUT_MAX_DIMENSION == PHASE2_OUTPUT_MAX_DIMENSION
    assert descriptor["render_policy"]["renderer_version"] == PHASE2_RENDERER_VERSION
    assert descriptor["render_policy"]["transform_version"] == "linear-luma-chroma-v1"
    assert descriptor["render_policy"]["max_longest_side"] == PHASE2_OUTPUT_MAX_DIMENSION
    assert descriptor["render_policy"]["no_upscale"] is True
    assert DEFAULT_PREVIEW_CACHE_MAX_BYTES == 2 * 1024 * 1024 * 1024
    assert DEFAULT_PREVIEW_CACHE_MAX_ENTRIES == 2_000
    assert DEFAULT_PREVIEW_MAX_WAITING_REQUESTS == 4


def test_preview_policy_matches_phase2_geometry_orientation_and_ffmpeg_argv():
    resolution = _resolution()
    request = StillRenderRequest(
        contract_version=STILL_RENDER_REQUEST_VERSION,
        source_path=Path("source.png"),
        output_relative_path="preview.png",
        resolution=resolution,
    )
    argv = FFmpegStillImageRenderer._build_ffmpeg_argv(
        None,
        Path("ffmpeg.exe"),
        Path("source.png"),
        Path("preview.png"),
        request,
        6,
        1024,
        512,
    )
    filter_graph = argv[argv.index("-vf") + 1]

    assert _scaled_dimensions(2048, 1024, PHASE2_OUTPUT_MAX_DIMENSION) == (1024, 512)
    assert _scaled_dimensions(640, 480, PHASE2_OUTPUT_MAX_DIMENSION) == (640, 480)
    assert "-noautorotate" in argv
    assert filter_graph.startswith("transpose=clock,")
    assert "w=1024:h=512:filter=lanczos:dither=none" in filter_graph
    assert argv[argv.index("-c:v") + 1] == "png"
    assert argv[argv.index("-pix_fmt") + 1] == "rgba"
    assert argv[argv.index("-color_primaries") + 1] == "bt709"
    assert argv[argv.index("-color_trc") + 1] == "iec61966-2-1"
    assert argv[argv.index("-colorspace") + 1] == "rgb"


DESCRIPTOR_LEAF_PATHS = {
    ("contract_version",),
    ("source_sha256",),
    ("treatment", "state"),
    ("treatment", "resolved_hex"),
    ("treatment", "intensity"),
    ("treatment", "resolver_version"),
    ("treatment", "preset_mapping_version"),
    ("render_policy", "renderer_version"),
    ("render_policy", "transform_version"),
    ("render_policy", "geometry_policy_version"),
    ("render_policy", "orientation_policy_version"),
    ("render_policy", "max_longest_side"),
    ("render_policy", "no_upscale"),
    ("render_policy", "scale_filter"),
    ("render_policy", "dither"),
    ("render_policy", "output_format"),
    ("render_policy", "output_pixel_format"),
    ("render_policy", "color_primaries"),
    ("render_policy", "color_transfer"),
    ("render_policy", "color_space"),
    ("toolchain", "ffmpeg_sha256"),
    ("toolchain", "ffprobe_sha256"),
}


def _leaf_paths(value, prefix=()):
    paths = set()
    for key, item in value.items():
        path = prefix + (key,)
        if isinstance(item, dict):
            paths.update(_leaf_paths(item, path))
        else:
            paths.add(path)
    return paths


@pytest.mark.parametrize("path", sorted(DESCRIPTOR_LEAF_PATHS))
def test_every_descriptor_leaf_is_present_and_changes_the_digest(path):
    descriptor = _identity().descriptor.to_dict()
    assert _leaf_paths(descriptor) == DESCRIPTOR_LEAF_PATHS
    changed = deepcopy(descriptor)
    target = changed
    for part in path[:-1]:
        target = target[part]
    original = target[path[-1]]
    if type(original) is bool:
        replacement = not original
    elif type(original) in (int, float):
        replacement = original + 1
    elif original is None:
        replacement = "changed"
    else:
        replacement = f"{original}-changed"
    target[path[-1]] = replacement
    assert canonical_sha256(changed) != _identity().preview_id


def test_manually_fabricated_color_resolution_cannot_claim_untreated_nonzero_output():
    fabricated = ColorResolution(
        contract_version="color-resolution-output-v1",
        mode="auto",
        resolved_hex=None,
        preset_id="original",
        intensity=0.2,
        source="fallback",
        reason="no_usable_auto_color",
        resolver_version="1.0.0-provisional.1",
        preset_mapping_version="provisional-1",
        input_fingerprint="a" * 64,
    )
    with pytest.raises(PreviewContractError):
        _identity(resolution=fabricated)
