from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import pytest

from wrld_video_studio.domain.player_overlay import (
    FontSettings,
    PlayerOverlaySettings,
    PlayerProgressSettings,
)
from wrld_video_studio.domain.video_effects import PanZoomSettings
from wrld_video_studio.domain.video_effects_v2 import AudioBarsSettingsV2, GlowSettings
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


def _project(
    tmp_path: Path,
    runner: SubprocessRunner,
    tools: MediaToolchain,
    *,
    effects: VideoEffectsV3 | None = None,
    first_track_silence: bool = False,
) -> Path:
    project = tmp_path / "synthetic-player"
    (project / "fonts").mkdir(parents=True)
    shutil.copyfile(_font(), project / "fonts" / "ui.ttf")
    ffmpeg = tools.resolve("ffmpeg").path
    commands = [
        [str(ffmpeg), "-v", "error", "-f", "lavfi", "-i", "color=c=0x1d3557:s=640x360,drawbox=x=80:y=60:w=180:h=120:c=0xd4a017:t=fill", "-frames:v", "1", "-y", str(project / "background.png")],
        [
            str(ffmpeg), "-v", "error", "-f", "lavfi", "-i",
            (
                "anullsrc=r=48000:cl=stereo:d=3"
                if first_track_silence
                else "sine=frequency=440:sample_rate=48000:duration=3"
            ),
            "-ac", "2", "-c:a", "pcm_s16le", "-y", str(project / "one.wav"),
        ],
        [str(ffmpeg), "-v", "error", "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=3", "-ac", "2", "-c:a", "pcm_s16le", "-y", str(project / "two.wav")],
    ]
    for command in commands:
        result = runner.run(command, timeout_seconds=30)
        assert result.returncode == 0 and not result.timed_out
    if effects is None:
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


def _extract_rgb(
    runner: SubprocessRunner,
    ffmpeg: Path,
    source: Path,
    destination: Path,
    *,
    timestamp: float,
    crop: str,
) -> bytes:
    result = runner.run(
        [
            str(ffmpeg), "-v", "error", "-ss", str(timestamp), "-i", str(source),
            "-vf", f"crop={crop}", "-frames:v", "1", "-pix_fmt", "rgb24",
            "-f", "rawvideo", "-y", str(destination),
        ],
        timeout_seconds=60,
    )
    assert result.returncode == 0 and not result.timed_out
    return destination.read_bytes()


@pytest.mark.integration_ffmpeg
@pytest.mark.parametrize("glow_enabled", [False, True])
def test_real_ffmpeg_player_reconstructs_compact_bar_geometry_from_audio(
    tmp_path, glow_enabled
):
    runner, tools = _tools()
    effects = VideoEffectsV3(
        pan_zoom=PanZoomSettings(enabled=False),
        audio_bars=AudioBarsSettingsV2(
            enabled=True,
            variation_mode="organic_rms",
            bar_count=32,
            color="#FFFFFF",
            opacity=1.0,
            placement="bottom_center",
            zone_width_px=900,
            zone_height_px=110,
            gap_px=8,
            horizontal_offset_px=0,
            bottom_margin_px=242,
            attack_ms=0,
            release_ms=0,
            glow=GlowSettings(enabled=glow_enabled, intensity=0.8),
        ),
        player=PlayerOverlaySettings(
            font=FontSettings("fonts/ui.ttf"),
            progress=PlayerProgressSettings(enabled=False),
        ),
    )
    project = _project(
        tmp_path,
        runner,
        tools,
        effects=effects,
        first_track_silence=True,
    )
    code = run_video_export(
        argparse.Namespace(
            album_project=str(project), target="album", track_id=None,
            profile="youtube-1080p30-player-v1",
            ffmpeg_path=str(tools.resolve("ffmpeg").path),
            ffprobe_path=str(tools.resolve("ffprobe").path),
        ),
        state_root=tmp_path / "state",
    )
    assert code == 0
    output = next(
        (project / "output" / "profiles" / "youtube-1080p30-player-v1").rglob("*.mp4")
    )
    ffmpeg = tools.resolve("ffmpeg").path
    crop = "972:182:474:692"
    silent_a = _extract_rgb(
        runner, ffmpeg, output, tmp_path / "silent-a.rgb", timestamp=0.5, crop=crop
    )
    silent_b = _extract_rgb(
        runner, ffmpeg, output, tmp_path / "silent-b.rgb", timestamp=1.5, crop=crop
    )
    tone_a = _extract_rgb(
        runner, ffmpeg, output, tmp_path / "tone-a.rgb", timestamp=3.5, crop=crop
    )
    tone_b = _extract_rgb(
        runner, ffmpeg, output, tmp_path / "tone-b.rgb", timestamp=4.5, crop=crop
    )

    def changed_pixels(left: bytes, right: bytes) -> tuple[int, set[int]]:
        changed = 0
        rows: set[int] = set()
        width = 972
        for offset in range(0, len(left), 3):
            if max(abs(left[offset + channel] - right[offset + channel]) for channel in range(3)) > 12:
                changed += 1
                rows.add((offset // 3) // width)
        return changed, rows

    quiet_change, _ = changed_pixels(silent_a, silent_b)
    active_change_a, active_rows_a = changed_pixels(silent_a, tone_a)
    active_change_b, active_rows_b = changed_pixels(silent_b, tone_b)
    assert quiet_change < 2_000
    assert active_change_a > 5_000
    assert active_change_b > 5_000
    assert len(active_rows_a) > 20
    assert len(active_rows_b) > 20
    # The reconstructed crisp mask must reach the approved bar-zone baseline.
    assert max(active_rows_a) >= 140
    assert max(active_rows_b) >= 140


@pytest.mark.integration_ffmpeg
@pytest.mark.parametrize("bars_enabled", [False, True])
def test_real_ffmpeg_player_progress_advances_over_stationary_rail(
    tmp_path, bars_enabled
):
    runner, tools = _tools()
    effects = VideoEffectsV3(
        pan_zoom=PanZoomSettings(enabled=False),
        audio_bars=AudioBarsSettingsV2(
            enabled=bars_enabled,
            variation_mode="organic_rms",
            bar_count=32,
            color="#FFFFFF",
            opacity=0.55,
            placement="bottom_center",
            zone_width_px=900,
            zone_height_px=110,
            gap_px=8,
            horizontal_offset_px=0,
            bottom_margin_px=242,
            glow=GlowSettings(enabled=False, intensity=0.0),
        ),
        player=PlayerOverlaySettings(font=FontSettings("fonts/ui.ttf")),
    )
    project = _project(tmp_path, runner, tools, effects=effects)
    code = run_video_export(
        argparse.Namespace(
            album_project=str(project), target="album", track_id=None,
            profile="youtube-1080p30-player-v1",
            ffmpeg_path=str(tools.resolve("ffmpeg").path),
            ffprobe_path=str(tools.resolve("ffprobe").path),
        ),
        state_root=tmp_path / "state",
    )
    assert code == 0
    output = next(
        (project / "output" / "profiles" / "youtube-1080p30-player-v1").rglob("*.mp4")
    )
    ffmpeg = tools.resolve("ffmpeg").path
    frames = [
        _extract_rgb(
            runner,
            ffmpeg,
            output,
            tmp_path / f"progress-{index}.rgb",
            timestamp=timestamp,
            crop="1552:6:184:930",
        )
        for index, timestamp in enumerate((0.1, 3.0, 5.8))
    ]

    def column_luma(frame: bytes) -> list[float]:
        width = 1552
        height = 6
        values = []
        for x in range(width):
            total = 0.0
            for y in range(height):
                offset = (y * width + x) * 3
                red, green, blue = frame[offset : offset + 3]
                total += 0.2126 * red + 0.7152 * green + 0.0722 * blue
            values.append(total / height)
        return values

    luminance = [column_luma(frame) for frame in frames]
    boundaries = []
    for values in luminance:
        rail = sum(values[-40:]) / 40
        fill = sum(values[:10]) / 10
        threshold = (rail + fill) / 2
        boundaries.append(sum(value < threshold for value in values))

    assert boundaries[0] == pytest.approx(26, abs=24)
    assert boundaries[1] == pytest.approx(776, abs=30)
    assert boundaries[2] == pytest.approx(1500, abs=30)
    assert boundaries[0] < boundaries[1] < boundaries[2]
    # The unfilled rail at the far end remains the same while only the fill advances.
    for left, right in zip(luminance, luminance[1:]):
        assert max(abs(a - b) for a, b in zip(left[-20:], right[-20:], strict=True)) < 8
