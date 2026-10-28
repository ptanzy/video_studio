from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import pytest

from wrld_video_studio.domain.player_overlay import FontSettings, PlayerOverlaySettings
from wrld_video_studio.domain.video_effects import PanZoomSettings
from wrld_video_studio.domain.video_effects_v3 import VideoEffectsV3
from wrld_video_studio.infrastructure.ffprobe_adapter import FFprobeAdapter
from wrld_video_studio.infrastructure.media_tools import MediaToolchain
from wrld_video_studio.infrastructure.process_runner import SubprocessRunner
from wrld_video_studio.infrastructure.video_export_renderer import StaticVideoExportRenderer
from wrld_video_studio.interfaces.cli.video_export import run_video_export


def _tools():
    if not os.environ.get("WRLD_FFMPEG_PATH") or not os.environ.get("WRLD_FFPROBE_PATH"):
        pytest.skip("WRLD_FFMPEG_PATH and WRLD_FFPROBE_PATH are required")
    runner = SubprocessRunner()
    tools = MediaToolchain(runner, {"ffmpeg": Path(os.environ["WRLD_FFMPEG_PATH"]), "ffprobe": Path(os.environ["WRLD_FFPROBE_PATH"])})
    tools.resolve("ffmpeg")
    tools.resolve("ffprobe")
    return runner, tools


def _font() -> Path:
    candidates = (
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    pytest.skip("a Unicode TTF acceptance font is unavailable")


def _project(tmp_path: Path, runner: SubprocessRunner, tools: MediaToolchain) -> Path:
    project = tmp_path / "synthetic-player"
    (project / "fonts").mkdir(parents=True)
    shutil.copyfile(_font(), project / "fonts" / "ui.ttf")
    ffmpeg = tools.resolve("ffmpeg").path
    commands = [
        [str(ffmpeg), "-v", "error", "-f", "lavfi", "-i", "color=c=0x1d3557:s=640x360,drawbox=x=80:y=60:w=180:h=120:c=0xd4a017:t=fill", "-frames:v", "1", "-y", str(project / "background.png")],
        [str(ffmpeg), "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3", "-ac", "2", "-c:a", "pcm_s16le", "-y", str(project / "one.wav")],
        [str(ffmpeg), "-v", "error", "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=3", "-ac", "2", "-c:a", "pcm_s16le", "-y", str(project / "two.wav")],
    ]
    for command in commands:
        result = runner.run(command, timeout_seconds=30)
        assert result.returncode == 0 and not result.timed_out
    effects = VideoEffectsV3(
        pan_zoom=PanZoomSettings(enabled=True, cycle_seconds=15, return_duration_seconds=0.5),
        player=PlayerOverlaySettings(font=FontSettings("fonts/ui.ttf")),
    )
    manifest = {
        "format": "wrld-video-album/4.0",
        "album": {"id": "player", "title": "Player Album Échos", "artist": "Test", "parent_channel": "WRLD-FI", "genre_channel": "World Music"},
        "visual": {"background": "background.png"},
        "tracks": [
            {"id": "one", "number": 1, "title": "First Movement", "audio": "one.wav", "music": {"intended": {"bpm": 92, "key": "D minor"}, "analyzed": {"bpm": None, "key": None}}},
            {"id": "two", "number": 2, "title": "Second Movement", "audio": "two.wav", "music": {"intended": {"bpm": None, "key": None}, "analyzed": {"bpm": {"value": 121.5, "confidence": 0.9, "reliable": True}, "key": {"value": "A major", "confidence": 0.4, "reliable": False}}}},
        ],
        "render": {"profile_id": "youtube-1080p30-player-v1", "effects": effects.to_dict()},
    }
    (project / "video_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return project


@pytest.mark.integration_ffmpeg
def test_real_ffmpeg_player_album_renders_decodes_and_has_separated_regions(tmp_path, monkeypatch):
    runner, tools = _tools()
    project = _project(tmp_path, runner, tools)
    rendered_text: list[str] = []
    original_write = StaticVideoExportRenderer._write_text_asset

    def capture_text(path: Path, value: str) -> Path:
        rendered_text.append(value)
        return original_write(path, value)

    monkeypatch.setattr(StaticVideoExportRenderer, "_write_text_asset", staticmethod(capture_text))
    code = run_video_export(
        argparse.Namespace(
            album_project=str(project), target="album", track_id=None,
            profile="youtube-1080p30-player-v1",
            ffmpeg_path=str(tools.resolve("ffmpeg").path), ffprobe_path=str(tools.resolve("ffprobe").path),
        ),
        state_root=tmp_path / "state",
    )
    assert code == 0
    outputs = list((project / "output" / "profiles" / "youtube-1080p30-player-v1").rglob("*.mp4"))
    assert len(outputs) == 1
    output = outputs[0]
    probe = FFprobeAdapter(tools, runner).probe(output)
    video = next(stream for stream in probe.streams if stream.codec_type == "video")
    audio = next(stream for stream in probe.streams if stream.codec_type == "audio")
    assert (video.codec_name, video.width, video.height, video.frame_rate, video.pixel_format) == ("h264", 1920, 1080, 30.0, "yuv420p")
    assert (video.color_space, video.color_transfer, video.color_primaries) == ("bt709", "bt709", "bt709")
    assert (audio.codec_name, audio.sample_rate, audio.channels) == ("aac", 48000, 2)
    assert probe.duration_seconds == pytest.approx(6.0, abs=0.1)
    assert "Player Album Échos" in rendered_text
    assert "WRLD-FI   World Music" in rendered_text
    assert "First Movement   92   D minor" in rendered_text
    assert not any(
        label in value
        for value in rendered_text
        for label in ("Album:", "Track:", "Parent:", "Genre:", "BPM:", "Key:")
    )
    decoded = runner.run([str(tools.resolve("ffmpeg").path), "-v", "error", "-xerror", "-i", str(output), "-f", "null", "-"], timeout_seconds=120)
    assert decoded.returncode == 0 and not decoded.timed_out

    def crop(name: str, geometry: str) -> bytes:
        destination = tmp_path / f"{name}.rgb"
        extracted = runner.run(
            [
                str(tools.resolve("ffmpeg").path), "-v", "error", "-ss", "1.5", "-i", str(output),
                "-vf", f"crop={geometry}", "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo",
                "-y", str(destination),
            ],
            timeout_seconds=60,
        )
        assert extracted.returncode == 0 and not extracted.timed_out
        return destination.read_bytes()

    def colors(pixels: bytes) -> set[bytes]:
        return {pixels[index:index + 3] for index in range(0, len(pixels), 3)}

    visualizer = colors(crop("visualizer", "900:110:510:728"))
    reserved_gap = colors(crop("reserved-gap", "900:24:510:878"))
    footer = colors(crop("footer", "900:100:510:910"))
    assert len(visualizer) > len(reserved_gap) + 10
    assert len(footer) > len(reserved_gap) + 10
    assert len(reserved_gap) < 20
