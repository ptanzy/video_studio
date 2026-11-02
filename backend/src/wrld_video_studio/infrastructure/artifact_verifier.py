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

    def verify(
        self,
        path: Path,
        expected: Mapping[str, Any],
        cancel_event: Any = None,
        heartbeat: Any = None,
        phase_callback: Any = None,
    ) -> MediaProbe:
        if not path.is_file() or path.stat().st_size <= 0:
            raise MediaInfrastructureError("OUTPUT_INVALID", "Output is missing or empty.")
        if phase_callback is not None:
            phase_callback("probing_output")
        probe = self.prober.probe(path)
        video = next((stream for stream in probe.streams if stream.codec_type == "video"), None)
        audio = next((stream for stream in probe.streams if stream.codec_type == "audio"), None)
        if video is None or audio is None:
            raise MediaInfrastructureError("OUTPUT_INVALID", "Output must contain video and audio streams.")
        requirements = (
            (video.codec_name, expected.get("video_codec"), "video codec"),
            (audio.codec_name, expected.get("audio_codec"), "audio codec"),
            (video.width, expected.get("width"), "video width"),
            (video.height, expected.get("height"), "video height"),
            (video.pixel_format, expected.get("pixel_format"), "video pixel format"),
            (
                video.frame_rate,
                expected["frame_rate"],
                "video frame rate",
            ),
            (probe.duration_seconds, "positive", "positive duration"),
            (probe.format_name, "mp4", "MP4 container"),
            (
                audio.sample_rate,
                expected.get("audio_sample_rate"),
                "audio sample rate",
            ),
            (
                audio.channels,
                expected.get("audio_channels"),
                "audio channel count",
            ),
            (
                video.profile,
                expected.get("video_profile"),
                "video profile",
            ),
            (
                audio.profile,
                expected.get("audio_profile"),
                "audio profile",
            ),
            (
                video.color_space,
                expected.get("color_space"),
                "video color space",
            ),
            (
                video.color_transfer,
                expected.get("color_transfer"),
                "video color transfer",
            ),
            (
                video.color_primaries,
                expected.get("color_primaries"),
                "video color primaries",
            ),
        )
        for actual, required, label in requirements:
            valid = self._matches(label, actual, required)
            if not valid:
                raise MediaInfrastructureError(
                    "OUTPUT_INVALID",
                    f"Output {label} check failed.",
                    {
                        "predicate": label,
                        "expected": required,
                        "actual": actual,
                        "probe": self._probe_details(probe),
                    },
                )
        expected_duration = float(expected["duration_seconds"])
        tolerance = float(expected["duration_tolerance_seconds"])
        assert probe.duration_seconds is not None
        if abs(probe.duration_seconds - expected_duration) > tolerance:
            raise MediaInfrastructureError(
                "OUTPUT_INVALID",
                "Output duration is outside declared tolerance.",
                {
                    "predicate": "duration tolerance",
                    "expected": {"duration_seconds": expected_duration, "tolerance_seconds": tolerance},
                    "actual": probe.duration_seconds,
                    "probe": self._probe_details(probe),
                },
            )
        provenance_name = "request" if "request_digest" in expected else "snapshot"
        provenance_value = expected.get("request_digest", expected.get("snapshot_digest"))
        expected_tag = f"wrld_{provenance_name}:{provenance_value}"
        if probe.format_tags.get("comment") != expected_tag:
            raise MediaInfrastructureError("OUTPUT_PROVENANCE_MISMATCH", "Output does not match this snapshot.")

        if expected.get("faststart") and not self._has_faststart(path):
            raise MediaInfrastructureError("OUTPUT_INVALID", "Output is missing fast-start atom ordering.")

        if phase_callback is not None:
            phase_callback("decoding_output")
        ffmpeg = self.toolchain.resolve("ffmpeg")
        args = [
            str(ffmpeg.path), "-hide_banner", "-nostdin", "-v", "error", "-xerror",
            "-i", str(path),
        ]
        if not expected.get("full_decode"):
            args.extend(["-t", str(min(self.decode_seconds, expected_duration))])
        args.extend(["-f", "null", "-"])
        decoded = self.runner.run(
            args,
            timeout_seconds=float(expected.get("decode_timeout_seconds", 15.0)),
            cancel_event=cancel_event,
            heartbeat=heartbeat,
        )
        if decoded.cancelled:
            raise MediaInfrastructureError(
                "PROCESS_CANCELLED", "Output decode verification was cancelled."
            )
        if decoded.timed_out or decoded.returncode != 0:
            raise MediaInfrastructureError(
                "OUTPUT_DECODE_FAILED",
                "Output failed complete decode verification."
                if expected.get("full_decode")
                else "Output failed bounded decode verification.",
                {"stderr_tail": self.runner.sanitize_diagnostic(decoded.stderr_tail)},
            )
        return probe

    @staticmethod
    def _matches(label: str, actual: Any, expected: Any) -> bool:
        if label == "video frame rate":
            return actual is not None and abs(actual - expected) < 0.05
        if label == "positive duration":
            return actual is not None and actual > 0
        if label == "MP4 container":
            return "mp4" in (actual or "")
        if label in {"video profile", "audio profile"}:
            return expected is None or (actual or "").casefold() == str(expected).casefold()
        return expected is None or actual == expected

    @staticmethod
    def _probe_details(probe: MediaProbe) -> dict[str, Any]:
        return {
            "tool_version": probe.tool_version,
            "duration_seconds": probe.duration_seconds,
            "format_name": probe.format_name,
            "format_tags": dict(probe.format_tags),
            "streams": [
                {
                    "index": stream.index,
                    "codec_type": stream.codec_type,
                    "codec_name": stream.codec_name,
                    "profile": stream.profile,
                    "sample_rate": stream.sample_rate,
                    "channels": stream.channels,
                    "width": stream.width,
                    "height": stream.height,
                    "frame_rate": stream.frame_rate,
                    "pixel_format": stream.pixel_format,
                    "color_space": stream.color_space,
                    "color_transfer": stream.color_transfer,
                    "color_primaries": stream.color_primaries,
                }
                for stream in probe.streams
            ],
        }

    @staticmethod
    def _has_faststart(path: Path) -> bool:
        try:
            with path.open("rb") as stream:
                moov_offset: int | None = None
                mdat_offset: int | None = None
                offset = 0
                while True:
                    header = stream.read(8)
                    if len(header) != 8:
                        break
                    size = int.from_bytes(header[:4], "big")
                    kind = header[4:]
                    header_size = 8
                    if size == 1:
                        extended = stream.read(8)
                        if len(extended) != 8:
                            return False
                        size = int.from_bytes(extended, "big")
                        header_size = 16
                    elif size == 0:
                        size = path.stat().st_size - offset
                    if size < header_size:
                        return False
                    if kind == b"moov":
                        moov_offset = offset
                    elif kind == b"mdat":
                        mdat_offset = offset
                    if moov_offset is not None and mdat_offset is not None:
                        return moov_offset < mdat_offset
                    stream.seek(size - header_size, 1)
                    offset += size
        except OSError:
            return False
        return False
