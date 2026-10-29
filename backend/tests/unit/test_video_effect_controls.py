import math
import re
import threading
from array import array

import pytest

from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.player_overlay import FontSettings, PlayerOverlaySettings
from wrld_video_studio.domain.video_effects import (
    AudioBarsSettings,
    TrackProgressSettings,
    VideoEffects,
)
from wrld_video_studio.domain.video_effects_v2 import (
    AudioBarsSettingsV2,
    TrackProgressSettingsV2,
    VideoEffectsV2,
)
from wrld_video_studio.domain.video_export import TimelineEntry
from wrld_video_studio.domain.video_effects_v3 import VideoEffectsV3
from wrld_video_studio.infrastructure.video_effect_controls import (
    VideoEffectControlBuilder,
)


def _pcm(path, sample_count, amplitude):
    samples = array("h")
    for index in range(sample_count):
        value = round(amplitude * math.sin(2 * math.pi * 440 * index / 48_000))
        samples.extend((value, value))
    path.write_bytes(samples.tobytes())


def test_control_stream_reads_pcm_windows_without_loading_tracks_and_resets(tmp_path):
    first = tmp_path / "first.pcm"
    second = tmp_path / "second.pcm"
    _pcm(first, 3_200, 20_000)
    _pcm(second, 3_200, 0)
    timeline = (
        TimelineEntry("one", 1, "One", 0, 3_200),
        TimelineEntry("two", 2, "Two", 3_200, 3_200),
    )
    effects = VideoEffects(
        audio_bars=AudioBarsSettings(
            enabled=True, bar_count=8, rms_window_samples=480, attack_ms=0, release_ms=0
        ),
        track_progress=TrackProgressSettings(enabled=True, placement="top"),
    )
    destination = tmp_path / "effects.sendcmd"

    plan = VideoEffectControlBuilder().build(
        (first, second), timeline, effects, destination
    )

    commands = destination.read_text(encoding="ascii")
    assert plan.frame_count == 4
    assert plan.command_count > 0
    assert "drawbox@wrld_bar_00 h " in commands
    assert "0.066666667" in commands
    assert "drawbox@wrld_bar_00 h 2" in commands
    assert "drawbox@wrld_progress color white@0" in commands
    assert len(plan.filters) == 9
    assert plan.filters[-1].startswith("drawbox@wrld_progress=")


@pytest.mark.parametrize("window", [480, 1920, 4800])
def test_supported_rms_window_sizes_are_deterministic(tmp_path, window):
    pcm = tmp_path / f"{window}.pcm"
    _pcm(pcm, 4_800, 12_000)
    timeline = (TimelineEntry("one", 1, "One", 0, 4_800),)
    effects = VideoEffects(
        audio_bars=AudioBarsSettings(
            enabled=True, bar_count=8, rms_window_samples=window, attack_ms=0, release_ms=0
        )
    )
    first = tmp_path / f"first-{window}.sendcmd"
    second = tmp_path / f"second-{window}.sendcmd"
    builder = VideoEffectControlBuilder()
    assert builder.build((pcm,), timeline, effects, first) == builder.build(
        (pcm,), timeline, effects, second
    )
    assert first.read_bytes() == second.read_bytes()


def test_segmented_progress_resets_at_non_aligned_track_boundary(tmp_path):
    first = tmp_path / "first.pcm"
    second = tmp_path / "second.pcm"
    _pcm(first, 2_001, 0)
    _pcm(second, 3_000, 0)
    timeline = (
        TimelineEntry("one", 1, "One", 0, 2_001),
        TimelineEntry("two", 2, "Two", 2_001, 3_000),
    )
    effects = VideoEffects(
        track_progress=TrackProgressSettings(
            enabled=True, style="segmented", segment_count=5
        )
    )
    destination = tmp_path / "segments.sendcmd"
    VideoEffectControlBuilder().build((first, second), timeline, effects, destination)
    commands = destination.read_text(encoding="ascii")
    assert "drawbox@wrld_segment_00 color white@0.800000" in commands
    assert "drawbox@wrld_segment_00 color white@0" in commands


def test_cancellation_leaves_only_attempt_owned_partial_for_outer_cleanup(tmp_path):
    pcm = tmp_path / "one.pcm"
    _pcm(pcm, 4_800, 10_000)
    destination = tmp_path / "effects.sendcmd"
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(MediaInfrastructureError) as caught:
        VideoEffectControlBuilder().build(
            (pcm,),
            (TimelineEntry("one", 1, "One", 0, 4_800),),
            VideoEffects(audio_bars=AudioBarsSettings(enabled=True)),
            destination,
            cancel_event=cancelled,
        )
    assert caught.value.code == "PROCESS_CANCELLED"
    assert destination.is_file()


def test_long_progress_control_grows_with_pixel_changes_not_every_frame(tmp_path):
    pcm = tmp_path / "long.pcm"
    sample_count = 10 * 60 * 48_000
    with pcm.open("wb") as stream:
        stream.truncate(sample_count * 4)
    destination = tmp_path / "long.sendcmd"
    plan = VideoEffectControlBuilder().build(
        (pcm,),
        (TimelineEntry("one", 1, "One", 0, sample_count),),
        VideoEffects(track_progress=TrackProgressSettings(enabled=True)),
        destination,
    )
    assert plan.frame_count == 18_000
    assert plan.command_count <= 1_794
    assert destination.stat().st_size < 200_000


def test_attack_state_resets_to_zero_for_each_equally_loud_track(tmp_path):
    first = tmp_path / "first.pcm"
    second = tmp_path / "second.pcm"
    _pcm(first, 4_800, 20_000)
    _pcm(second, 4_800, 20_000)
    destination = tmp_path / "reset.sendcmd"
    effects = VideoEffects(
        audio_bars=AudioBarsSettings(
            enabled=True,
            bar_count=8,
            rms_window_samples=480,
            attack_ms=60,
            release_ms=240,
        )
    )
    VideoEffectControlBuilder().build(
        (first, second),
        (
            TimelineEntry("one", 1, "One", 0, 4_800),
            TimelineEntry("two", 2, "Two", 4_800, 4_800),
        ),
        effects,
        destination,
    )
    heights = {}
    for line in destination.read_text(encoding="ascii").splitlines():
        timestamp = line.split(" ", 1)[0]
        match = re.search(r"drawbox@wrld_bar_03 h (\d+)", line)
        if match:
            heights[timestamp] = int(match.group(1))
    assert heights["0.000000000"] == heights["0.100000000"]
    assert heights["0.066666667"] > heights["0.000000000"]


def test_preview_prerolls_rms_state_and_emits_absolute_timeline_state_at_zero(tmp_path):
    pcm = tmp_path / "tone.pcm"
    _pcm(pcm, 96_000, 20_000)
    timeline = (TimelineEntry("one", 1, "One", 0, 96_000),)
    effects = VideoEffects(
        audio_bars=AudioBarsSettings(
            enabled=True,
            bar_count=8,
            rms_window_samples=480,
            attack_ms=500,
            release_ms=1000,
        ),
        track_progress=TrackProgressSettings(enabled=True),
    )
    destination = tmp_path / "preview.sendcmd"
    plan = VideoEffectControlBuilder().build(
        (pcm,),
        timeline,
        effects,
        destination,
        start_sample=48_000,
        sample_count=48_000,
    )
    first = destination.read_text(encoding="ascii").splitlines()[0]
    assert first.startswith("0.000000000 ")
    assert "drawbox@wrld_bar_03 h " in first
    assert "drawbox@wrld_progress w 896" in first
    assert plan.frame_count == 30


def test_refined_controls_use_organic_absolute_time_color_and_full_rail(tmp_path):
    pcm = tmp_path / "tone.pcm"
    _pcm(pcm, 96_000, 20_000)
    effects = VideoEffectsV2(
        audio_bars=AudioBarsSettingsV2(
            enabled=True,
            color="#FF69B4",
            bar_count=8,
            attack_ms=0,
            release_ms=0,
        ),
        track_progress=TrackProgressSettingsV2(
            enabled=True,
            color="#800080",
        ),
    )
    first = tmp_path / "first.sendcmd"
    second = tmp_path / "second.sendcmd"
    timeline = (TimelineEntry("one", 1, "One", 0, 96_000),)
    builder = VideoEffectControlBuilder()
    one = builder.build((pcm,), timeline, effects, first)
    two = builder.build((pcm,), timeline, effects, second)
    assert one == two
    assert first.read_bytes() == second.read_bytes()
    commands = first.read_text(encoding="ascii")
    assert "drawbox@wrld_bar_00 h " in commands
    assert "drawbox@wrld_progress color 0x800080@0.800000" in commands
    assert any("wrld_progress_rail" in item and "w=1792" in item for item in one.filters)
    assert any("color=0xD8CBD8@0.350000" in item for item in one.filters)


def test_refined_rms_smoothing_resets_at_track_boundary(tmp_path):
    first = tmp_path / "one.pcm"
    second = tmp_path / "two.pcm"
    _pcm(first, 4_800, 20_000)
    _pcm(second, 4_800, 20_000)
    destination = tmp_path / "refined-reset.sendcmd"
    VideoEffectControlBuilder().build(
        (first, second),
        (
            TimelineEntry("one", 1, "One", 0, 4_800),
            TimelineEntry("two", 2, "Two", 4_800, 4_800),
        ),
        VideoEffectsV2(
            audio_bars=AudioBarsSettingsV2(
                enabled=True,
                bar_count=8,
                rms_window_samples=480,
                attack_ms=60,
                release_ms=240,
            )
        ),
        destination,
    )
    commands = destination.read_text(encoding="ascii")
    first_height = re.search(r"^0\.000000000 .*?drawbox@wrld_bar_03 h (\d+)", commands, re.M)
    reset_height = re.search(r"^0\.100000000 .*?drawbox@wrld_bar_03 h (\d+)", commands, re.M)
    assert first_height is not None and reset_height is not None
    assert first_height.group(1) != "2"
    assert reset_height.group(1) != "2"


def test_refined_long_silent_controls_remain_bounded(tmp_path):
    pcm = tmp_path / "long-refined.pcm"
    sample_count = 60 * 48_000
    with pcm.open("wb") as stream:
        stream.truncate(sample_count * 4)
    destination = tmp_path / "long-refined.sendcmd"
    plan = VideoEffectControlBuilder().build(
        (pcm,),
        (TimelineEntry("one", 1, "One", 0, sample_count),),
        VideoEffectsV2(
            audio_bars=AudioBarsSettingsV2(enabled=True),
            track_progress=TrackProgressSettingsV2(enabled=True),
        ),
        destination,
    )
    assert plan.frame_count == 1_800
    assert plan.command_count <= 1_794
    assert destination.stat().st_size < 200_000


def test_refined_one_minute_organic_control_file_remains_linear_and_bounded(tmp_path):
    pcm = tmp_path / "minute-tone.pcm"
    sample_count = 60 * 48_000
    frame = array("h", [10_000, 10_000]).tobytes()
    pcm.write_bytes(frame * sample_count)
    destination = tmp_path / "minute-organic.sendcmd"
    plan = VideoEffectControlBuilder().build(
        (pcm,),
        (TimelineEntry("one", 1, "One", 0, sample_count),),
        VideoEffectsV2(
            audio_bars=AudioBarsSettingsV2(
                enabled=True,
                rms_window_samples=480,
                attack_ms=0,
                release_ms=0,
            ),
            track_progress=TrackProgressSettingsV2(enabled=True),
        ),
        destination,
    )
    assert plan.frame_count == 1_800
    assert plan.command_count <= plan.frame_count * 25
    assert destination.stat().st_size < 5_000_000


def test_player_full_album_uses_compact_bar_frames_and_bounded_sendcmd(tmp_path):
    pcm = tmp_path / "album.pcm"
    sample_count = 2_196 * 48_000
    with pcm.open("wb") as stream:
        stream.truncate(sample_count * 4)
    destination = tmp_path / "album.sendcmd"
    plan = VideoEffectControlBuilder().build(
        (pcm,),
        (TimelineEntry("album", 1, "Album", 0, sample_count),),
        VideoEffectsV3(player=PlayerOverlaySettings(font=FontSettings("fonts/ui.ttf"))),
        destination,
        progress_width=1_576,
        progress_color="#FFFFFF",
        compact_player_bars=True,
    )
    assert plan.frame_count == 65_880
    assert plan.bar_control_path == destination.with_suffix(".bars.gray16")
    assert plan.bar_control_width == 972
    assert plan.bar_control_path.stat().st_size == plan.frame_count * plan.bar_control_width * 2
    assert plan.command_count <= 1_578
    assert destination.stat().st_size < 200_000
    assert "wrld_bar" not in destination.read_text(encoding="ascii")

