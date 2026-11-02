from pathlib import Path
import re

import pytest

from wrld_video_studio.domain.jobs import ProcessExecution
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.motion_preview import (
    MotionPreviewExcerpt,
    MotionPreviewRequest,
    create_motion_preview_plan,
)
from wrld_video_studio.domain.video_export import (
    ExportTarget,
    VideoExportRequest,
    create_plan,
    parse_manifest,
)
from wrld_video_studio.domain.video_effects import (
    AudioBarsSettings,
    PanZoomSettings,
    TrackProgressSettings,
    VideoEffects,
)
from wrld_video_studio.domain.video_effects_v2 import (
    AudioBarsSettingsV2,
    GlowSettings,
    TrackProgressSettingsV2,
    VideoEffectsV2,
)
from wrld_video_studio.domain.video_export_v2 import (
    MotionVideoExportRequest,
    create_motion_plan,
    parse_motion_manifest,
)
from wrld_video_studio.domain.video_export_v3 import (
    RefinedVideoExportRequest,
    create_refined_plan,
    parse_refined_manifest,
)
from wrld_video_studio.infrastructure.media_tools import MediaToolchain
from wrld_video_studio.infrastructure.video_export_renderer import StaticVideoExportRenderer


class FakeRunner:
    def __init__(self):
        self.calls = []

    def run(self, argv, timeout_seconds, **kwargs):
        self.calls.append((argv, timeout_seconds))
        if argv[-1] == "-version":
            return ProcessExecution(0, f"{Path(argv[0]).stem} version fixture", "")
        if argv[-1] == "-filters":
            names = (
                "scale", "pad", "format", "setparams", "sendcmd", "drawbox", "zoompan",
                "color", "crop", "overlay", "colorchannelmixer", "split", "gblur",
            )
            return ProcessExecution(
                0, "\n".join(f" T. {name} V->V fixture" for name in names), ""
            )
        if "format=duration" in argv:
            return ProcessExecution(0, "1.0\n", "")
        output = Path(argv[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        if "pcm_s16le" in argv:
            samples = 48_000
            if "-af" in argv:
                match = re.search(
                    r"atrim=start_sample=(\d+):end_sample=(\d+)",
                    argv[argv.index("-af") + 1],
                )
                assert match is not None
                samples = int(match.group(2)) - int(match.group(1))
            output.write_bytes(b"\0" * (samples * 4))
        else:
            output.write_bytes(b"mp4")
        return ProcessExecution(0, "progress=end\n", "", sanitized_argv=tuple(argv))

    @staticmethod
    def sanitize_diagnostic(text):
        return text


def test_product_renderer_uses_approved_profile_and_sample_counts(tmp_path):
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    ffmpeg.write_bytes(b"tool")
    ffprobe.write_bytes(b"tool")
    audio = tmp_path / "source.wav"
    background = tmp_path / "background.png"
    audio.write_bytes(b"source")
    background.write_bytes(b"image")
    document = {
        "format": "wrld-video-album/1.0",
        "album": {"id": "a1", "title": "A", "artist": "B", "channel": "C"},
        "visual": {"background": "background.png"},
        "tracks": [{"id": "t1", "number": 1, "title": "T", "audio": "source.wav"}],
        "render": {"profile_id": "youtube-1080p30-v1"},
    }
    plan = create_plan(parse_manifest(document), VideoExportRequest(ExportTarget("album")))
    runner = FakeRunner()
    renderer = StaticVideoExportRenderer(
        MediaToolchain(runner, {"ffmpeg": ffmpeg, "ffprobe": ffprobe}), runner
    )
    output = tmp_path / "stage" / "video.mp4"
    rendered = renderer.render(
        plan,
        (audio,),
        background,
        output,
        (tmp_path / "stage" / "one.pcm",),
        tmp_path / "stage" / "combined.pcm",
        "a" * 64,
    )
    assert rendered.total_samples == 48_000
    command = next(argv for argv, _timeout in runner.calls if "libx264" in argv)
    for pair in (
        ("-profile:v", "high"),
        ("-preset", "medium"),
        ("-crf", "18"),
        ("-pix_fmt", "yuv420p"),
        ("-b:a", "192k"),
        ("-movflags", "+faststart"),
    ):
        index = command.index(pair[0])
        assert command[index + 1] == pair[1]
    video_filter = command[command.index("-vf") + 1]
    assert video_filter == (
        "scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos:"
        "out_color_matrix=bt709,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,"
        "format=yuv420p,"
        "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709"
    )
    assert "force_original_aspect_ratio=decrease" in video_filter
    assert "out_color_matrix=bt709" in video_filter
    assert "format=yuv420p" in video_filter
    assert "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709" in video_filter
    for option in ("-colorspace", "-color_primaries", "-color_trc"):
        assert command[command.index(option) + 1] == "bt709"
    assert output.read_bytes() == b"mp4"


def _motion_plan(*, enabled=False, bars=False, progress=False):
    effects = VideoEffects(
        pan_zoom=PanZoomSettings(enabled=enabled),
        audio_bars=AudioBarsSettings(enabled=bars, attack_ms=0, release_ms=0),
        track_progress=TrackProgressSettings(enabled=progress),
    )
    document = {
        "format": "wrld-video-album/2.0",
        "album": {"id": "a1", "title": "A", "artist": "B", "channel": "C"},
        "visual": {"background": "background.png"},
        "tracks": [{"id": "t1", "number": 1, "title": "T", "audio": "source.wav"}],
        "render": {
            "profile_id": "youtube-1080p30-motion-v1",
            "effects": effects.to_dict(),
        },
    }
    manifest = parse_motion_manifest(document)
    return create_motion_plan(
        manifest,
        MotionVideoExportRequest(ExportTarget("album"), effects),
    )


def _motion_preview_plan(start_sample, sample_count, *, bars=False, progress=False):
    effects = VideoEffects(
        audio_bars=AudioBarsSettings(enabled=bars, attack_ms=0, release_ms=0),
        track_progress=TrackProgressSettings(enabled=progress),
    )
    document = {
        "format": "wrld-video-album/2.0",
        "album": {"id": "a1", "title": "A", "artist": "B", "channel": "C"},
        "visual": {"background": "background.png"},
        "tracks": [
            {"id": f"t{index}", "number": index, "title": f"T{index}", "audio": f"{index}.wav"}
            for index in range(1, 4)
        ],
        "render": {"profile_id": "youtube-1080p30-motion-v1", "effects": effects.to_dict()},
    }
    manifest = parse_motion_manifest(document)
    request = MotionPreviewRequest(
        ExportTarget("album"), effects, MotionPreviewExcerpt(start_sample, sample_count)
    )
    return create_motion_preview_plan(manifest, request)


def test_preview_normalizes_only_intersecting_sample_windows(tmp_path):
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    ffmpeg.write_bytes(b"tool")
    ffprobe.write_bytes(b"tool")
    background = tmp_path / "background.png"
    background.write_bytes(b"image")
    audio = tuple(tmp_path / f"{index}.wav" for index in range(1, 4))
    for path in audio:
        path.write_bytes(b"source")
    runner = FakeRunner()
    renderer = StaticVideoExportRenderer(
        MediaToolchain(runner, {"ffmpeg": ffmpeg, "ffprobe": ffprobe}), runner
    )
    stage = tmp_path / "stage"
    excerpt_samples = 240_000

    rendered = renderer.render(
        _motion_preview_plan(400_000, excerpt_samples, bars=True, progress=True),
        audio,
        background,
        stage / "video.mp4",
        tuple(stage / f"{index}.pcm" for index in range(1, 4)),
        stage / "combined.pcm",
        "a" * 64,
        effect_control_path=stage / "effects.sendcmd",
        source_sample_counts=(480_000, 480_000, 480_000),
    )

    normalizations = [argv for argv, _timeout in runner.calls if "pcm_s16le" in argv]
    assert len(normalizations) == 2
    assert all("atrim=start_sample=" in argv[argv.index("-af") + 1] for argv in normalizations)
    assert (stage / "combined.pcm").stat().st_size == excerpt_samples * 4
    command = next(argv for argv, _timeout in runner.calls if "libx264" in argv)
    assert "-ss" not in command
    assert rendered.total_samples == excerpt_samples
    assert rendered.timeline[1].start_sample == 480_000


def _refined_plan(*, camera=False, bars=False, progress=False, glow=True):
    effects = VideoEffectsV2(
        pan_zoom=PanZoomSettings(enabled=camera),
        audio_bars=AudioBarsSettingsV2(
            enabled=bars,
            color="#FF69B4",
            attack_ms=0,
            release_ms=0,
            glow=GlowSettings(enabled=glow, intensity=0.35),
        ),
        track_progress=TrackProgressSettingsV2(
            enabled=progress,
            color="#800080",
        ),
    )
    document = {
        "format": "wrld-video-album/3.0",
        "album": {"id": "a1", "title": "A", "artist": "B", "channel": "C"},
        "visual": {"background": "background.png"},
        "tracks": [{"id": "t1", "number": 1, "title": "T", "audio": "source.wav"}],
        "render": {
            "profile_id": "youtube-1080p30-motion-v2",
            "effects": effects.to_dict(),
        },
    }
    manifest = parse_refined_manifest(document)
    return create_refined_plan(
        manifest,
        RefinedVideoExportRequest(ExportTarget("album"), effects),
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_motion_renderer_selects_camera_filter_without_changing_encoding(tmp_path, enabled):
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    ffmpeg.write_bytes(b"tool")
    ffprobe.write_bytes(b"tool")
    audio = tmp_path / "source.wav"
    background = tmp_path / "background.png"
    audio.write_bytes(b"source")
    background.write_bytes(b"image")
    runner = FakeRunner()
    renderer = StaticVideoExportRenderer(
        MediaToolchain(runner, {"ffmpeg": ffmpeg, "ffprobe": ffprobe}), runner
    )

    renderer.render(
        _motion_plan(enabled=enabled),
        (audio,),
        background,
        tmp_path / "stage" / "video.mp4",
        (tmp_path / "stage" / "one.pcm",),
        tmp_path / "stage" / "combined.pcm",
        "a" * 64,
    )

    command = next(argv for argv, _timeout in runner.calls if "libx264" in argv)
    video_filter = command[command.index("-vf") + 1]
    assert ("zoompan=" in video_filter) is enabled
    assert video_filter.startswith(
        "scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos:"
        "out_color_matrix=bt709,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,"
    )
    assert video_filter.endswith(
        "format=yuv420p,"
        "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709"
    )


@pytest.mark.parametrize(
    ("camera", "bars", "progress"),
    [
        (False, False, False),
        (True, False, False),
        (False, True, False),
        (False, False, True),
        (True, True, False),
        (True, False, True),
        (False, True, True),
        (True, True, True),
    ],
)
def test_motion_renderer_supports_every_approved_effect_combination(
    tmp_path, camera, bars, progress
):
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    ffmpeg.write_bytes(b"tool")
    ffprobe.write_bytes(b"tool")
    audio = tmp_path / "source.wav"
    background = tmp_path / "background.png"
    audio.write_bytes(b"source")
    background.write_bytes(b"image")
    runner = FakeRunner()
    renderer = StaticVideoExportRenderer(
        MediaToolchain(runner, {"ffmpeg": ffmpeg, "ffprobe": ffprobe}), runner
    )
    control = tmp_path / "stage" / "effects.sendcmd"

    renderer.render(
        _motion_plan(enabled=camera, bars=bars, progress=progress),
        (audio,),
        background,
        tmp_path / "stage" / "video.mp4",
        (tmp_path / "stage" / "one.pcm",),
        tmp_path / "stage" / "combined.pcm",
        "a" * 64,
        effect_control_path=control,
    )

    command = next(argv for argv, _timeout in runner.calls if "libx264" in argv)
    video_filter = command[command.index("-vf") + 1]
    assert ("zoompan=" in video_filter) is camera
    if camera and (bars or progress):
        assert video_filter.index("zoompan=") < video_filter.index("drawbox@")
    assert ("wrld_bar_00" in video_filter) is bars
    assert ("wrld_progress" in video_filter) is progress
    assert ("sendcmd=filename=" in video_filter) is progress
    assert control.is_file() is (bars or progress)


def test_motion_overlay_preflight_rejects_missing_ffmpeg_filters(tmp_path):
    class MissingFilterRunner(FakeRunner):
        def run(self, argv, timeout_seconds, **kwargs):
            if argv[-1] == "-filters":
                self.calls.append((argv, timeout_seconds))
                return ProcessExecution(0, " .. scale V->V fixture\n", "")
            return super().run(argv, timeout_seconds, **kwargs)

    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    ffmpeg.write_bytes(b"tool")
    ffprobe.write_bytes(b"tool")
    audio = tmp_path / "source.wav"
    background = tmp_path / "background.png"
    audio.write_bytes(b"source")
    background.write_bytes(b"image")
    runner = MissingFilterRunner()
    renderer = StaticVideoExportRenderer(
        MediaToolchain(runner, {"ffmpeg": ffmpeg, "ffprobe": ffprobe}), runner
    )

    with pytest.raises(MediaInfrastructureError) as caught:
        renderer.render(
            _motion_plan(bars=True),
            (audio,),
            background,
            tmp_path / "stage" / "video.mp4",
            (tmp_path / "stage" / "one.pcm",),
            tmp_path / "stage" / "combined.pcm",
            "a" * 64,
            effect_control_path=tmp_path / "stage" / "effects.sendcmd",
        )
    assert caught.value.code == "MEDIA_TOOL_INVALID"


@pytest.mark.parametrize(
    ("camera", "bars", "progress", "glow"),
    [
        (False, False, False, True),
        (True, False, False, True),
        (False, True, False, False),
        (False, True, False, True),
        (False, False, True, True),
        (True, True, True, True),
    ],
)
def test_refined_renderer_uses_isolated_complex_graph_only_for_overlays(
    tmp_path, camera, bars, progress, glow
):
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    ffmpeg.write_bytes(b"tool")
    ffprobe.write_bytes(b"tool")
    audio = tmp_path / "source.wav"
    background = tmp_path / "background.png"
    audio.write_bytes(b"source")
    background.write_bytes(b"image")
    runner = FakeRunner()
    renderer = StaticVideoExportRenderer(
        MediaToolchain(runner, {"ffmpeg": ffmpeg, "ffprobe": ffprobe}), runner
    )
    renderer.render(
        _refined_plan(camera=camera, bars=bars, progress=progress, glow=glow),
        (audio,),
        background,
        tmp_path / "stage" / "video.mp4",
        (tmp_path / "stage" / "one.pcm",),
        tmp_path / "stage" / "combined.pcm",
        "a" * 64,
        effect_control_path=tmp_path / "stage" / "effects.sendcmd",
    )
    command = next(argv for argv, _timeout in runner.calls if "libx264" in argv)
    assert ("-filter_complex" in command) is (bars or progress)
    if not (bars or progress):
        assert "-vf" in command
        return
    graph = command[command.index("-filter_complex") + 1]
    assert command[command.index("-map") + 1] == "[vout]"
    assert ("zoompan=" in graph) is camera
    assert ("wrld_bar_00" in graph) is bars
    assert ("wrld_progress_rail" in graph) is progress
    assert graph.endswith(
        "format=yuv420p,setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709[vout]"
    )
    if bars:
        assert "color=c=black@0.0:s=712x252" in graph
        assert "t=fill:replace=1" in graph
        assert "overlay=604:800" in graph
        assert "colorchannelmixer=" in graph
        assert ("gblur=sigma=12" in graph) is glow
        if glow:
            assert graph.index("gblur=sigma=12") < graph.index("[glow_layer][crisp_layer]overlay")
            assert graph.index("[glow_layer][crisp_layer]overlay") < graph.index("[base][bar_layer]overlay")
    if progress:
        assert "w=1792" in graph
        assert "color=0xD8CBD8@0.350000" in graph
        assert "color=0x800080@0.000000" in graph


def test_refined_preflight_requires_local_glow_filters(tmp_path):
    class MissingGlowRunner(FakeRunner):
        def run(self, argv, timeout_seconds, **kwargs):
            if argv[-1] == "-filters":
                self.calls.append((argv, timeout_seconds))
                names = (
                    "scale", "pad", "format", "setparams", "sendcmd", "drawbox",
                    "color", "overlay", "colorchannelmixer",
                )
                return ProcessExecution(
                    0, "\n".join(f" T. {name} V->V fixture" for name in names), ""
                )
            return super().run(argv, timeout_seconds, **kwargs)

    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    ffmpeg.write_bytes(b"tool")
    ffprobe.write_bytes(b"tool")
    audio = tmp_path / "source.wav"
    background = tmp_path / "background.png"
    audio.write_bytes(b"source")
    background.write_bytes(b"image")
    runner = MissingGlowRunner()
    renderer = StaticVideoExportRenderer(
        MediaToolchain(runner, {"ffmpeg": ffmpeg, "ffprobe": ffprobe}), runner
    )
    with pytest.raises(MediaInfrastructureError) as caught:
        renderer.render(
            _refined_plan(bars=True, glow=True),
            (audio,),
            background,
            tmp_path / "stage" / "video.mp4",
            (tmp_path / "stage" / "one.pcm",),
            tmp_path / "stage" / "combined.pcm",
            "a" * 64,
            effect_control_path=tmp_path / "stage" / "effects.sendcmd",
        )
    assert caught.value.code == "MEDIA_TOOL_INVALID"
    assert set(caught.value.details["missing_filters"]) == {"gblur", "split"}


def test_preview_renderer_seeks_audio_and_uses_absolute_camera_time(tmp_path):
    class LongRunner(FakeRunner):
        def run(self, argv, timeout_seconds, **kwargs):
            result = super().run(argv, timeout_seconds, **kwargs)
            if "pcm_s16le" in argv:
                Path(argv[-1]).write_bytes(b"\0" * (480_000 * 4))
            return result

    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    ffmpeg.write_bytes(b"tool")
    ffprobe.write_bytes(b"tool")
    audio = tmp_path / "source.wav"
    background = tmp_path / "background.png"
    audio.write_bytes(b"source")
    background.write_bytes(b"image")
    motion = _motion_plan(enabled=True, bars=True, progress=True)
    plan = create_motion_preview_plan(
        motion.manifest,
        MotionPreviewRequest(
            motion.request.target,
            motion.request.effects,
            MotionPreviewExcerpt(96_000, 144_000),
        ),
    )
    runner = LongRunner()
    renderer = StaticVideoExportRenderer(
        MediaToolchain(runner, {"ffmpeg": ffmpeg, "ffprobe": ffprobe}), runner
    )
    rendered = renderer.render(
        plan,
        (audio,),
        background,
        tmp_path / "stage" / "preview.mp4",
        (tmp_path / "stage" / "one.pcm",),
        tmp_path / "stage" / "combined.pcm",
        "a" * 64,
        effect_control_path=tmp_path / "stage" / "effects.sendcmd",
    )
    command = next(argv for argv, _timeout in runner.calls if "libx264" in argv)
    assert command[command.index("-ss") + 1] == "2.000000000"
    assert command[command.index("-t") + 1] == "3.000000000"
    video_filter = command[command.index("-vf") + 1]
    assert "on/30+2" in video_filter
    assert "gte(on,89)" not in video_filter
    assert "sendcmd=filename=" in video_filter
    assert rendered.total_samples == 144_000
    assert rendered.duration_seconds == 3.0
