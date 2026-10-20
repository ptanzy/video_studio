from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from wrld_video_studio.application.ports.media import ArtifactVerifier, MediaProber, ProcessRunner
from wrld_video_studio.domain.jobs import MediaProbe
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.infrastructure.media_tools import MediaToolchain


class FFmpegArtifactVerifier(ArtifactVerifier):
    def __init__(
        self,
        prober: MediaProber,
        toolchain: MediaToolchain,
        runner: ProcessRunner,
        *,
        decode_seconds: float = 0.25,
    ) -> None:
        self.prober = prober
        self.toolchain = toolchain
        self.runner = runner
        self.decode_seconds = decode_seconds

    def verify(self, path: Path, expected: Mapping[str, Any]) -> MediaProbe:
        if not path.is_file() or path.stat().st_size <= 0:
            raise MediaInfrastructureError("OUTPUT_INVALID", "Output is missing or empty.")
        probe = self.prober.probe(path)
        video = next((stream for stream in probe.streams if stream.codec_type == "video"), None)
        audio = next((stream for stream in probe.streams if stream.codec_type == "audio"), None)
        if video is None or audio is None:
            raise MediaInfrastructureError("OUTPUT_INVALID", "Output must contain video and audio streams.")
        requirements = (
            (video.codec_name == expected.get("video_codec"), "video codec"),
            (audio.codec_name == expected.get("audio_codec"), "audio codec"),
            (video.width == expected.get("width"), "video width"),
            (video.height == expected.get("height"), "video height"),
            (video.pixel_format == expected.get("pixel_format"), "video pixel format"),
            (
                video.frame_rate is not None
                and abs(video.frame_rate - expected["frame_rate"]) < 0.05,
                "video frame rate",
            ),
            (probe.duration_seconds is not None, "positive duration"),
            ("mp4" in (probe.format_name or ""), "MP4 container"),
        )
        for valid, label in requirements:
            if not valid:
                raise MediaInfrastructureError("OUTPUT_INVALID", f"Output {label} check failed.")
        expected_duration = float(expected["duration_seconds"])
        tolerance = float(expected["duration_tolerance_seconds"])
        assert probe.duration_seconds is not None
        if abs(probe.duration_seconds - expected_duration) > tolerance:
            raise MediaInfrastructureError("OUTPUT_INVALID", "Output duration is outside declared tolerance.")
        expected_tag = f"wrld_snapshot:{expected['snapshot_digest']}"
        if probe.format_tags.get("comment") != expected_tag:
            raise MediaInfrastructureError("OUTPUT_PROVENANCE_MISMATCH", "Output does not match this snapshot.")

        ffmpeg = self.toolchain.resolve("ffmpeg")
        decoded = self.runner.run(
            [
                str(ffmpeg.path), "-hide_banner", "-nostdin", "-v", "error", "-xerror",
                "-i", str(path), "-t", str(min(self.decode_seconds, expected_duration)),
                "-f", "null", "-",
            ],
            timeout_seconds=15.0,
        )
        if decoded.timed_out or decoded.returncode != 0:
            raise MediaInfrastructureError(
                "OUTPUT_DECODE_FAILED",
                "Output failed bounded decode verification.",
                {"stderr_tail": self.runner.sanitize_diagnostic(decoded.stderr_tail)},
            )
        return probe