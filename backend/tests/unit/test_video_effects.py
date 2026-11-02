from dataclasses import replace

import pytest

from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.video_effects import (
    AudioBarsSettings,
    PanZoomSettings,
    TrackProgressSettings,
    VideoEffects,
    parse_video_effects,
)


def test_defaults_match_the_approved_contract():
    effects = VideoEffects()

    assert effects.to_dict() == {
        "pan_zoom": {
            "enabled": False,
            "max_zoom": 1.04,
            "path": "diagonal_down_right",
            "cycle_seconds": 180.0,
            "return_to_origin": True,
            "return_duration_seconds": 5.0,
            "easing": "smoothstep",
        },
        "audio_bars": {
            "enabled": False,
            "bar_count": 24,
            "opacity": 0.65,
            "placement": "bottom_center",
            "rms_window_samples": 1920,
            "attack_ms": 60.0,
            "release_ms": 240.0,
        },
        "track_progress": {
            "enabled": False,
            "style": "line",
            "placement": "bottom",
            "opacity": 0.8,
            "thickness_px": 6,
            "segment_count": 20,
        },
    }


@pytest.mark.parametrize("effect_name", ["pan_zoom", "audio_bars", "track_progress"])
def test_each_effect_can_be_enabled_independently(effect_name):
    defaults = VideoEffects()
    values = {
        "pan_zoom": replace(defaults.pan_zoom, enabled=effect_name == "pan_zoom"),
        "audio_bars": replace(defaults.audio_bars, enabled=effect_name == "audio_bars"),
        "track_progress": replace(
            defaults.track_progress, enabled=effect_name == "track_progress"
        ),
    }

    effects = VideoEffects(**values)

    assert effects.pan_zoom.enabled is (effect_name == "pan_zoom")
    assert effects.audio_bars.enabled is (effect_name == "audio_bars")
    assert effects.track_progress.enabled is (effect_name == "track_progress")


def test_all_effects_can_be_enabled_together():
    effects = VideoEffects(
        pan_zoom=PanZoomSettings(enabled=True),
        audio_bars=AudioBarsSettings(enabled=True),
        track_progress=TrackProgressSettings(enabled=True),
    )

    assert effects.pan_zoom.enabled
    assert effects.audio_bars.enabled
    assert effects.track_progress.enabled


@pytest.mark.parametrize(
    ("factory", "keyword", "value"),
    [
        (PanZoomSettings, "enabled", 1),
        (PanZoomSettings, "max_zoom", 0.999),
        (PanZoomSettings, "max_zoom", 1.051),
        (PanZoomSettings, "max_zoom", float("nan")),
        (PanZoomSettings, "path", "orbit"),
        (PanZoomSettings, "cycle_seconds", 14.999),
        (PanZoomSettings, "cycle_seconds", 600.001),
        (PanZoomSettings, "return_to_origin", "true"),
        (PanZoomSettings, "return_duration_seconds", 0.499),
        (PanZoomSettings, "return_duration_seconds", 30.001),
        (PanZoomSettings, "easing", "linear"),
        (AudioBarsSettings, "enabled", 0),
        (AudioBarsSettings, "bar_count", 7),
        (AudioBarsSettings, "bar_count", 65),
        (AudioBarsSettings, "bar_count", 24.0),
        (AudioBarsSettings, "opacity", 0.099),
        (AudioBarsSettings, "opacity", 1.001),
        (AudioBarsSettings, "placement", "center"),
        (AudioBarsSettings, "rms_window_samples", 479),
        (AudioBarsSettings, "rms_window_samples", 4801),
        (AudioBarsSettings, "attack_ms", -0.001),
        (AudioBarsSettings, "attack_ms", 500.001),
        (AudioBarsSettings, "release_ms", -0.001),
        (AudioBarsSettings, "release_ms", 1000.001),
        (TrackProgressSettings, "enabled", None),
        (TrackProgressSettings, "style", "dots"),
        (TrackProgressSettings, "placement", "left"),
        (TrackProgressSettings, "opacity", 0.099),
        (TrackProgressSettings, "opacity", 1.001),
        (TrackProgressSettings, "thickness_px", 1),
        (TrackProgressSettings, "thickness_px", 17),
        (TrackProgressSettings, "segment_count", 4),
        (TrackProgressSettings, "segment_count", 61),
    ],
)
def test_invalid_types_modes_and_boundaries_are_rejected(factory, keyword, value):
    with pytest.raises(ValueError):
        factory(**{keyword: value})


def test_inclusive_parameter_boundaries_are_accepted():
    for max_zoom in (1.0, 1.05):
        for cycle_seconds in (15, 600):
            for return_seconds in (0.5, 30):
                PanZoomSettings(
                    max_zoom=max_zoom,
                    cycle_seconds=cycle_seconds,
                    return_duration_seconds=return_seconds,
                )
    for bar_count in (8, 64):
        for opacity in (0.1, 1):
            for window in (480, 4800):
                AudioBarsSettings(
                    bar_count=bar_count,
                    opacity=opacity,
                    rms_window_samples=window,
                    attack_ms=0,
                    release_ms=1000,
                )
    for opacity in (0.1, 1):
        for thickness in (2, 16):
            for segments in (5, 60):
                TrackProgressSettings(
                    opacity=opacity,
                    thickness_px=thickness,
                    segment_count=segments,
                )


@pytest.mark.parametrize(
    ("factory", "keyword", "allowed"),
    [
        (
            PanZoomSettings,
            "path",
            ("center", "horizontal", "vertical", "diagonal_down_right", "diagonal_up_right"),
        ),
        (
            AudioBarsSettings,
            "placement",
            ("bottom_left", "bottom_center", "bottom_right"),
        ),
        (TrackProgressSettings, "style", ("line", "segmented")),
        (TrackProgressSettings, "placement", ("top", "bottom")),
    ],
)
def test_every_approved_enum_value_is_accepted(factory, keyword, allowed):
    for value in allowed:
        factory(**{keyword: value})


def test_canonical_form_is_independent_of_key_order_and_numeric_spelling():
    original = VideoEffects().to_dict()
    reordered = {
        "track_progress": dict(reversed(list(original["track_progress"].items()))),
        "audio_bars": dict(reversed(list(original["audio_bars"].items()))),
        "pan_zoom": dict(reversed(list(original["pan_zoom"].items()))),
    }
    reordered["pan_zoom"]["cycle_seconds"] = 180

    left = VideoEffects.from_dict(original)
    right = VideoEffects.from_dict(reordered)

    assert left == right
    assert left.canonical_json() == right.canonical_json()
    assert left.fingerprint == right.fingerprint
    assert left.fingerprint == (
        "4fded9a0cb6718caa0bdc9a4a81fdb17c777c26e69faf4102230dce976c9b436"
    )


def test_every_configurable_output_parameter_changes_the_fingerprint():
    baseline = VideoEffects()
    variants = [
        replace(baseline, pan_zoom=replace(baseline.pan_zoom, enabled=True)),
        replace(baseline, pan_zoom=replace(baseline.pan_zoom, max_zoom=1.05)),
        replace(baseline, pan_zoom=replace(baseline.pan_zoom, path="vertical")),
        replace(baseline, pan_zoom=replace(baseline.pan_zoom, cycle_seconds=181)),
        replace(baseline, pan_zoom=replace(baseline.pan_zoom, return_to_origin=False)),
        replace(
            baseline,
            pan_zoom=replace(baseline.pan_zoom, return_duration_seconds=6),
        ),
        replace(baseline, audio_bars=replace(baseline.audio_bars, enabled=True)),
        replace(baseline, audio_bars=replace(baseline.audio_bars, bar_count=25)),
        replace(baseline, audio_bars=replace(baseline.audio_bars, opacity=0.66)),
        replace(
            baseline,
            audio_bars=replace(baseline.audio_bars, placement="bottom_left"),
        ),
        replace(
            baseline,
            audio_bars=replace(baseline.audio_bars, rms_window_samples=1921),
        ),
        replace(baseline, audio_bars=replace(baseline.audio_bars, attack_ms=61)),
        replace(baseline, audio_bars=replace(baseline.audio_bars, release_ms=241)),
        replace(
            baseline,
            track_progress=replace(baseline.track_progress, enabled=True),
        ),
        replace(
            baseline,
            track_progress=replace(baseline.track_progress, style="segmented"),
        ),
        replace(
            baseline,
            track_progress=replace(baseline.track_progress, placement="top"),
        ),
        replace(
            baseline,
            track_progress=replace(baseline.track_progress, opacity=0.81),
        ),
        replace(
            baseline,
            track_progress=replace(baseline.track_progress, thickness_px=7),
        ),
        replace(
            baseline,
            track_progress=replace(baseline.track_progress, segment_count=21),
        ),
    ]

    assert all(item.fingerprint != baseline.fingerprint for item in variants)
    assert len({item.fingerprint for item in variants}) == len(variants)


def test_unknown_or_missing_effect_fields_are_rejected_with_the_requested_code():
    document = VideoEffects().to_dict()
    document["pan_zoom"]["unexpected"] = True

    with pytest.raises(MediaInfrastructureError) as caught:
        parse_video_effects(document, error_code="MANIFEST_INVALID")

    assert caught.value.code == "MANIFEST_INVALID"

