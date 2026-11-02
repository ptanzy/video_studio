import argparse
import json
import os
from pathlib import Path

import pytest

from wrld_video_studio.application.motion_preview import MotionPreviews
from wrld_video_studio.application.render_coordination import ProcessLocalRenderAdmission
from wrld_video_studio.domain.motion_preview import MotionPreviewExcerpt
from wrld_video_studio.domain.motion_preview_v2 import resolve_refined_motion_preview_request
from wrld_video_studio.domain.video_effects import PanZoomSettings
from wrld_video_studio.domain.video_effects_v2 import (
    AudioBarsSettingsV2,
    TrackProgressSettingsV2,
    VideoEffectsV2,
)
from wrld_video_studio.domain.video_export import ExportTarget
from wrld_video_studio.infrastructure.artifact_verifier import FFmpegArtifactVerifier
from wrld_video_studio.infrastructure.ffprobe_adapter import FFprobeAdapter
from wrld_video_studio.infrastructure.media_tools import MediaToolchain
from wrld_video_studio.infrastructure.process_runner import SubprocessRunner
from wrld_video_studio.infrastructure.project_sources import FilesystemVideoProjectLoader
from wrld_video_studio.infrastructure.video_export_renderer import StaticVideoExportRenderer
from wrld_video_studio.interfaces.cli.video_export import run_video_export


def _configured_tools():
    if not os.environ.get("WRLD_FFMPEG_PATH") or not os.environ.get("WRLD_FFPROBE_PATH"):
        pytest.skip("WRLD_FFMPEG_PATH and WRLD_FFPROBE_PATH are required")
    runner = SubprocessRunner()
    tools = MediaToolchain(
        runner,
        {
            "ffmpeg": Path(os.environ["WRLD_FFMPEG_PATH"]),
            "ffprobe": Path(os.environ["WRLD_FFPROBE_PATH"]),
        },
    )
    tools.resolve("ffmpeg")
    tools.resolve("ffprobe")
    return runner, tools


def _project(tmp_path, runner, tools, *, effects=None, name="synthetic-refined-album"):
    project = tmp_path / name
    project.mkdir()
    ffmpeg = tools.resolve("ffmpeg").path
    commands = (
        [
            str(ffmpeg), "-v", "error", "-f", "lavfi", "-i",
            "color=c=0x203050:s=640x360,drawbox=x=80:y=60:w=120:h=90:c=0x20c060:t=fill",
            "-frames:v", "1", "-y", str(project / "background.png"),
        ],
        [
            str(ffmpeg), "-v", "error", "-f", "lavfi", "-i",
            "sine=frequency=660:sample_rate=48000:duration=3", "-filter:a", "volume=0.8",
            "-ac", "2", "-c:a", "pcm_s16le", "-y", str(project / "tone.wav"),
        ],
    )
    for command in commands:
        result = runner.run(command, timeout_seconds=30)
        assert result.returncode == 0 and not result.timed_out
    effects = effects or VideoEffectsV2(
            pan_zoom=PanZoomSettings(
                enabled=True,
                max_zoom=1.04,
                cycle_seconds=15,
                return_to_origin=True,
                return_duration_seconds=0.5,
            ),
            audio_bars=AudioBarsSettingsV2(
                enabled=True,
                color="#FF69B4",
                bar_count=24,
                rms_window_samples=480,
                attack_ms=0,
                release_ms=0,
            ),
            track_progress=TrackProgressSettingsV2(
                enabled=True,
                color="#800080",
                fill_opacity=0.8,
                rail_opacity=0.35,
            ),
        )
    manifest = {
        "format": "wrld-video-album/3.0",
        "album": {"id": "refined", "title": "Refined", "artist": "Test", "channel": "Test"},
        "visual": {"background": "background.png"},
        "tracks": [{"id": "tone", "number": 1, "title": "Tone", "audio": "tone.wav"}],
        "render": {
            "profile_id": "youtube-1080p30-motion-v2",
            "effects": effects.to_dict(),
        },
    }
    (project / "video_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return project, effects


def _assert_verified_media(path, runner, tools, *, expect_effects=True):
    probe = FFprobeAdapter(tools, runner).probe(path)
    video = next(stream for stream in probe.streams if stream.codec_type == "video")
    audio = next(stream for stream in probe.streams if stream.codec_type == "audio")
    assert (video.width, video.height, video.frame_rate, video.pixel_format) == (
        1920,
        1080,
        30.0,
        "yuv420p",
    )
    assert (video.codec_name, video.color_space, video.color_transfer, video.color_primaries) == (
        "h264",
        "bt709",
        "bt709",
        "bt709",
    )
    assert (audio.codec_name, audio.sample_rate, audio.channels) == ("aac", 48000, 2)
    assert probe.duration_seconds == pytest.approx(3.0, abs=0.1)
    decoded = runner.run(
        [str(tools.resolve("ffmpeg").path), "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
        timeout_seconds=120,
    )
    assert decoded.returncode == 0 and not decoded.timed_out
    frame = path.with_suffix(".inspection.rgb")
    extracted = runner.run(
        [
            str(tools.resolve("ffmpeg").path), "-v", "error", "-i", str(path),
            "-ss", "1.500000", "-frames:v", "1", "-f", "rawvideo",
            "-pix_fmt", "rgb24", "-y", str(frame),
        ],
        timeout_seconds=120,
    )
    assert extracted.returncode == 0 and not extracted.timed_out
    pixels = frame.read_bytes()
    frame.unlink()
    pink = 0
    for y in range(800, 1010):
        for x in range(600, 1320):
            offset = (y * 1920 + x) * 3
            red, green, blue = pixels[offset : offset + 3]
            if red > 140 and red > green * 1.25 and blue > green * 1.15:
                pink += 1
    if expect_effects:
        assert pink > 1_000
    else:
        assert pink < 50
    filled = _average_region(pixels, 1920, 300, 500, 1010, 1016)
    rail = _average_region(pixels, 1920, 1400, 1600, 1010, 1016)
    difference = sum(abs(left - right) for left, right in zip(filled, rail))
    if expect_effects:
        assert difference > 20
    else:
        assert difference < 5


def _average_region(pixels, width, x_start, x_end, y_start, y_end):
    totals = [0, 0, 0]
    count = 0
    for y in range(y_start, y_end):
        for x in range(x_start, x_end):
            offset = (y * width + x) * 3
            for index, value in enumerate(pixels[offset : offset + 3]):
                totals[index] += value
            count += 1
    return tuple(value / count for value in totals)


@pytest.mark.integration_ffmpeg
def test_real_ffmpeg_refined_track_export_decodes(tmp_path):
    runner, tools = _configured_tools()
    project, effects = _project(tmp_path, runner, tools)
    code = run_video_export(
        argparse.Namespace(
            album_project=str(project),
            target="track",
            track_id="tone",
            profile="youtube-1080p30-motion-v2",
            ffmpeg_path=str(tools.resolve("ffmpeg").path),
            ffprobe_path=str(tools.resolve("ffprobe").path),
        ),
        state_root=tmp_path / "state",
    )
    assert code == 0
    output = (
        project
        / "output"
        / "profiles"
        / "youtube-1080p30-motion-v2"
        / effects.fingerprint
        / "tracks"
        / "01 - Tone.mp4"
    )
    _assert_verified_media(output, runner, tools)


@pytest.mark.integration_ffmpeg
def test_real_ffmpeg_refined_effect_off_track_is_static_and_decodes(tmp_path):
    runner, tools = _configured_tools()
    project, effects = _project(
        tmp_path,
        runner,
        tools,
        effects=VideoEffectsV2(),
        name="synthetic-refined-static-album",
    )
    code = run_video_export(
        argparse.Namespace(
            album_project=str(project),
            target="track",
            track_id="tone",
            profile="youtube-1080p30-motion-v2",
            ffmpeg_path=str(tools.resolve("ffmpeg").path),
            ffprobe_path=str(tools.resolve("ffprobe").path),
        ),
        state_root=tmp_path / "state",
    )
    assert code == 0
    output = (
        project
        / "output"
        / "profiles"
        / "youtube-1080p30-motion-v2"
        / effects.fingerprint
        / "tracks"
        / "01 - Tone.mp4"
    )
    _assert_verified_media(output, runner, tools, expect_effects=False)


@pytest.mark.integration_ffmpeg
def test_real_ffmpeg_refined_preview_decodes_and_releases(tmp_path, schema_dir):
    runner, tools = _configured_tools()
    project, _effects = _project(tmp_path, runner, tools)
    prober = FFprobeAdapter(tools, runner)
    loader = FilesystemVideoProjectLoader(
        (
            schema_dir / "video-manifest-v1.schema.json",
            schema_dir / "video-manifest-v2.schema.json",
            schema_dir / "video-manifest-v3.schema.json",
        ),
        prober=prober,
    )
    loaded = loader.load(project)
    request = resolve_refined_motion_preview_request(
        loaded.manifest,
        ExportTarget("track", "tone"),
        MotionPreviewExcerpt(0, 144_000),
    )
    service = MotionPreviews(
        loader,
        StaticVideoExportRenderer(tools, runner),
        FFmpegArtifactVerifier(prober, tools, runner),
        ProcessLocalRenderAdmission(),
        tmp_path / "private-previews",
    )
    lease = service.prepare(project, request)
    output = lease.path
    _assert_verified_media(output, runner, tools)
    lease.close()
    assert not output.exists()
    assert not list((tmp_path / "private-previews").iterdir())
    service.close()
