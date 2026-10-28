from __future__ import annotations

from pathlib import Path

import pytest

from wrld_video_studio.domain.artwork_theme import (
    ArtworkThemeContrastError,
    ORDINARY_TEXT_CONTRAST_MINIMUM,
    PRESET_CONSTANTS,
    composited_footer_color,
    contrast_ratio,
    resolve_artwork_theme,
    text_contrast_is_compliant,
)
from wrld_video_studio.domain.player_overlay import (
    DisplayTrackMetadata,
    FontSettings,
    PlayerOverlaySettings,
    ThemeOverrides,
    ThemeSettings,
    TrueTypeFontMetrics,
    fixed_metadata_text,
    format_timeline_time,
    progress_fraction,
    resolve_player_layout,
    track_metadata_text,
)
from wrld_video_studio.domain.video_effects_v3 import VideoEffectsV3
from wrld_video_studio.domain.video_export import TimelineEntry
from wrld_video_studio.infrastructure.video_export_renderer import StaticVideoExportRenderer


def test_subtle_ambient_defaults_and_geometry_are_separated() -> None:
    effects = VideoEffectsV3(player=PlayerOverlaySettings(font=FontSettings("fonts/ui.ttf")))
    bars = effects.audio_bars
    assert (bars.zone_width_px, bars.zone_height_px, bars.bar_count, bars.gap_px) == (900, 110, 32, 8)
    assert (bars.opacity, bars.glow.intensity, bars.bottom_margin_px) == (0.55, 0.25, 242)
    layout = resolve_player_layout(
        footer_height=effects.player.footer.height_px,
        visualizer_width=bars.zone_width_px,
        visualizer_height=bars.zone_height_px,
        visualizer_gap=bars.gap_px,
        glow_enabled=True,
        placement=bars.placement,
        horizontal_offset=bars.horizontal_offset_px,
        bottom_margin=bars.bottom_margin_px,
    )
    assert layout.footer.y - layout.visualizer_glow.bottom == 32
    assert layout.visualizer.to_dict() == {"x": 510, "y": 728, "width": 900, "height": 110}
    assert layout.safe_area.x <= layout.visualizer_glow.x
    assert layout.visualizer_glow.right <= layout.safe_area.right


def test_impossible_player_layout_is_rejected() -> None:
    with pytest.raises(ValueError, match="too close"):
        resolve_player_layout(
            footer_height=110,
            visualizer_width=900,
            visualizer_height=110,
            visualizer_gap=8,
            glow_enabled=True,
            bottom_margin=200,
        )


def test_album_and_track_progress_use_integer_sample_timeline() -> None:
    timeline = (
        TimelineEntry("one", 1, "One", 0, 480_000),
        TimelineEntry("two", 2, "Two", 480_000, 960_000),
    )
    assert progress_fraction(timeline, 720_000, "album") == 0.5
    assert progress_fraction(timeline, 720_000, "track") == 0.25
    assert format_timeline_time(719_999, 1_440_000) == "00:14"
    assert format_timeline_time(480_000 * 360, 480_000 * 361) == "01:00:00"


def test_player_metadata_presentation_uses_values_without_diagnostic_labels() -> None:
    metadata = DisplayTrackMetadata(
        "track-1", "Echoes of Asia", "Moonlight Over Gyeongju",
        "92", "analyzed", "D minor", "intended", "WRLD MUSIC", "WRLD-FI",
    )
    album, channels = fixed_metadata_text(metadata)
    track = track_metadata_text(metadata)
    assert album == "Echoes of Asia"
    assert channels == "WRLD MUSIC   WRLD-FI"
    assert track == "Moonlight Over Gyeongju   92   D minor"
    assert not any(
        label in f"{album} {channels} {track}"
        for label in ("Album:", "Track:", "Parent:", "Genre:", "BPM:", "Key:")
    )
    without_optional = DisplayTrackMetadata(
        "track-1", "Echoes of Asia", "Moonlight Over Gyeongju",
        None, None, None, None, "WRLD MUSIC", "WRLD-FI",
    )
    assert track_metadata_text(without_optional) == "Moonlight Over Gyeongju"


def test_theme_modes_presets_and_provenance_are_deterministic() -> None:
    pixels = [(30, 70, 120)] * 12 + [(240, 200, 40)] * 3
    settings = ThemeSettings("hybrid", "subtle", ThemeOverrides(footer_background="#101827"))
    first = resolve_artwork_theme(pixels, "a" * 64, settings, footer_opacity=0.65)
    second = resolve_artwork_theme(tuple(reversed(pixels)), "a" * 64, settings, footer_opacity=0.65)
    assert first == second
    assert first.footer_background == "#101827"
    assert first.provenance["footer_background"] == "manual"
    assert first.provenance["visualizer"] == "artwork"
    assert set(PRESET_CONSTANTS) == {"subtle", "balanced", "vibrant"}
    assert contrast_ratio(first.primary_text, first.footer_background) > 1.0


def test_automatic_and_manual_theme_modes_preserve_provenance() -> None:
    pixels = [(20, 80, 140)] * 4
    automatic = resolve_artwork_theme(
        pixels, "a" * 64, ThemeSettings("automatic", "balanced", ThemeOverrides()),
        footer_opacity=0.65,
    )
    manual = resolve_artwork_theme(
        pixels,
        "a" * 64,
        ThemeSettings(
            "manual", "vibrant",
            ThemeOverrides(
                footer_background="#101827", primary_text="#FFFFFF",
                secondary_text="#CCCCCC", progress_fill="#112233",
                progress_rail="#445566", visualizer="#778899",
            ),
        ),
        footer_opacity=0.65,
    )
    assert automatic.mode == "automatic"
    assert all(value != "manual" for value in automatic.provenance.values())
    assert manual.mode == "manual"
    assert set(manual.provenance.values()) == {"manual"}
    assert manual.visualizer == "#778899"


@pytest.mark.parametrize("pixels", [[(250, 250, 250)] * 8, [(5, 5, 5)] * 8])
def test_derived_footer_text_meets_ordinary_wcag_contrast_on_composited_footer(pixels) -> None:
    theme = resolve_artwork_theme(
        pixels,
        "a" * 64,
        ThemeSettings("automatic", "balanced", ThemeOverrides()),
        footer_opacity=0.65,
    )
    background = composited_footer_color(
        theme.dominant_color, theme.footer_background, 0.65
    )
    assert contrast_ratio(theme.primary_text, background) >= ORDINARY_TEXT_CONTRAST_MINIMUM
    assert contrast_ratio(theme.secondary_text, background) >= ORDINARY_TEXT_CONTRAST_MINIMUM
    assert theme.provenance["primary_text"] == "derived"
    assert theme.provenance["secondary_text"] == "derived"


def test_noncompliant_manual_footer_text_is_rejected_without_correction() -> None:
    settings = ThemeSettings(
        "hybrid",
        "balanced",
        ThemeOverrides(footer_background="#FFFFFF", primary_text="#EEEEEE"),
    )
    with pytest.raises(ArtworkThemeContrastError, match="primary_text contrast"):
        resolve_artwork_theme([(255, 255, 255)] * 8, "a" * 64, settings, footer_opacity=0.65)


def test_large_text_uses_the_approved_three_to_one_threshold() -> None:
    assert text_contrast_is_compliant("#949494", "#FFFFFF", large=True)
    assert not text_contrast_is_compliant("#949494", "#FFFFFF", large=False)


def test_metadata_and_announcement_fades_are_deterministic() -> None:
    assert StaticVideoExportRenderer._metadata_alpha(0.0, 10.0, 0, 2) == (
        "(1)*(clip(((10.000000000)-t)/3,0,1))"
    )
    assert StaticVideoExportRenderer._metadata_alpha(10.0, 20.0, 1, 2) == (
        "(clip((t-(10.000000000))/3,0,1))*(1)"
    )
    announcement = StaticVideoExportRenderer._announcement_alpha(10.0, 0.5, 2.0, 0.5)
    assert "clip((t-10.000000000)/0.500000000,0,1)" in announcement
    assert "clip((13.000000000-t)/0.500000000,0,1)" in announcement


def test_every_player_setting_is_strict_and_fingerprinted() -> None:
    value = PlayerOverlaySettings(font=FontSettings("fonts/ui.ttf"))
    roundtrip = PlayerOverlaySettings.from_dict(value.to_dict())
    assert roundtrip == value
    baseline = VideoEffectsV3(player=value).fingerprint
    changed = VideoEffectsV3(player=PlayerOverlaySettings(font=FontSettings("fonts/ui.ttf", metadata_size_px=23))).fingerprint
    assert changed != baseline
    invalid = value.to_dict()
    invalid["unknown"] = True
    with pytest.raises(ValueError):
        PlayerOverlaySettings.from_dict(invalid)


@pytest.mark.skipif(not Path("C:/Windows/Fonts/segoeui.ttf").is_file(), reason="Windows test font unavailable")
def test_true_type_metrics_measure_unicode_and_truncate_deterministically() -> None:
    metrics = TrueTypeFontMetrics(Path("C:/Windows/Fonts/segoeui.ttf").read_bytes())
    assert metrics.width("Echoes of Asia", 22) > 100
    assert metrics.truncate("Echoes of Asia — 月光", 22, 120).endswith("…")
    assert metrics.width(metrics.truncate("Echoes of Asia — 月光", 22, 120), 22) <= 120
    assert metrics.supports("Échos of Asia — Gyeongju")
    assert metrics.missing_codepoints("valid\U0010FFFF") == (0x10FFFF,)
