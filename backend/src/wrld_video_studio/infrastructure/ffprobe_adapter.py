from __future__ import annotations

import json
import math
from fractions import Fraction
from pathlib import Path
from typing import Any

from wrld_video_studio.application.ports.media import MediaProber, ProcessRunner
from wrld_video_studio.domain.jobs import MediaProbe, MediaStream
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.infrastructure.media_tools import MediaToolchain


class FFprobeAdapter(MediaProber):
    def __init__(self, toolchain: MediaToolchain, runner: ProcessRunner) -> None:
        self.toolchain = toolchain
        self.runner = runner

    def probe(self, path: Path) -> MediaProbe:
        if not path.is_file():
            raise MediaInfrastructureError("ASSET_NOT_FOUND", "Media input file does not exist.")
        tool = self.toolchain.resolve("ffprobe")
        result = self.runner.run(
            [
                str(tool.path), "-v", "error", "-show_format", "-show_streams",
                "-of", "json", str(path),
            ],
            timeout_seconds=15.0,
        )
        if result.timed_out:
            raise MediaInfrastructureError(
                "PROBE_TIMEOUT",
                "FFprobe exceeded its time limit.",
                {"stderr_tail": self.runner.sanitize_diagnostic(result.stderr_tail)},
            )
        if result.returncode != 0:
            raise MediaInfrastructureError(
                "PROBE_FAILED",
                "FFprobe could not inspect media.",
                {"stderr_tail": self.runner.sanitize_diagnostic(result.stderr_tail)},
            )
        try:
            document = json.loads(
                result.stdout,
                parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
            )
            return self._parse(path, tool.version, document)
        except (ValueError, TypeError, KeyError) as error:
            raise MediaInfrastructureError(
                "PROBE_INVALID",
                "FFprobe returned invalid JSON data.",
                {"stderr_tail": self.runner.sanitize_diagnostic(result.stderr_tail)},
            ) from error

    def _parse(self, path: Path, version: str, document: Any) -> MediaProbe:
        if not isinstance(document, dict):
            raise ValueError("root must be an object")
        raw_streams = document.get("streams")
        if not isinstance(raw_streams, list):
            raise ValueError("streams must be an array")
        streams: list[MediaStream] = []
        for raw in raw_streams:
            if not isinstance(raw, dict):
                raise ValueError("stream must be an object")
            index = self._integer(raw.get("index"))
            codec_type = raw.get("codec_type")
            if index is None or not isinstance(codec_type, str):
                raise ValueError("stream index and codec_type are required")
            time_base = self._fraction(raw.get("time_base"))
            streams.append(
                MediaStream(
                    index=index,
                    codec_type=codec_type,
                    codec_name=raw.get("codec_name") if isinstance(raw.get("codec_name"), str) else None,
                    sample_rate=self._integer(raw.get("sample_rate")),
                    channels=self._integer(raw.get("channels")),
                    width=self._integer(raw.get("width")),
                    height=self._integer(raw.get("height")),
                    frame_rate=self._rational(raw.get("avg_frame_rate")),
                    duration_seconds=self._finite_positive(raw.get("duration")),
                    duration_ts=self._integer(raw.get("duration_ts")),
                    time_base_numerator=(time_base.numerator if time_base is not None else None),
                    time_base_denominator=(time_base.denominator if time_base is not None else None),
                    pixel_format=raw.get("pix_fmt") if isinstance(raw.get("pix_fmt"), str) else None,
                    profile=raw.get("profile") if isinstance(raw.get("profile"), str) else None,
                    color_space=(
                        raw.get("color_space") if isinstance(raw.get("color_space"), str) else None
                    ),
                    color_transfer=(
                        raw.get("color_transfer")
                        if isinstance(raw.get("color_transfer"), str)
                        else None
                    ),
                    color_primaries=(
                        raw.get("color_primaries")
                        if isinstance(raw.get("color_primaries"), str)
                        else None
                    ),
                )
            )
        raw_format = document.get("format") or {}
        if not isinstance(raw_format, dict):
            raise ValueError("format must be an object")
        duration = self._finite_positive(raw_format.get("duration"))
        if duration is None:
            durations = [stream.duration_seconds for stream in streams if stream.duration_seconds]
            duration = max(durations) if durations else None
        tags = raw_format.get("tags") or {}
        comment = tags.get("comment") if isinstance(tags, dict) else None
        format_name = raw_format.get("format_name")
        return MediaProbe(
            source_path=str(path.resolve()),
            tool_version=version,
            duration_seconds=duration,
            streams=tuple(streams),
            format_name=(format_name if isinstance(format_name, str) else None),
            format_tags={"comment": comment} if isinstance(comment, str) else {},
        )

    @staticmethod
    def _integer(value: Any) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None

    @staticmethod
    def _finite_positive(value: Any) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) and parsed > 0 else None

    @staticmethod
    def _rational(value: Any) -> float | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = float(Fraction(value))
        except (ValueError, ZeroDivisionError, OverflowError):
            return None
        return parsed if math.isfinite(parsed) and parsed > 0 else None

    @staticmethod
    def _fraction(value: Any) -> Fraction | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = Fraction(value)
        except (ValueError, ZeroDivisionError, OverflowError):
            return None
        return parsed if parsed > 0 else None
