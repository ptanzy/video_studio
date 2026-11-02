import math

import pytest

from wrld_video_studio.domain.color_transform import (
    TRANSFORM_VERSION,
    apply_luminance_preserving_tint,
    linear_to_srgb,
    quantize_srgb_8bit,
    srgb_hex_to_linear_rgb,
    srgb_to_linear,
)


def luminance(rgb):
    return 0.2126 * srgb_to_linear(rgb[0]) + 0.7152 * srgb_to_linear(rgb[1]) + 0.0722 * srgb_to_linear(rgb[2])


@pytest.mark.parametrize(
    ("srgb", "linear"),
    [(0.0, 0.0), (0.04045, 0.0031308049535603713), (1.0, 1.0)],
)
def test_srgb_transfer_breakpoints(srgb, linear):
    assert srgb_to_linear(srgb) == pytest.approx(linear, abs=1e-12)
    assert linear_to_srgb(linear) == pytest.approx(srgb, abs=5e-8)


def test_transform_version_and_target_hex_decoding_are_explicit():
    assert TRANSFORM_VERSION == "linear-luma-chroma-v1"
    assert srgb_hex_to_linear_rgb("#FFFFFF") == (1.0, 1.0, 1.0)
    assert srgb_hex_to_linear_rgb("#000000") == (0.0, 0.0, 0.0)


@pytest.mark.parametrize("target", ["#71869A", "#B47B55", "#887A9B", "#5F817B", "#48525A", "#15A0E7"])
def test_transform_preserves_source_luminance_and_returns_gamut_bounded_rgb(target):
    source_pixels = [
        (0.0, 0.0, 0.0),
        (1.0, 1.0, 1.0),
        (0.02, 0.01, 0.0),
        (0.95, 0.98, 1.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.5, 0.5, 0.5),
    ]
    for source in source_pixels:
        treated = apply_luminance_preserving_tint(source, target, 0.6)
        assert all(0.0 <= channel <= 1.0 for channel in treated)
        assert abs(luminance(treated) - luminance(source)) <= 0.004


@pytest.mark.parametrize("target", ["#71869A", "#B47B55", "#887A9B", "#5F817B", "#48525A", "#15A0E7"])
def test_zero_intensity_is_untreated_after_explicit_8bit_quantization(target):
    for source in [(0, 0, 0), (1, 1, 1), (0.2, 0.4, 0.8), (1, 0, 0)]:
        assert apply_luminance_preserving_tint(source, target, 0.0) == tuple(
            quantize_srgb_8bit(channel) / 255 for channel in source
        )


@pytest.mark.parametrize("intensity", [0.0, 0.0001, 0.6])
def test_transform_accepts_intensity_endpoints_and_small_positive_values(intensity):
    result = apply_luminance_preserving_tint((0.7, 0.3, 0.1), "#71869A", intensity)
    assert all(0.0 <= value <= 1.0 for value in result)


@pytest.mark.parametrize("channel", [-0.01, 1.01, float("nan"), float("inf")])
def test_transfer_functions_reject_invalid_channels(channel):
    with pytest.raises(ValueError):
        srgb_to_linear(channel)
    with pytest.raises(ValueError):
        linear_to_srgb(channel)


@pytest.mark.parametrize("target", ["#fff", "#12GG56", "#abcdef", "red", None])
def test_transform_rejects_non_normalized_or_malformed_target_hex(target):
    with pytest.raises(ValueError):
        apply_luminance_preserving_tint((0.5, 0.5, 0.5), target, 0.2)


@pytest.mark.parametrize("intensity", [-0.1, 0.6001, float("nan"), math.inf, True, "0.2"])
def test_transform_rejects_invalid_intensity(intensity):
    with pytest.raises(ValueError):
        apply_luminance_preserving_tint((0.5, 0.5, 0.5), "#71869A", intensity)


def test_black_target_safely_behaves_as_untreated_in_reference_transform():
    assert srgb_hex_to_linear_rgb("#000000") == (0.0, 0.0, 0.0)
    result = apply_luminance_preserving_tint((0.5, 0.5, 0.5), "#000000", 0.3)
    assert result == tuple(quantize_srgb_8bit(channel) / 255 for channel in (0.5, 0.5, 0.5))


@pytest.mark.parametrize(
    ("source", "target", "intensity", "expected_8bit"),
    [
        ((0.5, 0.5, 0.5), "#B47B55", 0.6, (154, 120, 102)),
        ((1.0, 0.0, 0.0), "#71869A", 0.6, (186, 102, 118)),
        ((0.0, 1.0, 0.0), "#887A9B", 0.6, (186, 230, 211)),
        ((0.0, 0.0, 1.0), "#5F817B", 0.6, (44, 62, 178)),
        ((2 / 255, 1 / 255, 0.0), "#B47B55", 0.6, (2, 1, 0)),
        ((248 / 255, 252 / 255, 1.0), "#B47B55", 0.6, (255, 251, 249)),
        ((0.25, 0.5, 0.75), "#808080", 0.6, (105, 125, 155)),
        ((0.2, 0.4, 0.8), "#000000", 0.6, (51, 102, 204)),
    ],
)
def test_reviewed_fixed_vectors_cover_gamut_extremes_and_black_noop(
    source, target, intensity, expected_8bit
):
    actual = apply_luminance_preserving_tint(source, target, intensity)
    assert tuple(round(channel * 255) for channel in actual) == expected_8bit


@pytest.mark.parametrize(
    ("channel", "expected"),
    [
        (0.5 / 255, 1),
        ((1.5 - 1e-12) / 255, 1),
        (1.5 / 255, 2),
        (254.5 / 255, 255),
    ],
)
def test_quantization_is_nearest_with_exact_ties_upward(channel, expected):
    assert quantize_srgb_8bit(channel) == expected
