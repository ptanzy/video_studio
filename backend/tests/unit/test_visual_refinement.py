from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest

from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.motion_preview import MotionPreviewExcerpt
from wrld_video_studio.domain.motion_preview_v2 import (
    create_refined_motion_preview_plan,
    parse_refined_motion_preview_request,
    resolve_refined_motion_preview_request,
)
from wrld_video_studio.domain.video_effects_v2 import VideoEffectsV2
from wrld_video_studio.domain.video_export import ExportTarget
from wrld_video_studio.domain.video_export_v3 import (
    REFINED_PROFILE_ID,
    RefinedVideoExportRequest,
    create_refined_plan,
    parse_refined_export_request,
    parse_refined_export_result,
    parse_refined_manifest,
    resolve_refined_export_request,
)
from wrld_video_studio.domain.visual_refinement import (
    derive_glow_color,
    derive_rail_color,
    organic_multiplier,
    refined_bar_heights,
    refined_bar_layout,
)


FIXTURES = Path(__file__).parents[1] / "contracts" / "fixtures"


def _json(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_documented_color_vectors_and_glow_derivation_are_exact():
    expected = {
        "#FFFFFF": "#AAAAAA",
        "#000000": "#CBCBCB",
        "#FFFF00": "#AAAA00",
        "#0000FF": "#CBCBFF",
        "#FF69B4": "#FFD4E5",
        "#800080": "#D8CBD8",
    }
    assert {color: derive_rail_color(color, 0.60) for color in expected} == expected
    assert derive_glow_color("#FF69B4") == "#FFA1CA"


def test_effects_v2_defaults_are_fully_materialized():
    effects = VideoEffectsV2().to_dict()
    assert effects["pan_zoom"] == {
        "enabled": False,
        "max_zoom": 1.04,
        "path": "diagonal_down_right",
        "cycle_seconds": 180.0,
        "return_to_origin": True,
        "return_duration_seconds": 5.0,
        "easing": "smoothstep",
    }
    assert effects["audio_bars"] == {
        "enabled": False,
        "variation_mode": "organic_rms",
        "bar_count": 24,
        "color": "#FFFFFF",
        "opacity": 0.65,
        "placement": "bottom_center",
        "zone_width_px": 640,
        "zone_height_px": 180,
        "gap_px": 4,
        "horizontal_offset_px": 0,
        "bottom_margin_px": 64,
        "rms_window_samples": 1920,
        "attack_ms": 60.0,
        "release_ms": 240.0,
        "glow": {"enabled": True, "intensity": 0.35},
    }
    assert effects["track_progress"] == {
        "enabled": False,
        "style": "line",
        "placement": "bottom",
        "color": "#FFFFFF",
        "fill_opacity": 0.8,
        "rail_color": None,
        "rail_contrast_strength": 0.6,
        "rail_opacity": 0.35,
        "thickness_px": 6,
        "segment_count": 20,
    }


def test_organic_formula_has_stable_vectors_and_pixel_quantization():
    assert [organic_multiplier(index, 48_000 * 7) for index in range(4)] == pytest.approx(
        [0.905550971658, 0.723950195226, 0.990245217849, 0.755287229393],
        abs=1e-12,
    )
    assert refined_bar_heights(0.5, 4, 180, "organic_rms", 48_000 * 7) == (
        83,
        66,
        90,
        69,
    )
    assert refined_bar_heights(0.0, 24, 180, "organic_rms", 0) == (2,) * 24


def test_safe_geometry_is_deterministic_and_rejects_escape():
    assert refined_bar_layout(24, "bottom_center", 640, 180, 4, 0, 64) == (
        650,
        836,
        22,
        620,
        640,
    )
    with pytest.raises(ValueError):
        refined_bar_layout(64, "bottom_left", 160, 180, 32, 0, 64)
    with pytest.raises(ValueError):
        refined_bar_layout(24, "bottom_left", 640, 180, 4, -1, 64)


def test_effects_v2_normalizes_hex_and_is_immutable():
    document = _json("video-effects-v2-valid.json")
    document["audio_bars"]["color"] = "#ff69b4"
    document["track_progress"]["color"] = "#800080"
    document["track_progress"]["rail_color"] = "#abcdef"
    effects = VideoEffectsV2.from_dict(document)
    assert effects.audio_bars.color == "#FF69B4"
    assert effects.track_progress.color == "#800080"
    assert effects.track_progress.rail_color == "#ABCDEF"
    with pytest.raises(FrozenInstanceError):
        effects.audio_bars.color = "#000000"


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("pan_zoom", "max_zoom"), 1.03),
        (("pan_zoom", "enabled"), False),
        (("pan_zoom", "path"), "vertical"),
        (("pan_zoom", "cycle_seconds"), 181.0),
        (("pan_zoom", "return_to_origin"), False),
        (("pan_zoom", "return_duration_seconds"), 6.0),
        (("audio_bars", "enabled"), False),
        (("audio_bars", "variation_mode"), "symmetrical"),
        (("audio_bars", "bar_count"), 25),
        (("audio_bars", "color"), "#0000FF"),
        (("audio_bars", "opacity"), 0.66),
        (("audio_bars", "placement"), "bottom_left"),
        (("audio_bars", "zone_width_px"), 642),
        (("audio_bars", "zone_height_px"), 181),
        (("audio_bars", "gap_px"), 5),
        (("audio_bars", "horizontal_offset_px"), 1),
        (("audio_bars", "bottom_margin_px"), 65),
        (("audio_bars", "rms_window_samples"), 1921),
        (("audio_bars", "attack_ms"), 61.0),
        (("audio_bars", "release_ms"), 241.0),
        (("audio_bars", "glow", "enabled"), False),
        (("audio_bars", "glow", "intensity"), 0.36),
        (("track_progress", "color"), "#FFFF00"),
        (("track_progress", "enabled"), False),
        (("track_progress", "style"), "segmented"),
        (("track_progress", "placement"), "top"),
        (("track_progress", "fill_opacity"), 0.81),
        (("track_progress", "rail_color"), "#123456"),
        (("track_progress", "rail_contrast_strength"), 0.61),
        (("track_progress", "rail_opacity"), 0.36),
        (("track_progress", "thickness_px"), 7),
        (("track_progress", "segment_count"), 21),
    ],
)
def test_every_refinement_setting_is_fingerprinted(path, replacement):
    original = _json("video-effects-v2-valid.json")
    changed = deepcopy(original)
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    assert VideoEffectsV2.from_dict(original).fingerprint != VideoEffectsV2.from_dict(
        changed
    ).fingerprint


def test_canonical_hex_case_has_one_fingerprint():
    lower = _json("video-effects-v2-valid.json")
    lower["audio_bars"]["color"] = "#ff69b4"
    lower["track_progress"]["color"] = "#ff69b4"
    assert VideoEffectsV2.from_dict(lower).fingerprint == VideoEffectsV2.from_dict(
        _json("video-effects-v2-valid.json")
    ).fingerprint


def test_refined_manifest_request_plan_and_result_round_trip():
    manifest = parse_refined_manifest(_json("video-manifest-v3-valid.json"))
    request = resolve_refined_export_request(manifest, ExportTarget("album"))
    parsed = parse_refined_export_request(request.to_dict())
    plan = create_refined_plan(manifest, parsed)
    assert request == parsed
    assert plan.output_relative_path == (
        f"profiles/{REFINED_PROFILE_ID}/{request.effects.fingerprint}/album/Album One.mp4"
    )
    assert parse_refined_export_result(
        _json("video-export-result-v3-valid.json")
    ).to_dict() == _json("video-export-result-v3-valid.json")


def test_refined_preview_uses_same_resolved_configuration():
    manifest = parse_refined_manifest(_json("video-manifest-v3-valid.json"))
    request = resolve_refined_motion_preview_request(
        manifest, ExportTarget("album"), MotionPreviewExcerpt(0, 144_000)
    )
    parsed = parse_refined_motion_preview_request(request.to_dict())
    plan = create_refined_motion_preview_plan(manifest, parsed)
    assert plan.request.effects == resolve_refined_export_request(
        manifest, ExportTarget("album")
    ).effects
    assert plan.selected_tracks == manifest.tracks


def test_refined_request_must_match_manifest_configuration():
    manifest = parse_refined_manifest(_json("video-manifest-v3-valid.json"))
    with pytest.raises(MediaInfrastructureError) as caught:
        create_refined_plan(
            manifest,
            RefinedVideoExportRequest(ExportTarget("album"), VideoEffectsV2()),
        )
    assert caught.value.code == "INVALID_EXPORT_REQUEST"
