from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from wrld_video_studio.domain.color_resolution import ColorResolution
from wrld_video_studio.domain.preview_cache import (
    PREVIEW_ERROR_CODES,
    PreviewToolchainIdentity,
)


STILL_RENDER_REQUEST_VERSION = "still-render-request-v1"
STILL_RENDER_RESULT_VERSION = "still-render-result-v1"
STILL_RENDERER_VERSION = "ffmpeg-still-v1"
STILL_OUTPUT_MAX_DIMENSION = 1024


@dataclass(frozen=True, slots=True)
class StillRenderRequest:
    contract_version: str
    source_path: Path
    output_relative_path: str
    resolution: ColorResolution
    renderer_version: str = STILL_RENDERER_VERSION
    transform_version: str = "linear-luma-chroma-v1"

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "source_path": str(self.source_path),
            "output_relative_path": self.output_relative_path,
            "resolution": self.resolution.to_dict(),
            "renderer_version": self.renderer_version,
            "transform_version": self.transform_version,
        }


@dataclass(frozen=True, slots=True)
class StillRenderResult:
    contract_version: str
    artifact_path: Path
    source_sha256: str
    treatment: ColorResolution
    width: int
    height: int
    output_format: str
    renderer_version: str
    transform_version: str
    ffmpeg_version: str
    input_pixel_format: str
    output_pixel_format: str
    orientation: str
    sanitized_command: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "artifact_path": str(self.artifact_path),
            "source_sha256": self.source_sha256,
            "treatment": self.treatment.to_dict(),
            "width": self.width,
            "height": self.height,
            "output_format": self.output_format,
            "renderer_version": self.renderer_version,
            "transform_version": self.transform_version,
            "ffmpeg_version": self.ffmpeg_version,
            "input_pixel_format": self.input_pixel_format,
            "output_pixel_format": self.output_pixel_format,
            "orientation": self.orientation,
            "sanitized_command": list(self.sanitized_command),
        }


class StillImageRenderer(Protocol):
    def render(
        self, request: StillRenderRequest, cancel_event: Any = None
    ) -> StillRenderResult: ...


class PreviewRenderError(RuntimeError):
    """Path-safe preview-facing failure raised by the render boundary."""

    def __init__(self, code: str, message: str) -> None:
        if code not in PREVIEW_ERROR_CODES:
            raise ValueError("Preview render errors must use an approved preview error code.")
        self.code = code
        self.message = message
        super().__init__(message)


class PreviewRenderBackend(Protocol):
    """Bind cache identity to the exact tools used for Phase 2 rendering."""

    def identify(self, cancel_event: Any = None) -> PreviewToolchainIdentity: ...

    def render(
        self,
        *,
        source_path: Path,
        output_path: Path,
        resolution: ColorResolution,
        expected_toolchain: PreviewToolchainIdentity,
        cancel_event: Any = None,
    ) -> StillRenderResult: ...
