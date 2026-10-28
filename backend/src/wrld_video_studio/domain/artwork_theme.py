from __future__ import annotations

import colorsys
from collections import Counter
from typing import Iterable

from wrld_video_studio.domain.player_overlay import PALETTE_ALGORITHM_VERSION, ResolvedTheme, ThemeSettings
from wrld_video_studio.domain.visual_refinement import derive_rail_color, normalize_hex, relative_luminance


# (saturation scale, accent/white mix, footer/black mix). These constants are
# renderer identity through PALETTE_ALGORITHM_VERSION and may only change in a
# future palette generation.
PRESET_CONSTANTS = {
    "subtle": (0.65, 0.18, 0.78),
    "balanced": (0.90, 0.10, 0.68),
    "vibrant": (1.20, 0.04, 0.58),
}
ORDINARY_TEXT_CONTRAST_MINIMUM = 4.5
LARGE_TEXT_CONTRAST_MINIMUM = 3.0


class ArtworkThemeContrastError(ValueError):
    pass


def resolve_artwork_theme(
    pixels: Iterable[tuple[int, int, int]],
    artwork_sha256: str,
    settings: ThemeSettings,
    *,
    footer_opacity: float,
) -> ResolvedTheme:
    values = tuple(pixels)
    if not values:
        raise ValueError("artwork palette input is empty")
    bins = Counter((red >> 4, green >> 4, blue >> 4) for red, green, blue in values)
    # Count first, then luminance and RGB tuple to provide a stable tie break.
    key = max(bins, key=lambda item: (bins[item], relative_luminance(_bin_hex(item)), item))
    dominant = _bin_hex(key)
    saturation, white_mix, black_mix = PRESET_CONSTANTS[settings.preset]
    accent = _adjust_saturation(dominant, saturation)
    visualizer = _mix(accent, "#FFFFFF", white_mix)
    footer = _mix(dominant, "#000000", black_mix)
    fill = accent
    rail = derive_rail_color(fill, 0.60)
    colors = {
        "footer_background": footer,
        "primary_text": "#FFFFFF",
        "secondary_text": "#D1D5DB",
        "progress_fill": fill,
        "progress_rail": rail,
        "visualizer": visualizer,
    }
    provenance = {name: ("derived" if name in {"primary_text", "secondary_text", "progress_rail"} else "artwork") for name in colors}
    if settings.mode in {"manual", "hybrid"}:
        for name, value in settings.overrides.to_dict().items():
            if value is not None:
                colors[name] = value
                provenance[name] = "manual"
    composited = _mix(dominant, colors["footer_background"], footer_opacity)
    if settings.overrides.primary_text is None:
        colors["primary_text"] = (
            "#FFFFFF"
            if _contrast("#FFFFFF", composited) >= _contrast("#101010", composited)
            else "#101010"
        )
        provenance["primary_text"] = "derived"
    if settings.overrides.secondary_text is None:
        colors["secondary_text"] = _mix(
            colors["primary_text"], colors["footer_background"], 0.22
        )
        if _contrast(colors["secondary_text"], composited) < ORDINARY_TEXT_CONTRAST_MINIMUM:
            colors["secondary_text"] = (
                "#FFFFFF"
                if _contrast("#FFFFFF", composited) >= _contrast("#101010", composited)
                else "#101010"
            )
        provenance["secondary_text"] = "derived"
    for role in ("primary_text", "secondary_text"):
        ratio = _contrast(colors[role], composited)
        if ratio < ORDINARY_TEXT_CONTRAST_MINIMUM:
            source = provenance[role]
            if source == "manual":
                raise ArtworkThemeContrastError(
                    f"manual {role} contrast is {ratio:.2f}:1; "
                    f"at least {ORDINARY_TEXT_CONTRAST_MINIMUM:.1f}:1 is required"
                )
            replacement = (
                "#FFFFFF"
                if _contrast("#FFFFFF", composited) >= _contrast("#101010", composited)
                else "#101010"
            )
            colors[role] = replacement
    if settings.mode == "manual":
        dominant = colors["footer_background"]
    return ResolvedTheme(
        artwork_sha256=artwork_sha256,
        palette_algorithm_version=PALETTE_ALGORITHM_VERSION,
        mode=settings.mode,
        preset=settings.preset,
        dominant_color=dominant,
        provenance=provenance,
        **colors,
    )


def contrast_ratio(first: str, second: str) -> float:
    return _contrast(normalize_hex(first), normalize_hex(second))


def composited_footer_color(artwork_color: str, footer_color: str, opacity: float) -> str:
    return _mix(normalize_hex(artwork_color), normalize_hex(footer_color), opacity)


def text_contrast_is_compliant(text: str, background: str, *, large: bool = False) -> bool:
    minimum = LARGE_TEXT_CONTRAST_MINIMUM if large else ORDINARY_TEXT_CONTRAST_MINIMUM
    return contrast_ratio(text, background) >= minimum


def _bin_hex(value: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{channel * 17:02X}" for channel in value)


def _decode(value: str) -> tuple[float, float, float]:
    value = normalize_hex(value)
    return tuple(int(value[index:index + 2], 16) / 255 for index in (1, 3, 5))  # type: ignore[return-value]


def _encode(value: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{min(255, max(0, int(channel * 255 + 0.5))):02X}" for channel in value)


def _mix(first: str, second: str, amount: float) -> str:
    a, b = _decode(first), _decode(second)
    return _encode(tuple((1 - amount) * left + amount * right for left, right in zip(a, b, strict=True)))


def _adjust_saturation(value: str, scale: float) -> str:
    red, green, blue = _decode(value)
    hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
    return _encode(colorsys.hls_to_rgb(hue, lightness, min(1.0, saturation * scale)))


def _linear(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _contrast(first: str, second: str) -> float:
    first_luma = sum(weight * _linear(channel) for weight, channel in zip((0.2126, 0.7152, 0.0722), _decode(first), strict=True))
    second_luma = sum(weight * _linear(channel) for weight, channel in zip((0.2126, 0.7152, 0.0722), _decode(second), strict=True))
    high, low = sorted((first_luma, second_luma), reverse=True)
    return (high + 0.05) / (low + 0.05)
