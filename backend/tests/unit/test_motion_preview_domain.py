import pytest

from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.motion_preview import (
    DEFAULT_PREVIEW_SAMPLES,
    MAX_PREVIEW_SAMPLES,
    MIN_PREVIEW_SAMPLES,
    MotionPreviewExcerpt,
    MotionPreviewRequest,
    create_motion_preview_plan,
    parse_motion_preview_request,
    resolve_motion_preview_request,
    validate_excerpt,
)
from wrld_video_studio.domain.video_effects import VideoEffects
from wrld_video_studio.domain.video_export import ExportTarget
from wrld_video_studio.domain.video_export_v2 import parse_motion_manifest


def _manifest():
    effects = VideoEffects()
    return parse_motion_manifest(
        {
            "format": "wrld-video-album/2.0",
            "album": {"id": "a1", "title": "A", "artist": "B", "channel": "C"},
            "visual": {"background": "background.png"},
            "tracks": [
                {"id": "t1", "number": 1, "title": "One", "audio": "one.wav"},
                {"id": "t2", "number": 2, "title": "Two", "audio": "two.wav"},
            ],
            "render": {"profile_id": "youtube-1080p30-motion-v1", "effects": effects.to_dict()},
        }
    )


def test_default_and_endpoint_excerpt_contracts_round_trip():
    assert MotionPreviewExcerpt().sample_count == DEFAULT_PREVIEW_SAMPLES
    for count in (MIN_PREVIEW_SAMPLES, DEFAULT_PREVIEW_SAMPLES, MAX_PREVIEW_SAMPLES):
        request = MotionPreviewRequest(ExportTarget("album"), VideoEffects(), MotionPreviewExcerpt(7, count))
        assert parse_motion_preview_request(request.to_dict()) == request


@pytest.mark.parametrize(
    "start,count",
    [(-1, 240000), (0, 143999), (0, 720001), (True, 240000), (0, 240000.0)],
)
def test_invalid_excerpt_values_are_rejected(start, count):
    with pytest.raises(ValueError):
        MotionPreviewExcerpt(start, count)


def test_manifest_resolution_freezes_effects_and_target_tracks():
    manifest = _manifest()
    request = resolve_motion_preview_request(
        manifest, ExportTarget("track", "t2"), MotionPreviewExcerpt(10, MIN_PREVIEW_SAMPLES)
    )
    plan = create_motion_preview_plan(manifest, request)
    assert [track.id for track in plan.selected_tracks] == ["t2"]
    assert plan.request.effects == manifest.effects


def test_excerpt_must_fit_exact_normalized_timeline():
    validate_excerpt(MotionPreviewExcerpt(1, MIN_PREVIEW_SAMPLES), MIN_PREVIEW_SAMPLES + 1)
    with pytest.raises(MediaInfrastructureError) as caught:
        validate_excerpt(MotionPreviewExcerpt(2, MIN_PREVIEW_SAMPLES), MIN_PREVIEW_SAMPLES + 1)
    assert caught.value.code == "PREVIEW_RANGE_INVALID"
