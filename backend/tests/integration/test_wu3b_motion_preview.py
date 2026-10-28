import json
import os
from array import array
from pathlib import Path

import pytest

from wrld_video_studio.application.motion_preview import MotionPreviews
from wrld_video_studio.application.render_coordination import ProcessLocalRenderAdmission
from wrld_video_studio.domain.motion_preview import MotionPreviewExcerpt, resolve_motion_preview_request
from wrld_video_studio.domain.video_effects import (
    AudioBarsSettings,
    PanZoomSettings,
    TrackProgressSettings,
    VideoEffects,
)
from wrld_video_studio.domain.video_export import ExportTarget
from wrld_video_studio.infrastructure.artifact_verifier import FFmpegArtifactVerifier
from wrld_video_studio.infrastructure.ffprobe_adapter import FFprobeAdapter
from wrld_video_studio.infrastructure.media_tools import MediaToolchain
from wrld_video_studio.infrastructure.process_runner import SubprocessRunner
from wrld_video_studio.infrastructure.project_sources import FilesystemVideoProjectLoader
from wrld_video_studio.infrastructure.video_export_renderer import StaticVideoExportRenderer


@pytest.mark.integration_ffmpeg
def test_real_ffmpeg_motion_preview_crosses_boundary_and_is_lease_owned(tmp_path, schema_dir):
    runner = SubprocessRunner()
    configured = {}
    if os.environ.get("WRLD_FFMPEG_PATH") and os.environ.get("WRLD_FFPROBE_PATH"):
        configured = {
            "ffmpeg": Path(os.environ["WRLD_FFMPEG_PATH"]),
            "ffprobe": Path(os.environ["WRLD_FFPROBE_PATH"]),
        }
    tools = MediaToolchain(runner, configured)
    try:
        ffmpeg = tools.resolve("ffmpeg")
        tools.resolve("ffprobe")
    except Exception as error:
        pytest.skip(f"FFmpeg integration tools unavailable: {error}")
    project = tmp_path / "external" / "Album"
    project.mkdir(parents=True)
    commands = (
        [
            str(ffmpeg.path), "-v", "error", "-f", "lavfi", "-i",
            "color=c=0x203050:s=640x360,drawbox=x=80:y=60:w=120:h=90:c=0x20c060:t=fill",
            "-frames:v", "1", "-y", str(project / "background.png"),
        ],
        [
            str(ffmpeg.path), "-v", "error", "-f", "lavfi", "-i",
            "anullsrc=r=48000:cl=stereo:d=3", "-c:a", "pcm_s16le", "-y",
            str(project / "silence.wav"),
        ],
        [
            str(ffmpeg.path), "-v", "error", "-f", "lavfi", "-i",
            "sine=frequency=660:sample_rate=48000:duration=3", "-filter:a", "volume=0.8",
            "-ac", "2", "-c:a", "pcm_s16le", "-y", str(project / "tone.wav"),
        ],
    )
    for command in commands:
        result = runner.run(command, timeout_seconds=30)
        assert result.returncode == 0 and not result.timed_out
    effects = VideoEffects(
        pan_zoom=PanZoomSettings(
            enabled=True, max_zoom=1.05, cycle_seconds=15, return_to_origin=True
        ),
        audio_bars=AudioBarsSettings(
            enabled=True,
            bar_count=8,
            opacity=1,
            rms_window_samples=480,
            attack_ms=0,
            release_ms=0,
        ),
        track_progress=TrackProgressSettings(
            enabled=True, placement="top", opacity=1, thickness_px=8
        ),
    )
    manifest = {
        "format": "wrld-video-album/2.0",
        "album": {"id": "preview", "title": "Preview", "artist": "Test", "channel": "Test"},
        "visual": {"background": "background.png"},
        "tracks": [
            {"id": "silent", "number": 1, "title": "Silence", "audio": "silence.wav"},
            {"id": "tone", "number": 2, "title": "Tone", "audio": "tone.wav"},
        ],
        "render": {"profile_id": "youtube-1080p30-motion-v1", "effects": effects.to_dict()},
    }
    (project / "video_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    prober = FFprobeAdapter(tools, runner)
    loader = FilesystemVideoProjectLoader(
        (schema_dir / "video-manifest-v1.schema.json", schema_dir / "video-manifest-v2.schema.json"),
        prober=prober,
    )
    loaded = loader.load(project)
    request = resolve_motion_preview_request(
        loaded.manifest,
        ExportTarget("album"),
        MotionPreviewExcerpt(96_000, 144_000),
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
    assert output.is_file()
    probe = prober.probe(output)
    video = next(item for item in probe.streams if item.codec_type == "video")
    audio = next(item for item in probe.streams if item.codec_type == "audio")
    assert (video.width, video.height, video.frame_rate, video.pixel_format) == (
        1920, 1080, 30.0, "yuv420p"
    )
    assert (video.color_space, video.color_transfer, video.color_primaries) == (
        "bt709", "bt709", "bt709"
    )
    assert (audio.codec_name, audio.sample_rate, audio.channels) == ("aac", 48000, 2)
    assert probe.duration_seconds == pytest.approx(3.0, abs=0.1)
    decoded = runner.run(
        [str(ffmpeg.path), "-v", "error", "-xerror", "-i", str(output), "-f", "null", "-"],
        timeout_seconds=60,
    )
    assert decoded.returncode == 0 and not decoded.timed_out
    decoded_audio = tmp_path / "preview-audio.pcm"
    audio_decode = runner.run(
        [
            str(ffmpeg.path), "-v", "error", "-xerror", "-i", str(output),
            "-map", "0:a:0", "-ac", "1", "-ar", "48000", "-f", "s16le", "-y",
            str(decoded_audio),
        ],
        timeout_seconds=60,
    )
    assert audio_decode.returncode == 0 and not audio_decode.timed_out
    samples = array("h")
    samples.frombytes(decoded_audio.read_bytes())
    assert max(abs(value) for value in samples[4_800:38_400]) < 50
    tone = samples[72_000:120_000]
    crossings = sum(left <= 0 < right for left, right in zip(tone, tone[1:]))
    assert crossings / (len(tone) / 48_000) == pytest.approx(660, abs=12)
    frames = {}
    for name, timestamp in (
        ("silence", "0.500000"),
        ("before_boundary", "0.966667"),
        ("after_boundary", "1.033333"),
        ("tone", "1.500000"),
    ):
        raw = tmp_path / f"preview-{name}.rgb"
        frame_decode = runner.run(
            [
                str(ffmpeg.path), "-v", "error", "-i", str(output), "-ss", timestamp,
                "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-y", str(raw),
            ],
            timeout_seconds=60,
        )
        assert frame_decode.returncode == 0 and not frame_decode.timed_out
        frames[name] = raw.read_bytes()
    assert _white_region_height(frames["silence"], 1920, 1080, 800, 1016) <= 4
    assert _white_region_height(frames["tone"], 1920, 1080, 800, 1016) >= 80
    assert _white_row_width(frames["before_boundary"], 1920, 64, 71) > 1600
    assert _white_row_width(frames["after_boundary"], 1920, 64, 71) < 100
    assert not (project / "output").exists()
    lease.close()
    assert not output.exists()
    assert not list((tmp_path / "private-previews").iterdir())
    service.close()


def _white_region_height(frame, width, height, y_start, y_end):
    ys = set()
    for y in range(y_start, min(height, y_end)):
        for x in range(width):
            offset = (y * width + x) * 3
            red, green, blue = frame[offset : offset + 3]
            if red > 220 and green > 220 and blue > 220:
                ys.add(y)
    return 0 if not ys else max(ys) - min(ys) + 1


def _white_row_width(frame, width, y_start, y_end):
    xs = set()
    for y in range(y_start, y_end + 1):
        for x in range(width):
            offset = (y * width + x) * 3
            red, green, blue = frame[offset : offset + 3]
            if red > 220 and green > 220 and blue > 220:
                xs.add(x)
    return 0 if not xs else max(xs) - min(xs) + 1
