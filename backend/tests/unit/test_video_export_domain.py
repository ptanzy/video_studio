import pytest

from wrld_video_studio.domain.jobs import InputFingerprint, create_snapshot
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.video_export import (
    ExportTarget,
    VideoExportRequest,
    build_timeline,
    chapters_text,
    create_plan,
    parse_export_request,
    parse_manifest,
    safe_title,
)


def manifest_document():
    return {
        "format": "wrld-video-album/1.0",
        "album": {"id": "album-1", "title": "Album", "artist": "Artist", "channel": "Channel"},
        "visual": {"background": "background.png"},
        "tracks": [
            {"id": "t1", "number": 1, "title": "First", "audio": "first.wav"},
            {"id": "t2", "number": 2, "title": "Second\nLine", "audio": "second.wav"},
        ],
        "render": {"profile_id": "youtube-1080p30-v1"},
    }


def test_album_and_track_plans_have_deterministic_paths():
    manifest = parse_manifest(manifest_document())
    album = create_plan(manifest, VideoExportRequest(ExportTarget("album")))
    track = create_plan(manifest, VideoExportRequest(ExportTarget("track", "t2")))
    assert album.output_relative_path == "album/Album.mp4"
    assert [item.id for item in album.selected_tracks] == ["t1", "t2"]
    assert track.output_relative_path == "tracks/02 - Second_Line.mp4"
    assert [item.id for item in track.selected_tracks] == ["t2"]


def test_sample_timeline_and_chapters_floor_boundaries():
    manifest = parse_manifest(manifest_document())
    timeline = build_timeline(manifest.tracks, (48_001, 96_000))
    assert timeline[1].start_sample == 48_001
    assert timeline[1].display_seconds == 1
    assert chapters_text(timeline) == "00:00 First\n00:01 Second Line\n"


def test_duplicate_identity_and_order_are_rejected():
    value = manifest_document()
    value["tracks"][1]["id"] = "t1"
    with pytest.raises(MediaInfrastructureError) as caught:
        parse_manifest(value)
    assert caught.value.code == "DUPLICATE_TRACK_ID"


@pytest.mark.parametrize("title", ["CON", "...", "   "])
def test_unsafe_output_names_are_rejected(title):
    with pytest.raises(MediaInfrastructureError):
        safe_title(title)


def test_v1_manifest_rejects_effect_configuration():
    value = manifest_document()
    value["render"]["effects"] = {}

    with pytest.raises(MediaInfrastructureError) as caught:
        parse_manifest(value)

    assert caught.value.code == "MANIFEST_INVALID"


def test_v1_request_rejects_effect_configuration():
    value = VideoExportRequest(ExportTarget("album")).to_dict()
    value["effects"] = {}

    with pytest.raises(MediaInfrastructureError) as caught:
        parse_export_request(value)

    assert caught.value.code == "INVALID_EXPORT_REQUEST"


def test_static_request_identity_remains_unchanged():
    manifest = parse_manifest(manifest_document())
    request = VideoExportRequest(ExportTarget("album"))
    snapshot = create_snapshot(
        job_id="job-static-regression",
        attempt_id="attempt-static-regression",
        created_at="2026-10-26T12:00:00Z",
        renderer_version="wu3a-video-export-1",
        request=request.to_dict(),
        inputs=(
            InputFingerprint("video_manifest.json", "a" * 64),
            InputFingerprint("background.png", "b" * 64),
            InputFingerprint("first.wav", "c" * 64),
            InputFingerprint("second.wav", "d" * 64),
        ),
    )

    assert manifest.profile_id == "youtube-1080p30-v1"
    assert snapshot.request_digest == (
        "2219b6921cce4e6d27a1187f0c7e4ebb2a2b19f55d72eb20cc8400f938057f12"
    )
