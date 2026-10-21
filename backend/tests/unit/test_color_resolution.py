import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

import wrld_video_studio.domain.color_resolution as color_resolution
from wrld_video_studio.domain.color_resolution import (
    INPUT_CONTRACT_VERSION,
    MAX_INTENSITY,
    MIN_INTENSITY,
    OUTPUT_CONTRACT_VERSION,
    PRESET_HEX_BY_ID,
    PRESET_MAPPING_VERSION,
    RESOLVER_VERSION,
    ColorResolutionError,
    resolve_color_treatment,
)


def payload(treatment, context=None):
    result = {"contract_version": INPUT_CONTRACT_VERSION, "treatment": treatment}
    if context is not None:
        result["context"] = context
    return result


@pytest.mark.parametrize("preset_id", PRESET_HEX_BY_ID)
def test_every_preset_resolves_with_versioned_mapping(preset_id):
    expected_hex = {
        "original": None,
        "cool": "#71869A",
        "warm": "#B47B55",
        "lavender": "#887A9B",
        "teal": "#5F817B",
        "dark": "#48525A",
    }
    result = resolve_color_treatment(
        payload({"mode": "preset", "preset": preset_id, "intensity": 0.4})
    )

    assert result.mode == "preset"
    assert result.preset_id == preset_id
    assert result.resolved_hex == expected_hex[preset_id]
    assert result.intensity == (0.0 if preset_id == "original" else 0.4)
    assert result.preset_mapping_version == PRESET_MAPPING_VERSION


def test_custom_and_auto_modes_resolve():
    custom = resolve_color_treatment(
        payload({"mode": "custom", "hex": "#aBcD09", "intensity": 0.3})
    )
    automatic = resolve_color_treatment(
        payload(
            {"mode": "auto", "intensity": 0.2},
            {"album_palette": [{"hex": "#37aBc1"}]},
        )
    )

    assert (custom.resolved_hex, custom.source, custom.reason) == (
        "#ABCD09",
        "user_selection",
        "explicit_custom",
    )
    assert (automatic.resolved_hex, automatic.source, automatic.reason) == (
        "#37ABC1",
        "album_palette",
        "first_palette_entry",
    )


@pytest.mark.parametrize(
    ("context", "resolved_hex", "preset_id", "source", "reason"),
    [
        ({"track_preference": {"hex": "#123456"}, "album_palette": [{"hex": "#ABCDEF"}]}, "#123456", None, "track_preference", "explicit_track_preference"),
        ({"album_palette": [{"hex": "#ABCDEF"}, {"hex": "#010203"}]}, "#ABCDEF", None, "album_palette", "first_palette_entry"),
        ({"album_default_preset": "warm"}, "#B47B55", "warm", "album_default", "album_default_preset"),
        ({"album_default_preset": "original"}, None, "original", "album_default", "album_default_original"),
        ({"mood": "  🌫 unknown mood  ", "features": {"energy": 0.7}}, None, "original", "fallback", "no_usable_auto_color"),
    ],
)
def test_auto_precedence_returns_exact_source_and_reason(context, resolved_hex, preset_id, source, reason):
    result = resolve_color_treatment(payload({"mode": "auto", "intensity": 0.5}, context))

    assert (result.resolved_hex, result.preset_id, result.source, result.reason) == (
        resolved_hex,
        preset_id,
        source,
        reason,
    )
    assert result.intensity == (0.0 if resolved_hex is None else 0.5)


def test_explicit_custom_and_preset_override_conflicting_valid_auto_context():
    conflicting_context = {
        "track_preference": {"hex": "#111111"},
        "album_palette": [{"hex": "#222222"}],
        "album_default_preset": "teal",
    }
    custom = resolve_color_treatment(
        payload({"mode": "custom", "hex": "#ABCDEF", "intensity": 0.2}, conflicting_context)
    )
    preset = resolve_color_treatment(
        payload({"mode": "preset", "preset": "warm", "intensity": 0.2}, conflicting_context)
    )

    assert (custom.resolved_hex, custom.source, custom.reason) == (
        "#ABCDEF", "user_selection", "explicit_custom"
    )
    assert (preset.resolved_hex, preset.source, preset.reason) == (
        "#B47B55", "user_selection", "explicit_preset"
    )


def test_auto_falls_back_to_album_default_then_original():
    defaulted = resolve_color_treatment(
        payload(
            {"mode": "auto", "intensity": 0.4},
            {"album_palette": [], "album_default_preset": "teal", "mood": "unknown"},
        )
    )
    original_default = resolve_color_treatment(
        payload({"mode": "auto", "intensity": 0.4}, {"album_default_preset": "original"})
    )
    fallback = resolve_color_treatment(payload({"mode": "auto", "intensity": 0.4}))

    assert (defaulted.resolved_hex, defaulted.source, defaulted.intensity) == (
        PRESET_HEX_BY_ID["teal"],
        "album_default",
        0.4,
    )
    assert (original_default.resolved_hex, original_default.preset_id, original_default.intensity) == (
        None,
        "original",
        0.0,
    )
    assert (fallback.resolved_hex, fallback.preset_id, fallback.source, fallback.intensity) == (
        None,
        "original",
        "fallback",
        0.0,
    )


def test_unknown_unicode_mood_with_missing_features_uses_deterministic_fallback():
    context = {"mood": "未知の感情 ☁"}
    first = resolve_color_treatment(payload({"mode": "auto", "intensity": 0.4}, context))
    second = resolve_color_treatment(payload({"mode": "auto", "intensity": 0.4}, context))

    assert (first.resolved_hex, first.preset_id, first.intensity, first.reason) == (
        None,
        "original",
        0.0,
        "no_usable_auto_color",
    )
    assert first.input_fingerprint == second.input_fingerprint


@pytest.mark.parametrize("hex_value", ["#000000", "#aBcD09", "#FFFFFF"])
def test_custom_hex_accepts_six_digit_srgb_and_normalizes_uppercase(hex_value):
    result = resolve_color_treatment(payload({"mode": "custom", "hex": hex_value, "intensity": 0.2}))
    assert result.resolved_hex == hex_value.upper()


@pytest.mark.parametrize("hex_value", ["#FFF", "123456", "#12345", "#1234567", "#12GG56", None, 123456])
def test_custom_hex_rejects_invalid_values(hex_value):
    with pytest.raises(ColorResolutionError) as raised:
        resolve_color_treatment(payload({"mode": "custom", "hex": hex_value, "intensity": 0.2}))
    assert raised.value.code == "COLOR_INVALID_HEX"


@pytest.mark.parametrize("intensity", [MIN_INTENSITY, MAX_INTENSITY, 0, 0.3])
def test_intensity_accepts_finite_inclusive_bounds(intensity):
    result = resolve_color_treatment(
        payload({"mode": "auto", "intensity": intensity}, {"album_palette": [{"hex": "#123456"}]})
    )
    assert result.intensity == float(intensity)


@pytest.mark.parametrize("intensity", [-0.0001, 0.6001, float("nan"), float("inf"), -float("inf"), True, "0.2", None])
def test_intensity_rejects_out_of_range_non_finite_and_wrong_types(intensity):
    with pytest.raises(ColorResolutionError) as raised:
        resolve_color_treatment(payload({"mode": "auto", "intensity": intensity}))
    assert raised.value.code == "COLOR_INVALID_INTENSITY"


def test_explicit_original_is_untreated_even_with_positive_intensity():
    result = resolve_color_treatment(
        payload({"mode": "preset", "preset": "original", "intensity": 0.6})
    )
    assert result.resolved_hex is None
    assert result.intensity == 0.0
    assert result.reason == "explicit_original"


@pytest.mark.parametrize(
    ("treatment", "code"),
    [
        ({"mode": "unexpected", "intensity": 0.2}, "COLOR_INVALID_MODE"),
        ({"mode": "preset", "preset": "unknown", "intensity": 0.2}, "COLOR_INVALID_PRESET"),
        ({"mode": "auto", "intensity": 0.2, "hex": "#112233"}, "COLOR_INVALID_INPUT"),
        ({"mode": "preset", "preset": [], "intensity": 0.2}, "COLOR_INVALID_PRESET"),
    ],
)
def test_invalid_contract_values_have_stable_typed_errors(treatment, code):
    with pytest.raises(ColorResolutionError) as raised:
        resolve_color_treatment(payload(treatment))
    assert raised.value.code == code
    assert raised.value.message


@pytest.mark.parametrize(
    ("context", "code"),
    [
        ({"track_preference": {}}, "COLOR_INVALID_INPUT"),
        ({"track_preference": {"hex": "#123456", "extra": 1}}, "COLOR_INVALID_INPUT"),
        ({"track_preference": {"hex": "bad"}}, "COLOR_INVALID_HEX"),
        ({"album_default_preset": 17}, "COLOR_INVALID_PRESET"),
        ({"album_default_preset": "unknown"}, "COLOR_INVALID_PRESET"),
        ({"album_palette": None}, "COLOR_INVALID_INPUT"),
        ({"album_palette": [{"hex": "bad"}, {"hex": "#ABCDEF"}]}, "COLOR_INVALID_HEX"),
        ({"album_palette": [{"hex": "#123456", "name": 7}]}, "COLOR_INVALID_INPUT"),
        ({"album_palette": [{"hex": "#123456", "extra": True}]}, "COLOR_INVALID_INPUT"),
        ({"features": None}, "COLOR_INVALID_INPUT"),
        ({"features": {"energy": True}}, "COLOR_INVALID_INPUT"),
        ({"features": {"energy": float("nan")}}, "COLOR_INVALID_INPUT"),
        ({"features": {"energy": float("inf")}}, "COLOR_INVALID_INPUT"),
        ({"features": {"energy": 10**400}}, "COLOR_INVALID_INPUT"),
    ],
)
def test_malformed_nested_context_is_rejected_with_typed_errors(context, code):
    with pytest.raises(ColorResolutionError) as raised:
        resolve_color_treatment(payload({"mode": "auto", "intensity": 0.2}, context))
    assert raised.value.code == code


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), {"not": "json"}, object(), {1, 2}, "\ud800"])
def test_malformed_json_like_metadata_never_escapes_typed_error_boundary(bad_value):
    context = {"mood": bad_value}
    with pytest.raises(ColorResolutionError) as raised:
        resolve_color_treatment(payload({"mode": "auto", "intensity": 0.2}, context))
    assert raised.value.code == "COLOR_INVALID_INPUT"


def test_nan_intensity_uses_stable_intensity_error():
    with pytest.raises(ColorResolutionError) as raised:
        resolve_color_treatment(payload({"mode": "auto", "intensity": float("nan")}))
    assert raised.value.code == "COLOR_INVALID_INTENSITY"


def test_metadata_is_not_mutated_and_result_is_immutable():
    supplied = payload(
        {"mode": "custom", "hex": "#abcdef", "intensity": 0.25},
        {"mood": "free form mood", "features": {"brightness": 0.4}},
    )
    before = deepcopy(supplied)
    result = resolve_color_treatment(supplied)

    assert supplied == before
    with pytest.raises((AttributeError, TypeError)):
        result.mode = "preset"
    assert result.mode == "custom"


def test_error_details_are_deeply_immutable():
    error = ColorResolutionError("COLOR_INVALID_INPUT", "bad input", {"nested": {"items": [1, 2]}})

    with pytest.raises(TypeError):
        error.details["nested"]["new"] = 3
    with pytest.raises(TypeError):
        error.details["nested"]["items"][0] = 9
    with pytest.raises(AttributeError):
        error.details = {}
    assert error.details["nested"]["items"] == (1, 2)


def test_fingerprint_is_stable_for_mapping_order_and_normalized_hex_case():
    first = payload(
        {"mode": "custom", "hex": "#abcdef", "intensity": 0.2},
        {"mood": "opaque", "album_palette": [{"hex": "#123456", "name": "x"}]},
    )
    second = {
        "context": {"album_palette": [{"name": "x", "hex": "#123456"}], "mood": "opaque"},
        "treatment": {"intensity": 0.2, "hex": "#ABCDEF", "mode": "custom"},
        "contract_version": INPUT_CONTRACT_VERSION,
    }
    assert resolve_color_treatment(first).input_fingerprint == resolve_color_treatment(second).input_fingerprint


def test_fingerprint_normalizes_auto_palette_hex_case():
    lower = payload({"mode": "auto", "intensity": 0.2}, {"album_palette": [{"hex": "#abcdef"}]})
    upper = payload({"mode": "auto", "intensity": 0.2}, {"album_palette": [{"hex": "#ABCDEF"}]})
    assert resolve_color_treatment(lower).input_fingerprint == resolve_color_treatment(upper).input_fingerprint


def test_negative_zero_intensity_has_same_effective_value_and_fingerprint_as_zero():
    context = {"album_palette": [{"hex": "#123456"}]}
    negative_zero = resolve_color_treatment(payload({"mode": "auto", "intensity": -0.0}, context))
    positive_zero = resolve_color_treatment(payload({"mode": "auto", "intensity": 0.0}, context))

    assert negative_zero.intensity == positive_zero.intensity == 0.0
    assert str(negative_zero.intensity) == "0.0"
    assert negative_zero.input_fingerprint == positive_zero.input_fingerprint


def test_fingerprint_changes_for_meaningful_treatment_or_context_changes():
    base = resolve_color_treatment(
        payload({"mode": "custom", "hex": "#123456", "intensity": 0.2}, {"mood": "calm"})
    )
    changed_hex = resolve_color_treatment(
        payload({"mode": "custom", "hex": "#123457", "intensity": 0.2}, {"mood": "calm"})
    )
    changed_context = resolve_color_treatment(
        payload({"mode": "custom", "hex": "#123456", "intensity": 0.2}, {"mood": "tense"})
    )
    changed_intensity = resolve_color_treatment(
        payload({"mode": "custom", "hex": "#123456", "intensity": 0.3}, {"mood": "calm"})
    )

    assert len({base.input_fingerprint, changed_hex.input_fingerprint, changed_context.input_fingerprint, changed_intensity.input_fingerprint}) == 4


def test_fingerprint_changes_when_resolver_or_mapping_version_changes(monkeypatch):
    value = payload({"mode": "custom", "hex": "#123456", "intensity": 0.2})
    baseline = resolve_color_treatment(value).input_fingerprint

    monkeypatch.setattr(color_resolution, "RESOLVER_VERSION", "test-resolver-version")
    changed_resolver = resolve_color_treatment(value).input_fingerprint
    monkeypatch.setattr(color_resolution, "RESOLVER_VERSION", RESOLVER_VERSION)
    monkeypatch.setattr(color_resolution, "PRESET_MAPPING_VERSION", "test-mapping-version")
    changed_mapping = resolve_color_treatment(value).input_fingerprint

    assert baseline != changed_resolver
    assert baseline != changed_mapping


def test_fingerprint_matches_independent_canonical_sha256():
    from wrld_video_studio.domain.canonical_json import canonical_json_bytes

    input_value = payload({"mode": "custom", "hex": "#abcdef", "intensity": 0.2})
    result = resolve_color_treatment(input_value)
    fingerprint_input = {
        "input": payload({"mode": "custom", "hex": "#ABCDEF", "intensity": 0.2}),
        "resolver_version": RESOLVER_VERSION,
        "preset_mapping_version": PRESET_MAPPING_VERSION,
    }
    encoded = json.dumps(
        fingerprint_input,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    assert hashlib.sha256(encoded).hexdigest() == result.input_fingerprint
    assert canonical_json_bytes(fingerprint_input) == encoded


def test_fingerprint_is_deterministic_in_a_separate_process():
    root = Path(__file__).resolve().parents[3]
    environment = os.environ.copy()
    source_path = str(root / "backend" / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (source_path, environment.get("PYTHONPATH", "")) if item
    )
    script = (
        "from wrld_video_studio.domain.color_resolution import resolve_color_treatment; "
        "print(resolve_color_treatment({'contract_version':'color-resolution-input-v1',"
        "'treatment':{'mode':'custom','hex':'#123456','intensity':0.2},"
        "'context':{'mood':'calm'}}).input_fingerprint)"
    )
    first = subprocess.check_output([sys.executable, "-c", script], env=environment, text=True).strip()
    second = subprocess.check_output([sys.executable, "-c", script], env=environment, text=True).strip()

    assert first == second
    assert len(first) == 64


def test_resolver_contract_and_versions_are_explicit():
    result = resolve_color_treatment(payload({"mode": "auto", "intensity": 0.2})).to_dict()
    assert result["contract_version"] == OUTPUT_CONTRACT_VERSION
    assert result["resolver_version"] == RESOLVER_VERSION
    assert result["preset_mapping_version"] == PRESET_MAPPING_VERSION
    assert len(result["input_fingerprint"]) == 64