from __future__ import annotations

import math
import re


TRANSFORM_VERSION = "linear-luma-chroma-v1"
LUMINANCE_RED = 0.2126
LUMINANCE_GREEN = 0.7152
LUMINANCE_BLUE = 0.0722
_HEX_PATTERN = re.compile(r"^#[0-9A-F]{6}$")


def srgb_to_linear(channel: float) -> float:
    if not math.isfinite(channel) or not 0.0 <= channel <= 1.0:
        raise ValueError("sRGB channel must be finite and within [0, 1].")
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def linear_to_srgb(channel: float) -> float:
    if not math.isfinite(channel) or not 0.0 <= channel <= 1.0:
        raise ValueError("Linear RGB channel must be finite and within [0, 1].")
    if channel <= 0.0031308:
        return 12.92 * channel
    return 1.055 * (channel ** (1.0 / 2.4)) - 0.055


def srgb_hex_to_linear_rgb(hex_color: str) -> tuple[float, float, float]:
    if not isinstance(hex_color, str) or not _HEX_PATTERN.fullmatch(hex_color):
        raise ValueError("Resolved color must be normalized uppercase six-digit sRGB HEX.")
    return tuple(
        srgb_to_linear(int(hex_color[offset : offset + 2], 16) / 255.0)
        for offset in (1, 3, 5)
    )


def apply_luminance_preserving_tint(
    source_srgb: tuple[float, float, float],
    target_srgb_hex: str,
    intensity: float,
) -> tuple[float, float, float]:
    """Reference implementation of linear-luma-chroma-v1 for one opaque pixel.

    The target chromaticity is scaled to unit Rec.709 luminance. The source
    luminance is then held constant while chroma moves toward that target.
    Out-of-gamut results are desaturated toward neutral at the same luminance.
    """
    if len(source_srgb) != 3:
        raise ValueError("Source pixel must have three RGB channels.")
    if type(intensity) not in (int, float) or not math.isfinite(intensity) or not 0.0 <= intensity <= 0.6:
        raise ValueError("Intensity must be finite and within [0.0, 0.6].")
    source_linear = tuple(srgb_to_linear(channel) for channel in source_srgb)
    target_linear = srgb_hex_to_linear_rgb(target_srgb_hex)
    source_luminance = _luminance(source_linear)
    target_luminance = _luminance(target_linear)
    if intensity == 0.0 or source_luminance == 0.0 or target_luminance == 0.0:
        return tuple(_quantize_8bit_srgb(channel) for channel in source_srgb)

    target_chromaticity = tuple(channel / target_luminance for channel in target_linear)
    candidate = tuple(
        (1.0 - intensity) * source_channel
        + intensity * source_luminance * target_channel
        for source_channel, target_channel in zip(source_linear, target_chromaticity)
    )
    neutral = (source_luminance, source_luminance, source_luminance)
    differences = tuple(value - gray for value, gray in zip(candidate, neutral))
    gamut_scale = 1.0
    for difference in differences:
        if difference > 0.0:
            gamut_scale = min(gamut_scale, (1.0 - source_luminance) / difference)
        elif difference < 0.0:
            gamut_scale = min(gamut_scale, source_luminance / -difference)
    gamut_scale = min(1.0, max(0.0, gamut_scale))
    output_linear = tuple(
        min(1.0, max(0.0, gray + gamut_scale * difference))
        for gray, difference in zip(neutral, differences)
    )
    output_srgb = tuple(linear_to_srgb(channel) for channel in output_linear)
    return tuple(_quantize_8bit_srgb(channel) for channel in output_srgb)


def quantize_srgb_8bit(channel: float) -> int:
    """Quantize with round-to-nearest, ties upward, after gamut clipping."""
    if not math.isfinite(channel):
        raise ValueError("sRGB channel must be finite.")
    bounded = min(1.0, max(0.0, channel))
    return math.floor(bounded * 255.0 + 0.5)


def _quantize_8bit_srgb(channel: float) -> float:
    return quantize_srgb_8bit(channel) / 255.0


def _luminance(rgb: tuple[float, float, float]) -> float:
    return (
        LUMINANCE_RED * rgb[0]
        + LUMINANCE_GREEN * rgb[1]
        + LUMINANCE_BLUE * rgb[2]
    )