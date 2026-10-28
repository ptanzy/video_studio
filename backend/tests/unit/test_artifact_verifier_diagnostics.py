from pathlib import Path

import pytest

from wrld_video_studio.domain.jobs import MediaProbe, MediaStream, ProcessExecution
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.infrastructure.artifact_verifier import FFmpegArtifactVerifier


class ProbeWithoutTransfer:
    def probe(self, path):
        return MediaProbe(
            str(path),
            "ffprobe version 9.0.2",
            1.0,
            (
                MediaStream(
                    0,
                    "video",
                    "h264",
                    profile="High",
                    width=1920,
                    height=1080,
                    frame_rate=30.0,
                    pixel_format="yuv420p",
                    color_space="bt709",
                    color_transfer=None,
                    color_primaries="bt709",
                ),
                MediaStream(1, "audio", "aac", profile="LC", sample_rate=48000, channels=2),
            ),
            "mov,mp4,m4a,3gp,3g2,mj2",
            {"comment": "wrld_request:" + "a" * 64},
        )


class NoopRunner:
    def run(self, *args, **kwargs):
        return ProcessExecution(0, "", "")

    @staticmethod
    def sanitize_diagnostic(value):
        return value


class Toolchain:
    def resolve(self, name):
        return type("Tool", (), {"path": Path(name), "version": f"{name} version 9.0.2"})()


def test_strict_color_transfer_failure_exposes_exact_probe_predicate(tmp_path):
    output = tmp_path / "video.mp4"
    output.write_bytes(b"mp4")
    verifier = FFmpegArtifactVerifier(ProbeWithoutTransfer(), Toolchain(), NoopRunner())
    expected = {
        "video_codec": "h264",
        "audio_codec": "aac",
        "pixel_format": "yuv420p",
        "width": 1920,
        "height": 1080,
        "frame_rate": 30,
        "audio_sample_rate": 48000,
        "audio_channels": 2,
        "video_profile": "High",
        "audio_profile": "LC",
        "color_space": "bt709",
        "color_transfer": "bt709",
        "color_primaries": "bt709",
        "duration_seconds": 1.0,
        "duration_tolerance_seconds": 0.25,
        "request_digest": "a" * 64,
        "faststart": False,
        "full_decode": True,
    }

    with pytest.raises(MediaInfrastructureError) as caught:
        verifier.verify(output, expected)

    assert caught.value.code == "OUTPUT_INVALID"
    assert caught.value.details["predicate"] == "video color transfer"
    assert caught.value.details["expected"] == "bt709"
    assert caught.value.details["actual"] is None
    assert caught.value.details["probe"]["tool_version"] == "ffprobe version 9.0.2"
