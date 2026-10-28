from __future__ import annotations

import math
import re


OUTPUT_WIDTH = 1920
OUTPUT_HEIGHT = 1080
SAFE_MARGIN = 64
SAFE_RIGHT = OUTPUT_WIDTH - SAFE_MARGIN
SAFE_BOTTOM = OUTPUT_HEIGHT - SAFE_MARGIN
PROGRESS_WIDTH = OUTPUT_WIDTH - 2 * SAFE_MARGIN
GLOW_SIGMA_PX = 12
GLOW_PADDING_PX = 36

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def normalize_hex(value: str) -> str:
    if type(value) is not str or _HEX.fullmatch(value) is None:
        raise ValueError("color must be an exact six-digit HEX value")
    return value.upper()


def derive_glow_color(color: str) -> str:
    channels = _decode_hex(color)
    return _encode_hex(tuple(0.75 * channel + 0.25 for channel in channels))


def relative_luminance(color: str) -> float:
    red, green, blue = _decode_hex(color)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def derive_rail_color(color: str, strength: float) -> str:
    if type(strength) not in (int, float) or not math.isfinite(float(strength)):
        raise ValueError("rail contrast strength must be finite")
    strength = float(strength)
    if not 0.0 <= strength <= 1.0:
        raise ValueError("rail contrast strength is outside the supported range")
    channels = _decode_hex(color)
    target = 0.0 if relative_luminance(color) >= 0.5 else 1.0
    return _encode_hex(
        tuple((1.0 - strength) * channel + strength * target for channel in channels)
    )


def refined_bar_layout(
    bar_count: int,
    placement: str,
    zone_width_px: int,
    zone_height_px: int,
    gap_px: int,
    horizontal_offset_px: int,
    bottom_margin_px: int,
) -> tuple[int, int, int, int, int]:
    usable = zone_width_px - gap_px * (bar_count - 1)
    if usable < bar_count:
        raise ValueError("bar geometry does not leave at least one pixel per bar")
    bar_width = usable // bar_count
    occupied = bar_width * bar_count + gap_px * (bar_count - 1)
    base_x = {
        "bottom_left": SAFE_MARGIN,
        "bottom_center": (OUTPUT_WIDTH - zone_width_px) // 2,
        "bottom_right": SAFE_RIGHT - zone_width_px,
    }.get(placement)
    if base_x is None:
        raise ValueError("bar placement is unsupported")
    zone_x = base_x + horizontal_offset_px
    zone_y = OUTPUT_HEIGHT - bottom_margin_px - zone_height_px
    if (
        zone_x < SAFE_MARGIN
        or zone_x + zone_width_px > SAFE_RIGHT
        or zone_y < SAFE_MARGIN
        or zone_y + zone_height_px > SAFE_BOTTOM
    ):
        raise ValueError("bar zone is outside the approved safe rectangle")
    start_x = zone_x + (zone_width_px - occupied) // 2
    return start_x, zone_y, bar_width, occupied, zone_x


def organic_multiplier(bar_index: int, presentation_sample: int) -> float:
    if type(bar_index) is not int or bar_index < 0:
        raise ValueError("bar index must be a nonnegative integer")
    if type(presentation_sample) is not int or presentation_sample < 0:
        raise ValueError("presentation sample must be a nonnegative integer")
    time_seconds = presentation_sample / 48_000.0
    phi = 2.0 * math.pi * _fract((bar_index + 0.5) * 0.61803398875)
    psi = 2.0 * math.pi * _fract((bar_index + 0.5) * 0.41421356237)
    return (
        0.70
        + 0.18 * (0.5 + 0.5 * math.sin(2.0 * math.pi * 0.11 * time_seconds + phi))
        + 0.12 * (0.5 + 0.5 * math.sin(2.0 * math.pi * 0.037 * time_seconds + psi))
    )


def refined_bar_heights(
    amplitude: float,
    bar_count: int,
    zone_height_px: int,
    variation_mode: str,
    presentation_sample: int,
) -> tuple[int, ...]:
    if type(amplitude) not in (int, float) or not math.isfinite(float(amplitude)):
        raise ValueError("amplitude must be finite")
    amplitude = float(amplitude)
    if not 0.0 <= amplitude <= 1.0:
        raise ValueError("amplitude must be between zero and one")
    values: list[int] = []
    for index in range(bar_count):
        if variation_mode == "organic_rms":
            multiplier = organic_multiplier(index, presentation_sample)
        elif variation_mode == "symmetrical":
            multiplier = 0.25 + 0.75 * math.sin(math.pi * (index + 0.5) / bar_count) ** 2
        else:
            raise ValueError("bar variation mode is unsupported")
        scaled = (zone_height_px - 2) * min(1.0, max(0.0, amplitude * multiplier))
        height = 2 + math.floor(scaled + 0.5)
        values.append(min(zone_height_px, max(2, height)))
    return tuple(values)


def _fract(value: float) -> float:
    return value - math.floor(value)


def _decode_hex(value: str) -> tuple[float, float, float]:
    normalized = normalize_hex(value)
    encoded = tuple(int(normalized[index : index + 2], 16) / 255.0 for index in (1, 3, 5))
    return tuple(_linearize(channel) for channel in encoded)  # type: ignore[return-value]


def _encode_hex(channels: tuple[float, float, float]) -> str:
    encoded = []
    for channel in channels:
        value = _encode_channel(min(1.0, max(0.0, channel)))
        encoded.append(min(255, max(0, math.floor(value * 255.0 + 0.5))))
    return "#" + "".join(f"{value:02X}" for value in encoded)


def _linearize(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _encode_channel(value: float) -> float:
    return 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1.0 / 2.4) - 0.055
