from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest

from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.video_effects import PanZoomSettings, VideoEffects
from wrld_video_studio.domain.video_export import (
    ExportTarget,
    VideoExportRequest,
    create_plan,
    parse_manifest,
)
from wrld_video_studio.domain.video_export_v2 import (
    MOTION_PROFILE_ID,
    MotionVideoExportRequest,
    create_motion_plan,
    parse_motion_export_result,
    parse_motion_export_request,
    parse_motion_manifest,
    resolve_motion_export_request,
)


FIXTURES = Path(__file__).parents[1] / "contracts" / "fixtures"


def manifest_document():
    base_effects = VideoEffects().to_dict()
    override_effects = deepcopy(base_effects)
    override_effects["pan_zoom"]["enabled"] = True
    return {
        "format": "wrld-video-album/2.0",
        "album": {
            "id": "album-1",
            "title": "Album",
            "artist": "Artist",
            "channel": "Channel",
        },
        "visual": {"background": "art/background.png"},
        "tracks": [
            {"id": "t1", "number": 1, "title": "First", "audio": "audio/first.wav"},
            {"id": "t2", "number": 2, "title": "Second", "audio": "audio/second.wav"},
        ],
        "render": {
            "profile_id": MOTION_PROFILE_ID,
            "effects": base_effects,
            "track_effects": [{"track_id": "t2", "effects": override_effects}],
        },
    }


def test_manifest_resolves_immutable_album_and_track_effects():
    manifest = parse_motion_manifest(manifest_document())

    album_effects = manifest.effects_for(ExportTarget("album"))
    first_effects = manifest.effects_for(ExportTarget("track", "t1"))
    second_effects = manifest.effects_for(ExportTarget("track", "t2"))

    assert album_effects == VideoEffects()
    assert first_effects == album_effects
    assert second_effects.pan_zoom.enabled
    assert second_effects != album_effects
    with pytest.raises(FrozenInstanceError):
        second_effects.pan_zoom.enabled = False


def test_motion_plan_uses_profile_and_effect_fingerprint_namespace():
    manifest = parse_motion_manifest(manifest_document())
    effects = manifest.effects_for(ExportTarget("album"))
    request = MotionVideoExportRequest(ExportTarget("album"), effects)

    plan = create_motion_plan(manifest, request)

    assert plan.effect_config_digest == effects.fingerprint
    assert plan.output_relative_path == (
        f"profiles/{MOTION_PROFILE_ID}/{effects.fingerprint}/album/Album.mp4"
    )
    assert [track.id for track in plan.selected_tracks] == ["t1", "t2"]


def test_track_plan_uses_track_override_namespace():
    manifest = parse_motion_manifest(manifest_document())
    target = ExportTarget("track", "t2")
    effects = manifest.effects_for(target)

    plan = create_motion_plan(manifest, MotionVideoExportRequest(target, effects))

    assert effects.pan_zoom.enabled
    assert plan.output_relative_path == (
        f"profiles/{MOTION_PROFILE_ID}/{effects.fingerprint}/tracks/02 - Second.mp4"
    )


def test_motion_namespace_does_not_change_static_output_paths():
    v2_manifest = parse_motion_manifest(manifest_document())
    effects = v2_manifest.effects_for(ExportTarget("album"))
    motion = create_motion_plan(
        v2_manifest, MotionVideoExportRequest(ExportTarget("album"), effects)
    )
    v1_document = deepcopy(manifest_document())
    v1_document["format"] = "wrld-video-album/1.0"
    v1_document["render"] = {"profile_id": "youtube-1080p30-v1"}
    static = create_plan(
        parse_manifest(v1_document), VideoExportRequest(ExportTarget("album"))
    )

    assert static.output_relative_path == "album/Album.mp4"
    assert motion.output_relative_path != static.output_relative_path


def test_request_round_trip_and_manifest_consistency():
    manifest = parse_motion_manifest(manifest_document())
    target = ExportTarget("track", "t1")
    request = resolve_motion_export_request(manifest, target)

    parsed = parse_motion_export_request(request.to_dict())
    plan = create_motion_plan(manifest, parsed)

    assert parsed == request
    assert plan.request.effects == manifest.effects_for(target)


def test_manifest_override_is_frozen_into_the_resolved_track_request():
    manifest = parse_motion_manifest(manifest_document())

    request = resolve_motion_export_request(manifest, ExportTarget("track", "t2"))

    assert request.effects.pan_zoom.enabled
    assert request.to_dict()["effects"] == manifest.track_effects[0].effects.to_dict()


def test_request_effects_must_match_resolved_manifest_configuration():
    manifest = parse_motion_manifest(manifest_document())
    mismatched = VideoEffects(pan_zoom=PanZoomSettings(enabled=True))

    with pytest.raises(MediaInfrastructureError) as caught:
        create_motion_plan(
            manifest,
            MotionVideoExportRequest(ExportTarget("album"), mismatched),
        )

    assert caught.value.code == "INVALID_EXPORT_REQUEST"


def test_result_fixture_round_trips_through_the_strict_domain_model():
    document = json.loads(
        (FIXTURES / "video-export-result-v2-valid.json").read_text(encoding="utf-8")
    )

    result = parse_motion_export_result(document)

    assert result.profile_id == MOTION_PROFILE_ID
    assert result.effects == VideoEffects()
    assert result.to_dict() == document


def test_result_domain_rejects_unknown_fields_and_unverified_artifacts():
    document = json.loads(
        (FIXTURES / "video-export-result-v2-valid.json").read_text(encoding="utf-8")
    )
    document["artifacts"][0]["verification"] = "unchecked"

    with pytest.raises(MediaInfrastructureError) as caught:
        parse_motion_export_result(document)

    assert caught.value.code == "OUTPUT_INVALID"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["render"].update({"unknown": True}),
        lambda value: value["render"].update({"profile_id": "youtube-1080p30-v1"}),
        lambda value: value.update({"format": "wrld-video-album/3.0"}),
        lambda value: value["render"]["track_effects"].append(
            deepcopy(value["render"]["track_effects"][0])
        ),
        lambda value: value["render"]["track_effects"][0].update({"track_id": "missing"}),
    ],
)
def test_invalid_or_unsupported_manifests_are_rejected(mutation):
    document = manifest_document()
    mutation(document)

    with pytest.raises(MediaInfrastructureError):
        parse_motion_manifest(document)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"unknown": True}),
        lambda value: value.update({"contract_version": "video-export-request/1.0"}),
        lambda value: value.update({"profile_id": "youtube-1080p30-v1"}),
        lambda value: value["target"].update({"track_id": "not-allowed"}),
        lambda value: value["effects"]["pan_zoom"].update({"max_zoom": 1.051}),
    ],
)
def test_invalid_or_unsupported_requests_are_rejected(mutation):
    request = MotionVideoExportRequest(ExportTarget("album"), VideoEffects()).to_dict()
    mutation(request)

    with pytest.raises(MediaInfrastructureError) as caught:
        parse_motion_export_request(request)

    assert caught.value.code == "INVALID_EXPORT_REQUEST"

