from __future__ import annotations

import hashlib
import math
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wrld_video_studio.application.ports.media import ProcessRunner
from wrld_video_studio.application.ports.still_images import (
    STILL_RENDER_REQUEST_VERSION,
    STILL_RENDERER_VERSION,
    PreviewRenderBackend,
    PreviewRenderError,
    StillRenderRequest,
    StillRenderResult,
)
from wrld_video_studio.domain.color_resolution import ColorResolution
from wrld_video_studio.domain.color_transform import TRANSFORM_VERSION
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.preview_cache import PreviewToolchainIdentity
from wrld_video_studio.infrastructure.media_tools import MediaTool, MediaToolchain
from wrld_video_studio.infrastructure.still_image_renderer import (
    FFmpegStillImageRenderer,
    PROCESS_TIMEOUT_SECONDS,
    REQUIRED_FFMPEG_ENCODERS,
    REQUIRED_FFMPEG_FILTERS,
)


_HASH_CHUNK = 1024 * 1024
_IDENTIFY_TIMEOUT_SECONDS = 15.0
_REQUIRED_DECODERS = frozenset({"mjpeg", "png", "webp", "webp_anim"})


@dataclass(frozen=True, slots=True)
class _ResolvedPreviewToolchain:
    ffmpeg: MediaTool
    ffprobe: MediaTool
    identity: PreviewToolchainIdentity


class _PinnedMediaToolchain:
    def __init__(self, resolved: _ResolvedPreviewToolchain) -> None:
        self._resolved = resolved

    def resolve(self, name: str) -> MediaTool:
        if name == "ffmpeg":
            return self._resolved.ffmpeg
        if name == "ffprobe":
            return self._resolved.ffprobe
        raise ValueError("Only ffmpeg and ffprobe are supported media tools")


class VerifiedFFmpegPreviewBackend(PreviewRenderBackend):
    """Fingerprint exact media tools and reuse the authoritative Phase 2 renderer."""

    def __init__(
        self,
        toolchain: MediaToolchain,
        runner: ProcessRunner,
        *,
        render_timeout_seconds: float = PROCESS_TIMEOUT_SECONDS,
    ) -> None:
        if (
            type(render_timeout_seconds) not in (int, float)
            or not math.isfinite(render_timeout_seconds)
            or render_timeout_seconds <= 0
        ):
            raise ValueError("Preview render timeout must be a positive finite number.")
        self._toolchain = toolchain
        self._runner = runner
        self._render_timeout_seconds = float(render_timeout_seconds)
        self._identity_guard = threading.Lock()
        self._resolved: _ResolvedPreviewToolchain | None = None

    def identify(self, cancel_event: Any = None) -> PreviewToolchainIdentity:
        return self._resolve_verified(cancel_event).identity

    def render(
        self,
        *,
        source_path: Path,
        output_path: Path,
        resolution: ColorResolution,
        expected_toolchain: PreviewToolchainIdentity,
        cancel_event: Any = None,
    ) -> StillRenderResult:
        if not isinstance(expected_toolchain, PreviewToolchainIdentity):
            raise PreviewRenderError(
                "PREVIEW_INTERNAL_ERROR", "Trusted preview toolchain identity is required."
            )
        expected_output = self._trusted_output_path(output_path)
        resolved = self._resolve_verified(cancel_event)
        if resolved.identity != expected_toolchain:
            raise PreviewRenderError(
                "PREVIEW_INTERNAL_ERROR", "The preview rendering toolchain changed."
            )
        renderer = FFmpegStillImageRenderer(
            _PinnedMediaToolchain(resolved),
            self._runner,
            expected_output.parent,
            timeout_seconds=self._render_timeout_seconds,
        )
        try:
            result = renderer.render(
                StillRenderRequest(
                    contract_version=STILL_RENDER_REQUEST_VERSION,
                    source_path=source_path,
                    output_relative_path=expected_output.name,
                    resolution=resolution,
                    renderer_version=STILL_RENDERER_VERSION,
                    transform_version=TRANSFORM_VERSION,
                ),
                cancel_event,
            )
        except MediaInfrastructureError as error:
            raise _map_media_error(error) from error
        if result.artifact_path.resolve(strict=False) != expected_output:
            raise PreviewRenderError(
                "PREVIEW_INTERNAL_ERROR", "Preview rendering produced an unexpected artifact."
            )
        self._verify_unchanged(resolved, cancel_event)
        return result

    def _resolve_verified(self, cancel_event: Any) -> _ResolvedPreviewToolchain:
        with self._identity_guard:
            _raise_if_cancelled(cancel_event)
            cached = self._resolved
            if cached is None:
                try:
                    ffmpeg_candidate = self._toolchain.resolve("ffmpeg")
                    _raise_if_cancelled(cancel_event)
                    ffprobe_candidate = self._toolchain.resolve("ffprobe")
                except MediaInfrastructureError as error:
                    raise _map_media_error(error) from error
                ffmpeg_path = _regular_tool_path(ffmpeg_candidate.path, "FFmpeg")
                ffprobe_path = _regular_tool_path(ffprobe_candidate.path, "FFprobe")
            else:
                # Tool selection is pinned for this backend lifetime. Every use
                # still hashes the exact files, so replacement cannot inherit a
                # previously established cache identity.
                ffmpeg_path = _regular_tool_path(cached.ffmpeg.path, "FFmpeg")
                ffprobe_path = _regular_tool_path(cached.ffprobe.path, "FFprobe")

            ffmpeg_before = _sha256_file(ffmpeg_path, cancel_event)
            ffprobe_before = _sha256_file(ffprobe_path, cancel_event)
            observed_identity = PreviewToolchainIdentity.create(
                ffmpeg_sha256=ffmpeg_before,
                ffprobe_sha256=ffprobe_before,
            )
            if cached is not None and observed_identity == cached.identity:
                return cached

            ffmpeg_version = self._version(ffmpeg_path, "FFmpeg", cancel_event)
            ffprobe_version = self._version(ffprobe_path, "FFprobe", cancel_event)
            self._verify_capabilities(ffmpeg_path, cancel_event)
            ffmpeg_after = _sha256_file(ffmpeg_path, cancel_event)
            ffprobe_after = _sha256_file(ffprobe_path, cancel_event)
            if ffmpeg_before != ffmpeg_after or ffprobe_before != ffprobe_after:
                raise PreviewRenderError(
                    "PREVIEW_INTERNAL_ERROR",
                    "The preview rendering toolchain changed during verification.",
                )
            resolved = _ResolvedPreviewToolchain(
                ffmpeg=MediaTool(ffmpeg_path, ffmpeg_version),
                ffprobe=MediaTool(ffprobe_path, ffprobe_version),
                identity=PreviewToolchainIdentity.create(
                    ffmpeg_sha256=ffmpeg_after,
                    ffprobe_sha256=ffprobe_after,
                ),
            )
            self._resolved = resolved
            return resolved

    def _verify_unchanged(
        self, resolved: _ResolvedPreviewToolchain, cancel_event: Any
    ) -> None:
        actual = PreviewToolchainIdentity.create(
            ffmpeg_sha256=_sha256_file(resolved.ffmpeg.path, cancel_event),
            ffprobe_sha256=_sha256_file(resolved.ffprobe.path, cancel_event),
        )
        if actual != resolved.identity:
            raise PreviewRenderError(
                "PREVIEW_INTERNAL_ERROR", "The preview rendering toolchain changed during rendering."
            )

    def _version(self, path: Path, label: str, cancel_event: Any) -> str:
        result = self._runner.run(
            [str(path), "-hide_banner", "-version"],
            timeout_seconds=_IDENTIFY_TIMEOUT_SECONDS,
            cancel_event=cancel_event,
        )
        if result.cancelled:
            raise PreviewRenderError("PREVIEW_CANCELLED", "Preview rendering was cancelled.")
        if result.timed_out:
            raise PreviewRenderError("PREVIEW_TIMEOUT", "Preview tool inspection timed out.")
        if result.returncode != 0 or not result.stdout.strip():
            raise PreviewRenderError(
                "PREVIEW_INTERNAL_ERROR", f"{label} could not be verified for preview rendering."
            )
        return result.stdout.splitlines()[0].strip()

    def _verify_capabilities(self, ffmpeg_path: Path, cancel_event: Any) -> None:
        required = {
            "filters": ("-filters", REQUIRED_FFMPEG_FILTERS),
            "encoders": ("-encoders", REQUIRED_FFMPEG_ENCODERS),
            "decoders": ("-decoders", _REQUIRED_DECODERS),
        }
        for label, (flag, expected) in required.items():
            result = self._runner.run(
                [str(ffmpeg_path), "-hide_banner", flag],
                timeout_seconds=_IDENTIFY_TIMEOUT_SECONDS,
                cancel_event=cancel_event,
            )
            if result.cancelled:
                raise PreviewRenderError("PREVIEW_CANCELLED", "Preview rendering was cancelled.")
            if result.timed_out:
                raise PreviewRenderError("PREVIEW_TIMEOUT", "Preview tool inspection timed out.")
            if result.returncode != 0:
                raise PreviewRenderError(
                    "PREVIEW_INTERNAL_ERROR", "Preview tool capabilities could not be verified."
                )
            available = {
                parts[1]
                for line in result.stdout.splitlines()
                if len(parts := line.split()) >= 2
            }
            if expected - available:
                raise PreviewRenderError(
                    "PREVIEW_INTERNAL_ERROR",
                    f"FFmpeg lacks required preview {label}.",
                )

    @staticmethod
    def _trusted_output_path(output_path: Path) -> Path:
        if not isinstance(output_path, Path) or not output_path.is_absolute():
            raise PreviewRenderError(
                "PREVIEW_INTERNAL_ERROR", "Trusted preview staging output is invalid."
            )
        candidate = output_path.resolve(strict=False)
        if (
            candidate.suffix.lower() != ".png"
            or candidate.name in {"", ".", ".."}
            or not candidate.parent.is_dir()
        ):
            raise PreviewRenderError(
                "PREVIEW_INTERNAL_ERROR", "Trusted preview staging output is invalid."
            )
        return candidate


def _regular_tool_path(path: Path, label: str) -> Path:
    try:
        resolved = Path(path).resolve(strict=True)
        metadata = resolved.stat()
    except OSError as error:
        raise PreviewRenderError(
            "PREVIEW_INTERNAL_ERROR", f"{label} is unavailable for preview rendering."
        ) from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0:
        raise PreviewRenderError(
            "PREVIEW_INTERNAL_ERROR", f"{label} is unavailable for preview rendering."
        )
    return resolved


def _sha256_file(path: Path, cancel_event: Any) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(_HASH_CHUNK):
                _raise_if_cancelled(cancel_event)
                digest.update(chunk)
    except OSError as error:
        raise PreviewRenderError(
            "PREVIEW_INTERNAL_ERROR", "The preview rendering toolchain could not be verified."
        ) from error
    _raise_if_cancelled(cancel_event)
    return digest.hexdigest()


def _raise_if_cancelled(cancel_event: Any) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise PreviewRenderError("PREVIEW_CANCELLED", "Preview rendering was cancelled.")


def _map_media_error(error: MediaInfrastructureError) -> PreviewRenderError:
    if error.code == "PROCESS_CANCELLED":
        return PreviewRenderError("PREVIEW_CANCELLED", "Preview rendering was cancelled.")
    if error.code in {
        "PROCESS_TIMEOUT",
        "IMAGE_PROBE_TIMEOUT",
        "MEDIA_CAPABILITY_PROBE_TIMEOUT",
    }:
        return PreviewRenderError("PREVIEW_TIMEOUT", "Preview rendering timed out.")
    if error.code in {
        "IMAGE_UNSUPPORTED_OR_CORRUPT",
        "IMAGE_TOO_LARGE",
        "UNSUPPORTED_IMAGE_FORMAT",
        "IMAGE_COLOR_PROFILE_UNSUPPORTED",
        "IMAGE_EXTENSION_MISMATCH",
        "IMAGE_DIMENSION_LIMIT",
        "IMAGE_PIXEL_LIMIT",
        "ANIMATED_IMAGE_UNSUPPORTED",
        "IMAGE_UNDECODABLE",
        "UNSUPPORTED_IMAGE_CODEC",
        "UNSUPPORTED_PIXEL_FORMAT",
        "UNSUPPORTED_COLOR_METADATA",
    }:
        return PreviewRenderError(
            "PREVIEW_IMAGE_UNSUPPORTED", "The artwork cannot be rendered as a preview."
        )
    if error.code in {"IMAGE_RENDER_FAILED", "OUTPUT_INVALID"}:
        return PreviewRenderError("PREVIEW_RENDER_FAILED", "Preview rendering failed.")
    return PreviewRenderError(
        "PREVIEW_INTERNAL_ERROR", "Preview rendering could not be completed safely."
    )
