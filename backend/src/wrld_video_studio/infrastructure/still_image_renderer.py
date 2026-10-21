from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from wrld_video_studio.application.ports.media import ProcessRunner
from wrld_video_studio.application.ports.still_images import (
    STILL_OUTPUT_MAX_DIMENSION,
    STILL_RENDER_REQUEST_VERSION,
    STILL_RENDER_RESULT_VERSION,
    STILL_RENDERER_VERSION,
    StillImageRenderer,
    StillRenderRequest,
    StillRenderResult,
)
from wrld_video_studio.domain.color_resolution import (
    ColorResolution,
    MAX_INTENSITY,
    OUTPUT_CONTRACT_VERSION,
    PRESET_HEX_BY_ID,
    PRESET_MAPPING_VERSION,
    RESOLVER_VERSION,
)
from wrld_video_studio.domain.color_transform import TRANSFORM_VERSION
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.infrastructure.media_tools import MediaToolchain


MAX_INPUT_BYTES = 40 * 1024 * 1024
MAX_INPUT_SIDE = 10_000
MAX_INPUT_PIXELS = 40_000_000
SUPPORTED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
SUPPORTED_CODECS = frozenset({"mjpeg", "png", "webp"})
PROCESS_TIMEOUT_SECONDS = 30.0
PROBE_TIMEOUT_SECONDS = 15.0
REQUIRED_FFMPEG_FILTERS = frozenset(
    {
        "alphaextract",
        "alphamerge",
        "format",
        "geq",
        "hflip",
        "scale",
        "split",
        "transpose",
        "vflip",
        "zscale",
    }
)
REQUIRED_FFMPEG_ENCODERS = frozenset({"png"})
_HEX_PATTERN = re.compile(r"^#[0-9A-F]{6}$")
_SRGB_TRANSFER_TAGS = {None, "unknown", "iec61966-2-1"}
_SUPPORTED_PRIMARIES = {None, "unknown", "bt709"}
_SUPPORTED_INPUT_COLORSPACES = {None, "unknown", "gbr", "rgb", "bt470bg", "smpte170m", "bt709"}


@dataclass(frozen=True, slots=True)
class _ImageInfo:
    codec: str
    width: int
    height: int
    pixel_format: str
    frame_count: int
    exif_orientation: int
    color_primaries: str | None
    color_transfer: str | None
    color_space: str | None


class FFmpegStillImageRenderer(StillImageRenderer):
    """Authoritative still renderer, deliberately separate from the WU2 video worker."""

    def __init__(
        self,
        toolchain: MediaToolchain,
        runner: ProcessRunner,
        output_root: str | Path,
        timeout_seconds: float = PROCESS_TIMEOUT_SECONDS,
    ) -> None:
        if (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("Still render timeout must be a positive finite number.")
        self.toolchain = toolchain
        self.runner = runner
        self.output_root = Path(output_root).resolve()
        self.timeout_seconds = float(timeout_seconds)
        self.output_root.mkdir(parents=True, exist_ok=True)

    def render(self, request: StillRenderRequest, cancel_event: Any = None) -> StillRenderResult:
        self._validate_request(request)
        self._raise_if_cancelled(cancel_event)
        source_path = Path(request.source_path).resolve(strict=False)
        if not source_path.is_file():
            raise MediaInfrastructureError("ASSET_NOT_FOUND", "Still image input does not exist.")
        try:
            input_size = source_path.stat().st_size
        except OSError as error:
            raise MediaInfrastructureError("IMAGE_READ_FAILED", "Could not inspect still image input.") from error
        if input_size == 0:
            raise MediaInfrastructureError("IMAGE_UNSUPPORTED_OR_CORRUPT", "Still image input is empty.")
        if input_size > MAX_INPUT_BYTES:
            raise MediaInfrastructureError("IMAGE_TOO_LARGE", "Still image exceeds the 40 MiB input limit.")
        if source_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise MediaInfrastructureError("UNSUPPORTED_IMAGE_FORMAT", "Only JPEG, PNG, and WebP still images are supported.")
        orientation, has_unsupported_profile = _read_image_metadata(source_path)
        if has_unsupported_profile:
            raise MediaInfrastructureError(
                "IMAGE_COLOR_PROFILE_UNSUPPORTED", "Embedded ICC or non-sRGB PNG color profiles are not supported."
            )

        output_path = self._resolve_output(request.output_relative_path)
        if os.path.normcase(str(output_path)) == os.path.normcase(str(source_path)):
            raise MediaInfrastructureError("INVALID_OUTPUT_PATH", "Output must not overwrite the source image.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path = self._resolve_output(request.output_relative_path)
        if output_path.exists():
            raise MediaInfrastructureError("OUTPUT_COLLISION", "Still image output already exists.")

        self._raise_if_cancelled(cancel_event)
        ffmpeg = self.toolchain.resolve("ffmpeg")
        self._raise_if_cancelled(cancel_event)
        self._validate_ffmpeg_capabilities(ffmpeg.path, cancel_event)
        ffprobe = self.toolchain.resolve("ffprobe")
        self._raise_if_cancelled(cancel_event)
        source_info = self._probe_image(ffprobe.path, source_path, cancel_event)
        self._validate_source_color_metadata(source_info)
        expected_codec = {".jpg": "mjpeg", ".jpeg": "mjpeg", ".png": "png", ".webp": "webp"}[
            source_path.suffix.lower()
        ]
        if source_info.codec != expected_codec:
            raise MediaInfrastructureError(
                "IMAGE_EXTENSION_MISMATCH", "Image container does not match its filename extension."
            )
        source_info = _ImageInfo(
            codec=source_info.codec,
            width=source_info.width,
            height=source_info.height,
            pixel_format=source_info.pixel_format,
            frame_count=0,
            exif_orientation=orientation,
            color_primaries=source_info.color_primaries,
            color_transfer=source_info.color_transfer,
            color_space=source_info.color_space,
        )
        oriented_width, oriented_height = self._oriented_size(source_info)
        if oriented_width > MAX_INPUT_SIDE or oriented_height > MAX_INPUT_SIDE:
            raise MediaInfrastructureError("IMAGE_DIMENSION_LIMIT", "Still image side exceeds 10,000 pixels.")
        if oriented_width * oriented_height > MAX_INPUT_PIXELS:
            raise MediaInfrastructureError("IMAGE_PIXEL_LIMIT", "Still image exceeds 40 megapixels.")
        frame_count = self._count_image_frames(ffprobe.path, source_path, cancel_event)
        if frame_count != 1:
            raise MediaInfrastructureError("ANIMATED_IMAGE_UNSUPPORTED", "Animated image input is not supported.")
        source_info = _ImageInfo(
            codec=source_info.codec,
            width=source_info.width,
            height=source_info.height,
            pixel_format=source_info.pixel_format,
            frame_count=frame_count,
            exif_orientation=source_info.exif_orientation,
            color_primaries=source_info.color_primaries,
            color_transfer=source_info.color_transfer,
            color_space=source_info.color_space,
        )
        width, height = _scaled_dimensions(oriented_width, oriented_height, STILL_OUTPUT_MAX_DIMENSION)
        source_digest = _sha256_file(source_path)
        temporary_path = self._create_temporary_output(output_path)
        sanitized_command: tuple[str, ...] = ()
        primary_error: MediaInfrastructureError | None = None
        try:
            command = self._build_ffmpeg_argv(
                ffmpeg.path, source_path, temporary_path, request, source_info.exif_orientation, width, height
            )
            execution = self.runner.run(
                command,
                timeout_seconds=self.timeout_seconds,
                cancel_event=cancel_event,
            )
            sanitized_command = execution.sanitized_argv
            if execution.cancelled:
                raise MediaInfrastructureError("PROCESS_CANCELLED", "Still image rendering was cancelled.")
            if execution.timed_out:
                raise MediaInfrastructureError(
                    "PROCESS_TIMEOUT",
                    "FFmpeg still rendering exceeded its time limit.",
                    {"stderr_tail": self.runner.sanitize_diagnostic(execution.stderr_tail)},
                )
            if execution.returncode != 0:
                raise MediaInfrastructureError(
                    "IMAGE_RENDER_FAILED",
                    "FFmpeg could not render the still image.",
                    {
                        "stderr_tail": self.runner.sanitize_diagnostic(execution.stderr_tail),
                        "command": list(sanitized_command),
                    },
                )
            if not temporary_path.is_file() or temporary_path.stat().st_size == 0:
                raise MediaInfrastructureError("OUTPUT_INVALID", "FFmpeg did not produce a PNG still.")
            _strip_png_exif(temporary_path)
            self._verify_png(
                ffprobe.path,
                ffmpeg.path,
                temporary_path,
                width,
                height,
                cancel_event,
            )
            if _sha256_file(source_path) != source_digest:
                raise MediaInfrastructureError("SOURCE_CHANGED", "Source image changed during still rendering.")
            self._publish_no_replace(temporary_path, output_path)
        except MediaInfrastructureError as error:
            primary_error = error
            raise
        except OSError as error:
            primary_error = MediaInfrastructureError(
                "STORAGE_ERROR", "Still image output could not be published safely."
            )
            raise primary_error from error
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                if primary_error is not None:
                    primary_error.details["cleanup_error"] = "Owned temporary output could not be removed."
                else:
                    raise MediaInfrastructureError(
                        "STORAGE_ERROR",
                        "Rendered output was published but staging cleanup failed.",
                        {"artifact_published": True},
                        commit_state="committed",
                    ) from cleanup_error

        return StillRenderResult(
            contract_version=STILL_RENDER_RESULT_VERSION,
            artifact_path=output_path,
            source_sha256=source_digest,
            treatment=request.resolution,
            width=width,
            height=height,
            output_format="png",
            renderer_version=request.renderer_version,
            transform_version=request.transform_version,
            ffmpeg_version=ffmpeg.version,
            input_pixel_format=source_info.pixel_format,
            output_pixel_format="rgba",
            orientation=f"EXIF orientation {source_info.exif_orientation} normalized explicitly",
            sanitized_command=sanitized_command,
        )

    def _validate_request(self, request: StillRenderRequest) -> None:
        if not isinstance(request, StillRenderRequest):
            raise MediaInfrastructureError("INVALID_RENDER_REQUEST", "Still render request has an unsupported type.")
        if not isinstance(request.source_path, (str, Path)):
            raise MediaInfrastructureError("INVALID_RENDER_REQUEST", "Source path must be a path or string.")
        if type(request.output_relative_path) is not str or not request.output_relative_path:
            raise MediaInfrastructureError("INVALID_RENDER_REQUEST", "Output relative path must be non-empty text.")
        try:
            str(request.source_path).encode("utf-8", errors="strict")
            request.output_relative_path.encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise MediaInfrastructureError("INVALID_RENDER_REQUEST", "Render paths must be valid Unicode.") from error
        if request.contract_version != STILL_RENDER_REQUEST_VERSION:
            raise MediaInfrastructureError("UNSUPPORTED_RENDER_CONTRACT", "Still render request version is unsupported.")
        if request.renderer_version != STILL_RENDERER_VERSION:
            raise MediaInfrastructureError("UNSUPPORTED_RENDERER_VERSION", "Still renderer version is unsupported.")
        if request.transform_version != TRANSFORM_VERSION:
            raise MediaInfrastructureError("UNSUPPORTED_TRANSFORM_VERSION", "Color transform version is unsupported.")
        self._validate_resolution(request.resolution)
        if not request.output_relative_path.endswith(".png"):
            raise MediaInfrastructureError("INVALID_OUTPUT_FORMAT", "Authoritative still output must use a .png path.")

    @staticmethod
    def _validate_resolution(resolution: ColorResolution) -> None:
        if not isinstance(resolution, ColorResolution) or resolution.contract_version != OUTPUT_CONTRACT_VERSION:
            raise MediaInfrastructureError("INVALID_COLOR_RESOLUTION", "A Phase 1 color resolution result is required.")
        if (
            resolution.resolver_version != RESOLVER_VERSION
            or resolution.preset_mapping_version != PRESET_MAPPING_VERSION
            or
            resolution.mode not in {"auto", "preset", "custom"}
            or type(resolution.intensity) not in (int, float)
            or not math.isfinite(resolution.intensity)
            or not 0.0 <= resolution.intensity <= MAX_INTENSITY
            or type(resolution.input_fingerprint) is not str
            or not re.fullmatch(r"[a-f0-9]{64}", resolution.input_fingerprint)
        ):
            raise MediaInfrastructureError("INVALID_COLOR_RESOLUTION", "Color resolution fields are invalid.")
        if resolution.resolved_hex is not None and (
            type(resolution.resolved_hex) is not str or not _HEX_PATTERN.fullmatch(resolution.resolved_hex)
        ):
            raise MediaInfrastructureError("INVALID_COLOR_RESOLUTION", "Resolved HEX must be uppercase six-digit sRGB.")
        if resolution.preset_id is not None and (
            type(resolution.preset_id) is not str or resolution.preset_id not in PRESET_HEX_BY_ID
        ):
            raise MediaInfrastructureError("INVALID_COLOR_RESOLUTION", "Resolved preset identifier is unsupported.")
        if resolution.resolved_hex is None and resolution.intensity != 0.0:
            raise MediaInfrastructureError("INVALID_COLOR_RESOLUTION", "Untreated resolution must have zero intensity.")
        if resolution.preset_id == "original" and (resolution.resolved_hex is not None or resolution.intensity != 0.0):
            raise MediaInfrastructureError("INVALID_COLOR_RESOLUTION", "Original preset must be untreated.")
        if resolution.mode == "custom":
            valid = resolution.preset_id is None and resolution.resolved_hex is not None
            expected = ("user_selection", "explicit_custom")
        elif resolution.mode == "preset":
            expected_hex = PRESET_HEX_BY_ID.get(resolution.preset_id) if resolution.preset_id else None
            valid = resolution.preset_id is not None and resolution.resolved_hex == expected_hex
            expected = ("user_selection", "explicit_original" if resolution.preset_id == "original" else "explicit_preset")
        else:
            if resolution.source == "track_preference":
                valid = resolution.preset_id is None and resolution.resolved_hex is not None
                expected = ("track_preference", "explicit_track_preference")
            elif resolution.source == "album_palette":
                valid = resolution.preset_id is None and resolution.resolved_hex is not None
                expected = ("album_palette", "first_palette_entry")
            elif resolution.source == "album_default":
                expected_hex = PRESET_HEX_BY_ID.get(resolution.preset_id) if resolution.preset_id else None
                valid = resolution.preset_id is not None and resolution.resolved_hex == expected_hex
                expected = ("album_default", "album_default_original" if resolution.preset_id == "original" else "album_default_preset")
            elif resolution.source == "fallback":
                valid = resolution.preset_id == "original" and resolution.resolved_hex is None and resolution.intensity == 0.0
                expected = ("fallback", "no_usable_auto_color")
            else:
                valid, expected = False, ("", "")
        if not valid or (resolution.source, resolution.reason) != expected:
            raise MediaInfrastructureError("INVALID_COLOR_RESOLUTION", "Color resolution mode and provenance are inconsistent.")

    def _resolve_output(self, relative_path: str) -> Path:
        path = Path(relative_path)
        windows_path = PureWindowsPath(relative_path)
        if (
            path.is_absolute()
            or path.drive
            or windows_path.is_absolute()
            or windows_path.drive
            or ".." in path.parts
            or ".." in windows_path.parts
            or not relative_path
        ):
            raise MediaInfrastructureError("INVALID_OUTPUT_PATH", "Still output path must be relative and contained.")
        candidate = (self.output_root / path).resolve(strict=False)
        try:
            relative = candidate.relative_to(self.output_root)
        except ValueError as error:
            raise MediaInfrastructureError("INVALID_OUTPUT_PATH", "Still output path escapes configured output root.") from error
        if not relative.parts or relative.parts[0].casefold() in {".wrld-staging", ".wrld-promotions"}:
            raise MediaInfrastructureError("INVALID_OUTPUT_PATH", "Still output targets a reserved path.")
        return candidate

    @staticmethod
    def _raise_if_cancelled(cancel_event: Any) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise MediaInfrastructureError("PROCESS_CANCELLED", "Still image rendering was cancelled.")

    def _validate_ffmpeg_capabilities(self, ffmpeg_path: Path, cancel_event: Any) -> None:
        listings: dict[str, set[str]] = {}
        for label, flag in (("filters", "-filters"), ("encoders", "-encoders")):
            result = self.runner.run(
                [str(ffmpeg_path), "-hide_banner", flag],
                timeout_seconds=PROBE_TIMEOUT_SECONDS,
                cancel_event=cancel_event,
            )
            if result.cancelled:
                raise MediaInfrastructureError("PROCESS_CANCELLED", "Still image rendering was cancelled.")
            if result.timed_out:
                raise MediaInfrastructureError(
                    "MEDIA_CAPABILITY_PROBE_TIMEOUT", "FFmpeg capability inspection exceeded its time limit."
                )
            if result.returncode != 0:
                raise MediaInfrastructureError(
                    "MEDIA_CAPABILITY_PROBE_FAILED",
                    "FFmpeg capabilities could not be inspected.",
                    {"stderr_tail": self.runner.sanitize_diagnostic(result.stderr_tail)},
                )
            listings[label] = {
                parts[1]
                for line in result.stdout.splitlines()
                if len(parts := line.split()) >= 2
            }
        missing_filters = sorted(REQUIRED_FFMPEG_FILTERS - listings["filters"])
        missing_encoders = sorted(REQUIRED_FFMPEG_ENCODERS - listings["encoders"])
        if missing_filters or missing_encoders:
            raise MediaInfrastructureError(
                "MEDIA_CAPABILITY_MISSING",
                "FFmpeg lacks required still-render capabilities.",
                {"missing_filters": missing_filters, "missing_encoders": missing_encoders},
            )

    def _probe_image(self, ffprobe_path: Path, path: Path, cancel_event: Any = None) -> _ImageInfo:
        result = self.runner.run(
            [
                str(ffprobe_path), "-v", "error", "-select_streams", "v:0",
                "-show_entries",
                "stream=codec_name,width,height,pix_fmt,color_primaries,color_transfer,color_space:stream_tags=rotate:stream_side_data=rotation",
                "-of", "json", str(path),
            ],
            timeout_seconds=PROBE_TIMEOUT_SECONDS,
            cancel_event=cancel_event,
        )
        if result.cancelled:
            raise MediaInfrastructureError("PROCESS_CANCELLED", "Still image rendering was cancelled.")
        if result.timed_out:
            raise MediaInfrastructureError("IMAGE_PROBE_TIMEOUT", "FFprobe image inspection exceeded its time limit.")
        if result.returncode != 0:
            raise MediaInfrastructureError(
                "IMAGE_UNDECODABLE",
                "FFprobe could not inspect the still image.",
                {"stderr_tail": self.runner.sanitize_diagnostic(result.stderr_tail)},
            )
        try:
            data = json.loads(result.stdout, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
            streams = data["streams"]
            stream = streams[0]
            if len(streams) != 1 or not isinstance(stream, dict):
                raise ValueError("expected exactly one image stream")
            codec = stream.get("codec_name")
            width, height = stream.get("width"), stream.get("height")
            pixel_format = stream.get("pix_fmt")
            if codec == "webp_anim":
                raise MediaInfrastructureError(
                    "ANIMATED_IMAGE_UNSUPPORTED", "Animated image input is not supported."
                )
            if codec not in SUPPORTED_CODECS or type(width) is not int or type(height) is not int:
                raise ValueError("unsupported stream")
            if type(pixel_format) is not str or width <= 0 or height <= 0:
                raise ValueError("invalid image stream")
            return _ImageInfo(
                codec=codec,
                width=width,
                height=height,
                pixel_format=pixel_format,
                frame_count=0,
                exif_orientation=1,
                color_primaries=stream.get("color_primaries"),
                color_transfer=stream.get("color_transfer"),
                color_space=stream.get("color_space"),
            )
        except (ValueError, TypeError, KeyError, IndexError) as error:
            raise MediaInfrastructureError(
                "IMAGE_UNSUPPORTED_OR_CORRUPT", "Input must be one decodable JPEG, PNG, or WebP still."
            ) from error

    def _count_image_frames(self, ffprobe_path: Path, path: Path, cancel_event: Any = None) -> int:
        result = self.runner.run(
            [
                str(ffprobe_path), "-v", "error", "-count_frames", "-select_streams", "v:0",
                "-show_entries", "stream=nb_read_frames", "-of", "json", str(path),
            ],
            timeout_seconds=PROBE_TIMEOUT_SECONDS,
            cancel_event=cancel_event,
        )
        if result.cancelled:
            raise MediaInfrastructureError("PROCESS_CANCELLED", "Still image rendering was cancelled.")
        if result.timed_out:
            raise MediaInfrastructureError("IMAGE_PROBE_TIMEOUT", "FFprobe frame counting exceeded its time limit.")
        if result.returncode != 0:
            raise MediaInfrastructureError(
                "IMAGE_UNDECODABLE",
                "FFprobe could not count still image frames.",
                {"stderr_tail": self.runner.sanitize_diagnostic(result.stderr_tail)},
            )
        try:
            data = json.loads(result.stdout, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
            streams = data["streams"]
            if len(streams) != 1:
                raise ValueError("expected exactly one image stream")
            frame_count = int(streams[0]["nb_read_frames"])
            if frame_count < 1:
                raise ValueError("expected at least one frame")
            return frame_count
        except (ValueError, TypeError, KeyError, IndexError) as error:
            raise MediaInfrastructureError(
                "IMAGE_UNSUPPORTED_OR_CORRUPT", "Image frame count could not be verified."
            ) from error

    @staticmethod
    def _validate_source_color_metadata(info: _ImageInfo) -> None:
        if info.color_transfer not in _SRGB_TRANSFER_TAGS:
            raise MediaInfrastructureError(
                "IMAGE_COLOR_PROFILE_UNSUPPORTED", "Only sRGB/untagged sRGB transfer input is supported."
            )
        if info.color_primaries not in _SUPPORTED_PRIMARIES or info.color_space not in _SUPPORTED_INPUT_COLORSPACES:
            raise MediaInfrastructureError(
                "IMAGE_COLOR_PROFILE_UNSUPPORTED", "Image primaries or color space are not supported as sRGB."
            )

    @staticmethod
    def _oriented_size(info: _ImageInfo) -> tuple[int, int]:
        if info.exif_orientation in {5, 6, 7, 8}:
            return info.height, info.width
        return info.width, info.height

    def _create_temporary_output(self, output_path: Path) -> Path:
        try:
            descriptor, name = tempfile.mkstemp(
                prefix=f".{output_path.stem}.", suffix=".partial.png", dir=output_path.parent
            )
            os.close(descriptor)
            return Path(name)
        except OSError as error:
            raise MediaInfrastructureError("STORAGE_ERROR", "Could not create still render staging file.") from error

    def _build_ffmpeg_argv(
        self,
        ffmpeg_path: Path,
        source_path: Path,
        temporary_path: Path,
        request: StillRenderRequest,
        exif_orientation: int,
        width: int,
        height: int,
    ) -> list[str]:
        treatment = request.resolution
        if treatment.resolved_hex in {None, "#000000"} or treatment.intensity == 0.0:
            color_pipeline = (
                f"zscale=w={width}:h={height}:filter=lanczos:dither=none:"
                "rangein=full:range=full,format=rgb24"
            )
        else:
            color_pipeline = _treatment_filter_graph(treatment.resolved_hex, treatment.intensity, width, height)
        filter_graph = _alpha_safe_filter_graph(color_pipeline, width, height)
        return [
            str(ffmpeg_path), "-hide_banner", "-nostdin", "-v", "error", "-xerror",
            "-threads", "1", "-noautorotate", "-i", str(source_path),
            "-map", "0:v:0", "-an", "-sn", "-dn", "-vf",
            _orientation_filter(exif_orientation, filter_graph),
            "-frames:v", "1", "-map_metadata", "-1", "-c:v", "png", "-pix_fmt", "rgba",
            "-compression_level", "9", "-pred", "mixed",
            "-color_primaries", "bt709", "-color_trc", "iec61966-2-1", "-colorspace", "rgb",
            "-f", "image2", "-y", str(temporary_path),
        ]

    def _verify_png(
        self,
        ffprobe_path: Path,
        ffmpeg_path: Path,
        path: Path,
        expected_width: int,
        expected_height: int,
        cancel_event: Any = None,
    ) -> None:
        if path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise MediaInfrastructureError("OUTPUT_INVALID", "FFmpeg output does not have a PNG signature.")
        probe = self.runner.run(
            [
                str(ffprobe_path), "-v", "error", "-count_frames", "-select_streams", "v:0",
                "-show_entries", "stream=codec_name,width,height,pix_fmt,nb_read_frames,color_primaries,color_transfer,color_space",
                "-of", "json", str(path),
            ],
            timeout_seconds=PROBE_TIMEOUT_SECONDS,
            cancel_event=cancel_event,
        )
        if probe.cancelled:
            raise MediaInfrastructureError("PROCESS_CANCELLED", "Still image rendering was cancelled.")
        try:
            data = json.loads(probe.stdout, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
            stream = data["streams"][0]
            if (
                probe.returncode != 0
                or probe.timed_out
                or stream.get("codec_name") != "png"
                or stream.get("width") != expected_width
                or stream.get("height") != expected_height
                or stream.get("pix_fmt") not in {"rgba", "rgb24"}
                or int(stream.get("nb_read_frames", "1")) != 1
                or stream.get("color_transfer") not in {"iec61966-2-1", None}
            ):
                raise ValueError("output metadata mismatch")
        except (ValueError, TypeError, KeyError, IndexError) as error:
            raise MediaInfrastructureError("OUTPUT_INVALID", "Rendered PNG metadata failed verification.") from error
        decoded = self.runner.run(
            [
                str(ffmpeg_path), "-hide_banner", "-nostdin", "-v", "error", "-xerror",
                "-threads", "1", "-i", str(path), "-frames:v", "1", "-f", "null", "-",
            ],
            timeout_seconds=self.timeout_seconds,
            cancel_event=cancel_event,
        )
        if decoded.cancelled:
            raise MediaInfrastructureError("PROCESS_CANCELLED", "Still image rendering was cancelled.")
        if decoded.timed_out or decoded.returncode != 0:
            raise MediaInfrastructureError(
                "OUTPUT_INVALID", "Rendered PNG failed an independent FFmpeg decode check.",
                {"stderr_tail": self.runner.sanitize_diagnostic(decoded.stderr_tail)},
            )

    @staticmethod
    def _publish_no_replace(staged: Path, destination: Path) -> None:
        try:
            with staged.open("rb+") as stream:
                os.fsync(stream.fileno())
            os.link(staged, destination)
        except FileExistsError as error:
            raise MediaInfrastructureError("OUTPUT_COLLISION", "Still image output already exists.") from error
        except OSError as error:
            raise MediaInfrastructureError(
                "STORAGE_ERROR", "PNG staging could not be durably flushed or published without replacement."
            ) from error


def _scaled_dimensions(width: int, height: int, max_dimension: int) -> tuple[int, int]:
    if width <= 0 or height <= 0 or max_dimension <= 0:
        raise MediaInfrastructureError("IMAGE_DIMENSIONS_INVALID", "Image dimensions must be positive.")
    if width <= max_dimension and height <= max_dimension:
        return width, height
    scale = max_dimension / max(width, height)
    return max(1, math.floor(width * scale + 0.5)), max(1, math.floor(height * scale + 0.5))


def _orientation_filter(orientation: int, color_pipeline: str) -> str:
    transforms = {
        1: "",
        2: "hflip,",
        3: "hflip,vflip,",
        4: "vflip,",
        5: "transpose=clock,hflip,",
        6: "transpose=clock,",
        7: "transpose=cclock,hflip,",
        8: "transpose=cclock,",
    }
    if orientation not in transforms:
        raise MediaInfrastructureError("IMAGE_ORIENTATION_UNSUPPORTED", "EXIF orientation is unsupported.")
    prefix = transforms[orientation]
    if not prefix:
        return color_pipeline
    return f"{prefix}{color_pipeline}"


def _read_image_metadata(path: Path) -> tuple[int, bool]:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise MediaInfrastructureError("IMAGE_READ_FAILED", "Could not read image metadata.") from error
    if data.startswith(b"\xff\xd8"):
        return _jpeg_metadata(data)
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return _png_metadata(data)
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return _webp_metadata(data)
    raise MediaInfrastructureError("IMAGE_UNSUPPORTED_OR_CORRUPT", "Image container signature is unsupported.")


def _strip_png_exif(path: Path) -> None:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise MediaInfrastructureError("OUTPUT_INVALID", "Rendered PNG metadata could not be read.") from error
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise MediaInfrastructureError("OUTPUT_INVALID", "Rendered output does not have a PNG signature.")
    output = bytearray(data[:8])
    offset = 8
    found_iend = False
    removed_exif = False
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise MediaInfrastructureError("OUTPUT_INVALID", "Rendered PNG contains a truncated chunk.")
        if chunk_type == b"eXIf":
            removed_exif = True
        else:
            output.extend(data[offset:end])
        offset = end
        if chunk_type == b"IEND":
            found_iend = True
            break
    if not found_iend:
        raise MediaInfrastructureError("OUTPUT_INVALID", "Rendered PNG does not contain a complete IEND chunk.")
    if removed_exif:
        try:
            path.write_bytes(output)
        except OSError as error:
            raise MediaInfrastructureError("STORAGE_ERROR", "Rendered PNG metadata could not be normalized.") from error


def _jpeg_metadata(data: bytes) -> tuple[int, bool]:
    offset = 2
    orientation = 1
    has_profile = False
    while offset + 4 <= len(data) and data[offset] == 0xFF:
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in {0xD9, 0xDA}:
            break
        if offset + 2 > len(data):
            break
        segment_length = int.from_bytes(data[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(data):
            raise MediaInfrastructureError("IMAGE_UNSUPPORTED_OR_CORRUPT", "JPEG metadata segment is malformed.")
        payload = data[offset + 2 : offset + segment_length]
        if marker == 0xE1 and payload.startswith(b"Exif\x00\x00"):
            orientation = _parse_tiff_orientation(payload[6:])
        if marker == 0xE2 and payload.startswith(b"ICC_PROFILE\x00"):
            has_profile = True
        offset += segment_length
    return orientation, has_profile


def _png_metadata(data: bytes) -> tuple[int, bool]:
    offset = 8
    orientation = 1
    has_icc_profile = False
    has_srgb_chunk = False
    has_explicit_gamma_or_chromaticity = False
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise MediaInfrastructureError("IMAGE_UNSUPPORTED_OR_CORRUPT", "PNG chunk is truncated.")
        payload = data[offset + 8 : offset + 8 + length]
        if chunk_type == b"eXIf":
            orientation = _parse_tiff_orientation(payload)
        elif chunk_type == b"iCCP":
            has_icc_profile = True
        elif chunk_type == b"sRGB":
            has_srgb_chunk = True
        elif chunk_type in {b"gAMA", b"cHRM"}:
            has_explicit_gamma_or_chromaticity = True
        offset = end
        if chunk_type == b"IEND":
            break
    return orientation, has_icc_profile or (
        has_explicit_gamma_or_chromaticity and not has_srgb_chunk
    )


def _webp_metadata(data: bytes) -> tuple[int, bool]:
    offset = 12
    orientation = 1
    has_profile = False
    has_animation_flag = False
    has_animation_control = False
    has_animation_frame = False
    while offset + 8 <= len(data):
        chunk_type = data[offset : offset + 4]
        length = int.from_bytes(data[offset + 4 : offset + 8], "little")
        end = offset + 8 + length
        if end > len(data):
            raise MediaInfrastructureError("IMAGE_UNSUPPORTED_OR_CORRUPT", "WebP chunk is truncated.")
        payload = data[offset + 8 : end]
        if chunk_type == b"VP8X" and payload:
            has_animation_flag = bool(payload[0] & 0x02)
        elif chunk_type == b"ANIM":
            has_animation_control = True
        elif chunk_type == b"ANMF":
            has_animation_frame = True
        elif chunk_type == b"EXIF":
            if payload.startswith(b"Exif\x00\x00"):
                payload = payload[6:]
            orientation = _parse_tiff_orientation(payload)
        elif chunk_type == b"ICCP":
            has_profile = True
        offset = end + (length & 1)
    if has_animation_flag and has_animation_control and has_animation_frame:
        raise MediaInfrastructureError(
            "ANIMATED_IMAGE_UNSUPPORTED", "Animated image input is not supported."
        )
    return orientation, has_profile


def _parse_tiff_orientation(data: bytes) -> int:
    try:
        if len(data) < 8 or data[:2] not in {b"II", b"MM"}:
            return 1
        byte_order = "little" if data[:2] == b"II" else "big"
        if int.from_bytes(data[2:4], byte_order) != 42:
            return 1
        directory_offset = int.from_bytes(data[4:8], byte_order)
        entry_count = int.from_bytes(data[directory_offset : directory_offset + 2], byte_order)
        for index in range(entry_count):
            entry_offset = directory_offset + 2 + index * 12
            entry = data[entry_offset : entry_offset + 12]
            if len(entry) != 12:
                return 1
            tag = int.from_bytes(entry[:2], byte_order)
            field_type = int.from_bytes(entry[2:4], byte_order)
            count = int.from_bytes(entry[4:8], byte_order)
            if tag == 0x0112 and field_type == 3 and count == 1:
                value = int.from_bytes(entry[8:10], byte_order)
                if value not in range(1, 9):
                    raise MediaInfrastructureError("IMAGE_ORIENTATION_UNSUPPORTED", "EXIF orientation must be 1 through 8.")
                return value
    except (IndexError, OverflowError, ValueError) as error:
        if isinstance(error, MediaInfrastructureError):
            raise
        raise MediaInfrastructureError("IMAGE_UNSUPPORTED_OR_CORRUPT", "EXIF orientation metadata is malformed.") from error
    return 1


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise MediaInfrastructureError("IMAGE_READ_FAILED", "Could not hash source image.") from error
    return digest.hexdigest()


def _treatment_filter_graph(hex_color: str, intensity: float, width: int, height: int) -> str:
    if not _HEX_PATTERN.fullmatch(hex_color):
        raise MediaInfrastructureError("INVALID_COLOR_RESOLUTION", "Treatment HEX must be uppercase sRGB.")
    if not math.isfinite(intensity) or not 0.0 < intensity <= MAX_INTENSITY:
        raise MediaInfrastructureError("INVALID_COLOR_RESOLUTION", "Treated intensity must be in (0, 0.6].")
    target = tuple(int(hex_color[offset : offset + 2], 16) / 255.0 for offset in (1, 3, 5))
    target_linear = tuple(_srgb_component_to_linear(value) for value in target)
    target_luminance = 0.2126 * target_linear[0] + 0.7152 * target_linear[1] + 0.0722 * target_linear[2]
    if target_luminance == 0.0:
        return (
            f"zscale=w={width}:h={height}:filter=lanczos:dither=none:"
            "rangein=full:range=full,format=rgb24"
        )
    target_chroma = tuple(channel / target_luminance for channel in target_linear)
    source_red, source_green, source_blue = "r(X,Y)", "g(X,Y)", "b(X,Y)"
    luminance = f"(0.2126*{source_red}+0.7152*{source_green}+0.0722*{source_blue})"
    intensity_text = format(intensity, ".17g")
    channels = []
    for source_channel, target_channel in zip((source_red, source_green, source_blue), target_chroma):
        channels.append(
            f"((1-{intensity_text})*{source_channel}+{intensity_text}*{luminance}*{format(target_channel, '.17g')})"
        )
    differences = [f"({candidate}-{luminance})" for candidate in channels]
    gamut_terms = ["1"]
    for difference in differences:
        gamut_terms.append(f"if(gt({difference},0),(1-{luminance})/{difference},1)")
        gamut_terms.append(f"if(lt({difference},0),{luminance}/(-{difference}),1)")
    gamut_scale = f"max(0,{_nested_min(gamut_terms)})"
    output_channels = [
        f"min(1,max(0,{luminance}+{gamut_scale}*{difference}))"
        for difference in differences
    ]
    return (
        "format=rgb24,"
        f"zscale=transferin=iec61966-2-1:transfer=linear:matrixin=gbr:matrix=gbr:primariesin=bt709:primaries=bt709:rangein=full:range=full:w={width}:h={height}:filter=lanczos:dither=none,"
        "format=gbrpf32le,"
        f"geq=r='{output_channels[0]}':g='{output_channels[1]}':b='{output_channels[2]}':interpolation=nearest,"
        "zscale=transferin=linear:transfer=iec61966-2-1:matrixin=gbr:matrix=gbr:primariesin=bt709:primaries=bt709:rangein=full:range=full:dither=none,"
        "format=rgb24"
    )


def _alpha_safe_filter_graph(color_pipeline: str, width: int, height: int) -> str:
    alpha_pipeline = f"alphaextract,scale={width}:{height}:flags=lanczos,format=gray"
    return (
        "format=rgba,split=2[color_source][alpha_source];"
        f"[alpha_source]{alpha_pipeline}[alpha];"
        f"[color_source]{color_pipeline}[color];"
        "[color][alpha]alphamerge,format=rgba"
    )


def _srgb_component_to_linear(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _nested_min(values: list[str]) -> str:
    result = values[0]
    for value in values[1:]:
        result = f"min({result},{value})"
    return result
