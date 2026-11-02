from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from wrld_video_studio.domain.canonical_json import canonical_sha256
from wrld_video_studio.domain.color_resolution import (
    INPUT_CONTRACT_VERSION,
    OUTPUT_CONTRACT_VERSION,
    PRESET_HEX_BY_ID,
    PRESET_MAPPING_VERSION,
    RESOLVER_VERSION,
    ColorResolution,
    ColorResolutionError,
    resolve_color_treatment,
)
from wrld_video_studio.domain.color_transform import TRANSFORM_VERSION


PREVIEW_REQUEST_VERSION = "preview-request-v1"
PREVIEW_RESULT_VERSION = "preview-result-v1"
PREVIEW_ERROR_VERSION = "preview-error-v1"
PREVIEW_CACHE_KEY_VERSION = "preview-cache-key-v1"
PREVIEW_VARIANT = "authoritative_still"
TOOLCHAIN_FINGERPRINT_VERSION = "preview-toolchain-fingerprint-v1"
STILL_RENDERER_VERSION = "ffmpeg-still-v1"
STILL_OUTPUT_MAX_DIMENSION = 1024
GEOMETRY_POLICY_VERSION = "phase2-still-geometry-v1"
ORIENTATION_POLICY_VERSION = "phase2-exif-orientation-v1"
OUTPUT_FORMAT = "png"
OUTPUT_PIXEL_FORMAT = "rgba"
SCALE_FILTER = "lanczos"
DITHER_POLICY = "none"
OUTPUT_COLOR_PRIMARIES = "bt709"
OUTPUT_COLOR_TRANSFER = "iec61966-2-1"
OUTPUT_COLOR_SPACE = "rgb"

DEFAULT_PREVIEW_CACHE_MAX_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_PREVIEW_CACHE_MAX_ENTRIES = 2_000
DEFAULT_PREVIEW_MAX_WAITING_REQUESTS = 4

PREVIEW_ERROR_CODES = frozenset(
    {
        "PREVIEW_INVALID_REQUEST",
        "PREVIEW_SOURCE_UNAVAILABLE",
        "SOURCE_CHANGED",
        "PREVIEW_IMAGE_UNSUPPORTED",
        "PREVIEW_RENDER_FAILED",
        "PREVIEW_CANCELLED",
        "PREVIEW_TIMEOUT",
        "PREVIEW_CAPACITY_EXHAUSTED",
        "PREVIEW_CACHE_CORRUPT",
        "PREVIEW_INTERNAL_ERROR",
    }
)

_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_HEX_PATTERN = re.compile(r"^#[0-9A-F]{6}$")
_OPAQUE_ARTWORK_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_COLOR_RESOLUTION_FIELDS = frozenset(
    {
        "contract_version",
        "mode",
        "resolved_hex",
        "preset_id",
        "intensity",
        "source",
        "reason",
        "resolver_version",
        "preset_mapping_version",
        "input_fingerprint",
    }
)


class PreviewContractError(ValueError):
    """Stable transport-independent validation error for preview contracts."""

    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None) -> None:
        self.code = code
        self.message = message
        self._details = _freeze_json(dict(details or {}), "details")
        super().__init__(message)

    @property
    def details(self) -> Mapping[str, Any]:
        return self._details


@dataclass(frozen=True, slots=True)
class PreviewTreatmentSelection:
    mode: str
    intensity: float
    preset: str | None = None
    hex: str | None = None

    def __post_init__(self) -> None:
        try:
            resolve_color_treatment(
                {"contract_version": INPUT_CONTRACT_VERSION, "treatment": self.to_dict()}
            )
        except ColorResolutionError as error:
            raise PreviewContractError(
                "PREVIEW_INVALID_REQUEST", "Treatment selection is invalid.", {"color_code": error.code}
            ) from error
        object.__setattr__(
            self,
            "intensity",
            _normalize_number(self.intensity, "treatment.intensity", minimum=0.0, maximum=0.6),
        )
        if self.hex is not None:
            object.__setattr__(self, "hex", self.hex.upper())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PreviewTreatmentSelection:
        if type(value) is not dict:
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Treatment must be an object.")
        payload = {"contract_version": INPUT_CONTRACT_VERSION, "treatment": dict(value)}
        try:
            resolve_color_treatment(payload)
        except ColorResolutionError as error:
            raise PreviewContractError(
                "PREVIEW_INVALID_REQUEST", "Treatment selection is invalid.", {"color_code": error.code}
            ) from error
        mode = value["mode"]
        intensity = _normalize_number(value["intensity"], "treatment.intensity", minimum=0.0, maximum=0.6)
        if mode == "preset":
            return cls(mode=mode, preset=value["preset"], intensity=intensity)
        if mode == "custom":
            return cls(mode=mode, hex=value["hex"].upper(), intensity=intensity)
        return cls(mode=mode, intensity=intensity)

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {"mode": self.mode, "intensity": self.intensity}
        if self.preset is not None:
            value["preset"] = self.preset
        if self.hex is not None:
            value["hex"] = self.hex
        return value


@dataclass(frozen=True, slots=True)
class PreviewTarget:
    album_id: str
    artwork_asset_id: str
    track_id: str | None = None
    short_id: str | None = None

    def __post_init__(self) -> None:
        _validate_identifier(self.album_id, "target.album_id")
        _validate_artwork_asset_id(self.artwork_asset_id)
        _validate_optional_identifier(self.track_id, "target.track_id")
        _validate_optional_identifier(self.short_id, "target.short_id")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PreviewTarget:
        if type(value) is not dict:
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview target must be an object.")
        required = {"album_id", "artwork_asset_id"}
        allowed = required | {"track_id", "short_id"}
        if not required <= set(value) or set(value) - allowed:
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview target fields are invalid.")
        return cls(
            album_id=_validate_identifier(value["album_id"], "target.album_id"),
            artwork_asset_id=_validate_artwork_asset_id(value["artwork_asset_id"]),
            track_id=_validate_optional_identifier(value.get("track_id"), "target.track_id"),
            short_id=_validate_optional_identifier(value.get("short_id"), "target.short_id"),
        )

    def to_dict(self) -> dict[str, str]:
        value = {"album_id": self.album_id, "artwork_asset_id": self.artwork_asset_id}
        if self.track_id is not None:
            value["track_id"] = self.track_id
        if self.short_id is not None:
            value["short_id"] = self.short_id
        return value


@dataclass(frozen=True, slots=True)
class PreviewRequest:
    contract_version: str
    target: PreviewTarget
    treatment: PreviewTreatmentSelection
    variant: str

    def __post_init__(self) -> None:
        if self.contract_version != PREVIEW_REQUEST_VERSION or self.variant != PREVIEW_VARIANT:
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview request version or variant is unsupported.")
        if not isinstance(self.target, PreviewTarget) or not isinstance(self.treatment, PreviewTreatmentSelection):
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview request contains untrusted nested values.")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PreviewRequest:
        if type(value) is not dict or set(value) != {"contract_version", "target", "treatment", "variant"}:
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview request fields are invalid.")
        if value["contract_version"] != PREVIEW_REQUEST_VERSION:
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview request version is unsupported.")
        if value["variant"] != PREVIEW_VARIANT:
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview variant is unsupported.")
        return cls(
            contract_version=PREVIEW_REQUEST_VERSION,
            target=PreviewTarget.from_dict(value["target"]),
            treatment=PreviewTreatmentSelection.from_dict(value["treatment"]),
            variant=PREVIEW_VARIANT,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "target": self.target.to_dict(),
            "treatment": self.treatment.to_dict(),
            "variant": self.variant,
        }


@dataclass(frozen=True, slots=True)
class PreviewToolchainIdentity:
    ffmpeg_sha256: str
    ffprobe_sha256: str

    def __post_init__(self) -> None:
        _validate_sha256(self.ffmpeg_sha256, "ffmpeg_sha256")
        _validate_sha256(self.ffprobe_sha256, "ffprobe_sha256")

    @classmethod
    def create(cls, *, ffmpeg_sha256: str, ffprobe_sha256: str) -> PreviewToolchainIdentity:
        return cls(
            ffmpeg_sha256=_validate_sha256(ffmpeg_sha256, "ffmpeg_sha256"),
            ffprobe_sha256=_validate_sha256(ffprobe_sha256, "ffprobe_sha256"),
        )

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(
            {
                "contract_version": TOOLCHAIN_FINGERPRINT_VERSION,
                "ffmpeg_sha256": self.ffmpeg_sha256,
                "ffprobe_sha256": self.ffprobe_sha256,
            }
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "ffmpeg_sha256": self.ffmpeg_sha256,
            "ffprobe_sha256": self.ffprobe_sha256,
        }


@dataclass(frozen=True, slots=True)
class PreviewTreatmentIdentity:
    state: str
    resolved_hex: str | None
    intensity: float
    resolver_version: str
    preset_mapping_version: str

    def __post_init__(self) -> None:
        if self.resolver_version != RESOLVER_VERSION or self.preset_mapping_version != PRESET_MAPPING_VERSION:
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Color resolution version is unsupported.")
        object.__setattr__(
            self,
            "intensity",
            _normalize_number(self.intensity, "treatment.intensity", minimum=0.0, maximum=0.6),
        )
        if self.state == "untreated":
            if self.resolved_hex is not None or self.intensity != 0.0:
                raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Untreated cache identity is inconsistent.")
        elif self.state == "treated":
            if type(self.resolved_hex) is not str or not _HEX_PATTERN.fullmatch(self.resolved_hex):
                raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Treated cache identity requires normalized HEX.")
        else:
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Treatment identity state is unsupported.")

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "resolved_hex": self.resolved_hex,
            "intensity": self.intensity,
            "resolver_version": self.resolver_version,
            "preset_mapping_version": self.preset_mapping_version,
        }


@dataclass(frozen=True, slots=True)
class PreviewRenderPolicy:
    renderer_version: str = STILL_RENDERER_VERSION
    transform_version: str = TRANSFORM_VERSION
    geometry_policy_version: str = GEOMETRY_POLICY_VERSION
    orientation_policy_version: str = ORIENTATION_POLICY_VERSION
    max_longest_side: int = STILL_OUTPUT_MAX_DIMENSION
    no_upscale: bool = True
    scale_filter: str = SCALE_FILTER
    dither: str = DITHER_POLICY
    output_format: str = OUTPUT_FORMAT
    output_pixel_format: str = OUTPUT_PIXEL_FORMAT
    color_primaries: str = OUTPUT_COLOR_PRIMARIES
    color_transfer: str = OUTPUT_COLOR_TRANSFER
    color_space: str = OUTPUT_COLOR_SPACE

    def __post_init__(self) -> None:
        actual = self.to_dict()
        authoritative = {
            "renderer_version": STILL_RENDERER_VERSION,
            "transform_version": TRANSFORM_VERSION,
            "geometry_policy_version": GEOMETRY_POLICY_VERSION,
            "orientation_policy_version": ORIENTATION_POLICY_VERSION,
            "max_longest_side": STILL_OUTPUT_MAX_DIMENSION,
            "no_upscale": True,
            "scale_filter": SCALE_FILTER,
            "dither": DITHER_POLICY,
            "output_format": OUTPUT_FORMAT,
            "output_pixel_format": OUTPUT_PIXEL_FORMAT,
            "color_primaries": OUTPUT_COLOR_PRIMARIES,
            "color_transfer": OUTPUT_COLOR_TRANSFER,
            "color_space": OUTPUT_COLOR_SPACE,
        }
        if actual != authoritative:
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview render policy version is unsupported.")

    def to_dict(self) -> dict[str, object]:
        return {
            "renderer_version": self.renderer_version,
            "transform_version": self.transform_version,
            "geometry_policy_version": self.geometry_policy_version,
            "orientation_policy_version": self.orientation_policy_version,
            "max_longest_side": self.max_longest_side,
            "no_upscale": self.no_upscale,
            "scale_filter": self.scale_filter,
            "dither": self.dither,
            "output_format": self.output_format,
            "output_pixel_format": self.output_pixel_format,
            "color_primaries": self.color_primaries,
            "color_transfer": self.color_transfer,
            "color_space": self.color_space,
        }


@dataclass(frozen=True, slots=True)
class PreviewCacheDescriptor:
    contract_version: str
    source_sha256: str
    treatment: PreviewTreatmentIdentity
    render_policy: PreviewRenderPolicy
    toolchain: PreviewToolchainIdentity

    def __post_init__(self) -> None:
        if self.contract_version != PREVIEW_CACHE_KEY_VERSION:
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview cache-key version is unsupported.")
        _validate_sha256(self.source_sha256, "source_sha256")
        if not isinstance(self.treatment, PreviewTreatmentIdentity):
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Trusted treatment identity is required.")
        if not isinstance(self.render_policy, PreviewRenderPolicy):
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Trusted render policy is required.")
        if not isinstance(self.toolchain, PreviewToolchainIdentity):
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Trusted toolchain identity is required.")

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "source_sha256": self.source_sha256,
            "treatment": self.treatment.to_dict(),
            "render_policy": self.render_policy.to_dict(),
            "toolchain": self.toolchain.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class PreviewCacheIdentity:
    preview_id: str
    descriptor: PreviewCacheDescriptor
    resolution: ColorResolution

    def __post_init__(self) -> None:
        _validate_sha256(self.preview_id, "preview_id")
        if not isinstance(self.descriptor, PreviewCacheDescriptor):
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview cache descriptor is required.")
        if self.preview_id != canonical_sha256(self.descriptor.to_dict()):
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview ID does not match its descriptor.")
        validated_resolution = validate_color_resolution(self.resolution)
        if _treatment_identity(validated_resolution) != self.descriptor.treatment:
            raise PreviewContractError(
                "PREVIEW_INVALID_REQUEST", "Associated color resolution does not match the cache descriptor."
            )


def build_preview_cache_identity(
    *,
    source_sha256: str,
    resolution: ColorResolution,
    toolchain: PreviewToolchainIdentity,
) -> PreviewCacheIdentity:
    """Build identity from server-derived authoritative inputs only.

    Request IDs, filesystem paths, timestamps, and caller-supplied version data
    are intentionally absent. Render-policy values come from the approved Phase
    2 implementation constants rather than function parameters.
    """
    source_digest = _validate_sha256(source_sha256, "source_sha256")
    validated_resolution = validate_color_resolution(resolution)
    treatment = _treatment_identity(validated_resolution)
    if not isinstance(toolchain, PreviewToolchainIdentity):
        raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Trusted toolchain identity is required.")
    descriptor = PreviewCacheDescriptor(
        contract_version=PREVIEW_CACHE_KEY_VERSION,
        source_sha256=source_digest,
        treatment=treatment,
        render_policy=PreviewRenderPolicy(),
        toolchain=toolchain,
    )
    return PreviewCacheIdentity(
        preview_id=canonical_sha256(descriptor.to_dict()),
        descriptor=descriptor,
        resolution=validated_resolution,
    )


@dataclass(frozen=True, slots=True)
class PreviewResult:
    _identity: PreviewCacheIdentity = field(repr=False)
    contract_version: str
    preview_id: str
    cache_status: str
    retrieval_reference: str
    media_type: str
    width: int
    height: int
    artifact_sha256: str
    source_sha256: str
    treatment: ColorResolution
    cache_key_version: str
    resolver_version: str
    preset_mapping_version: str
    renderer_version: str
    transform_version: str
    toolchain_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self._identity, PreviewCacheIdentity):
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Trusted preview cache identity is required.")
        if (
            self.contract_version != PREVIEW_RESULT_VERSION
            or type(self.cache_status) is not str
            or self.cache_status not in {"hit", "miss"}
            or self.media_type != "image/png"
            or self.cache_key_version != PREVIEW_CACHE_KEY_VERSION
            or self.resolver_version != RESOLVER_VERSION
            or self.preset_mapping_version != PRESET_MAPPING_VERSION
            or self.renderer_version != STILL_RENDERER_VERSION
            or self.transform_version != TRANSFORM_VERSION
        ):
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview result version or metadata is unsupported.")
        _validate_sha256(self.preview_id, "preview_id")
        _validate_sha256(self.artifact_sha256, "artifact_sha256")
        _validate_sha256(self.source_sha256, "source_sha256")
        _validate_sha256(self.toolchain_fingerprint, "toolchain_fingerprint")
        if self.retrieval_reference != f"preview:{self.preview_id}":
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview retrieval reference is inconsistent.")
        object.__setattr__(self, "width", _normalize_dimension(self.width, "width"))
        object.__setattr__(self, "height", _normalize_dimension(self.height, "height"))
        _treatment_identity(self.treatment)
        expected = {
            "preview_id": self._identity.preview_id,
            "source_sha256": self._identity.descriptor.source_sha256,
            "treatment": self._identity.resolution,
            "cache_key_version": self._identity.descriptor.contract_version,
            "resolver_version": self._identity.resolution.resolver_version,
            "preset_mapping_version": self._identity.resolution.preset_mapping_version,
            "renderer_version": self._identity.descriptor.render_policy.renderer_version,
            "transform_version": self._identity.descriptor.render_policy.transform_version,
            "toolchain_fingerprint": self._identity.descriptor.toolchain.fingerprint,
            "retrieval_reference": f"preview:{self._identity.preview_id}",
        }
        actual = {
            "preview_id": self.preview_id,
            "source_sha256": self.source_sha256,
            "treatment": self.treatment,
            "cache_key_version": self.cache_key_version,
            "resolver_version": self.resolver_version,
            "preset_mapping_version": self.preset_mapping_version,
            "renderer_version": self.renderer_version,
            "transform_version": self.transform_version,
            "toolchain_fingerprint": self.toolchain_fingerprint,
            "retrieval_reference": self.retrieval_reference,
        }
        if actual != expected:
            raise PreviewContractError(
                "PREVIEW_INVALID_REQUEST", "Preview result metadata does not match its trusted cache identity."
            )

    @classmethod
    def create(
        cls,
        *,
        identity: PreviewCacheIdentity,
        cache_status: str,
        width: int,
        height: int,
        artifact_sha256: str,
    ) -> PreviewResult:
        if not isinstance(identity, PreviewCacheIdentity):
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview cache identity is required.")
        if type(cache_status) is not str or cache_status not in {"hit", "miss"}:
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Cache status is invalid.")
        return cls(
            _identity=identity,
            contract_version=PREVIEW_RESULT_VERSION,
            preview_id=identity.preview_id,
            cache_status=cache_status,
            retrieval_reference=f"preview:{identity.preview_id}",
            media_type="image/png",
            width=_normalize_dimension(width, "width"),
            height=_normalize_dimension(height, "height"),
            artifact_sha256=_validate_sha256(artifact_sha256, "artifact_sha256"),
            source_sha256=identity.descriptor.source_sha256,
            treatment=identity.resolution,
            cache_key_version=PREVIEW_CACHE_KEY_VERSION,
            resolver_version=RESOLVER_VERSION,
            preset_mapping_version=PRESET_MAPPING_VERSION,
            renderer_version=STILL_RENDERER_VERSION,
            transform_version=TRANSFORM_VERSION,
            toolchain_fingerprint=identity.descriptor.toolchain.fingerprint,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], *, identity: PreviewCacheIdentity) -> PreviewResult:
        """Bind an external result representation to a trusted expected identity."""
        if not isinstance(identity, PreviewCacheIdentity):
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Trusted preview cache identity is required.")
        fields = {
            "contract_version",
            "preview_id",
            "cache_status",
            "retrieval_reference",
            "media_type",
            "width",
            "height",
            "artifact_sha256",
            "source_sha256",
            "treatment",
            "provenance",
        }
        if type(value) is not dict or set(value) != fields:
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview result fields are invalid.")
        provenance = value["provenance"]
        provenance_fields = {
            "cache_key_version",
            "resolver_version",
            "preset_mapping_version",
            "renderer_version",
            "transform_version",
            "toolchain_fingerprint",
        }
        if type(provenance) is not dict or set(provenance) != provenance_fields:
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview result provenance fields are invalid.")
        treatment = _color_resolution_from_dict(value["treatment"])
        return cls(
            _identity=identity,
            contract_version=value["contract_version"],
            preview_id=value["preview_id"],
            cache_status=value["cache_status"],
            retrieval_reference=value["retrieval_reference"],
            media_type=value["media_type"],
            width=value["width"],
            height=value["height"],
            artifact_sha256=value["artifact_sha256"],
            source_sha256=value["source_sha256"],
            treatment=treatment,
            cache_key_version=provenance["cache_key_version"],
            resolver_version=provenance["resolver_version"],
            preset_mapping_version=provenance["preset_mapping_version"],
            renderer_version=provenance["renderer_version"],
            transform_version=provenance["transform_version"],
            toolchain_fingerprint=provenance["toolchain_fingerprint"],
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "preview_id": self.preview_id,
            "cache_status": self.cache_status,
            "retrieval_reference": self.retrieval_reference,
            "media_type": self.media_type,
            "width": self.width,
            "height": self.height,
            "artifact_sha256": self.artifact_sha256,
            "source_sha256": self.source_sha256,
            "treatment": self.treatment.to_dict(),
            "provenance": {
                "cache_key_version": self.cache_key_version,
                "resolver_version": self.resolver_version,
                "preset_mapping_version": self.preset_mapping_version,
                "renderer_version": self.renderer_version,
                "transform_version": self.transform_version,
                "toolchain_fingerprint": self.toolchain_fingerprint,
            },
        }


@dataclass(frozen=True, slots=True)
class PreviewError:
    code: str
    message: str
    details: Mapping[str, Any]
    correlation_id: str

    def __post_init__(self) -> None:
        if type(self.code) is not str or self.code not in PREVIEW_ERROR_CODES:
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview error code is unsupported.")
        _validate_identifier(self.message, "error.message")
        _validate_identifier(self.correlation_id, "error.correlation_id")
        if not isinstance(self.details, Mapping):
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview error details must be an object.")
        object.__setattr__(self, "details", _freeze_json(dict(self.details), "error.details"))

    @classmethod
    def create(
        cls,
        *,
        code: str,
        message: str,
        correlation_id: str,
        details: Mapping[str, Any] | None = None,
    ) -> PreviewError:
        if type(code) is not str or code not in PREVIEW_ERROR_CODES:
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview error code is unsupported.")
        if details is None:
            normalized_details: Mapping[str, Any] = {}
        elif isinstance(details, Mapping):
            normalized_details = details
        else:
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview error details must be an object.")
        return cls(
            code=code,
            message=_validate_identifier(message, "error.message"),
            details=normalized_details,
            correlation_id=_validate_identifier(correlation_id, "error.correlation_id"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_version": PREVIEW_ERROR_VERSION,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": _thaw_json(self.details),
                "correlation_id": self.correlation_id,
            },
        }


def validate_color_resolution(resolution: ColorResolution) -> ColorResolution:
    """Validate the complete Phase 1 output contract at the Phase 3A trust boundary."""
    if not isinstance(resolution, ColorResolution):
        raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Trusted color resolution is required.")
    if (
        resolution.contract_version != OUTPUT_CONTRACT_VERSION
        or resolution.resolver_version != RESOLVER_VERSION
        or resolution.preset_mapping_version != PRESET_MAPPING_VERSION
    ):
        raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Color resolution version is unsupported.")
    if type(resolution.mode) is not str or resolution.mode not in {"auto", "preset", "custom"}:
        raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Color resolution mode is unsupported.")
    intensity = _normalize_number(resolution.intensity, "treatment.intensity", minimum=0.0, maximum=0.6)
    if resolution.resolved_hex is not None and (
        type(resolution.resolved_hex) is not str or not _HEX_PATTERN.fullmatch(resolution.resolved_hex)
    ):
        raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Resolved HEX is invalid.")
    if resolution.preset_id is not None and (
        type(resolution.preset_id) is not str or resolution.preset_id not in PRESET_HEX_BY_ID
    ):
        raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Resolved preset identifier is unsupported.")
    _validate_sha256(resolution.input_fingerprint, "treatment.input_fingerprint")

    if resolution.mode == "custom":
        valid = resolution.preset_id is None and resolution.resolved_hex is not None
        expected = ("user_selection", "explicit_custom")
    elif resolution.mode == "preset":
        expected_hex = PRESET_HEX_BY_ID.get(resolution.preset_id) if resolution.preset_id else None
        valid = resolution.preset_id is not None and resolution.resolved_hex == expected_hex
        if resolution.preset_id == "original":
            valid = valid and intensity == 0.0
            expected = ("user_selection", "explicit_original")
        else:
            expected = ("user_selection", "explicit_preset")
    elif resolution.source == "track_preference":
        valid = resolution.preset_id is None and resolution.resolved_hex is not None
        expected = ("track_preference", "explicit_track_preference")
    elif resolution.source == "album_palette":
        valid = resolution.preset_id is None and resolution.resolved_hex is not None
        expected = ("album_palette", "first_palette_entry")
    elif resolution.source == "album_default":
        expected_hex = PRESET_HEX_BY_ID.get(resolution.preset_id) if resolution.preset_id else None
        valid = resolution.preset_id is not None and resolution.resolved_hex == expected_hex
        if resolution.preset_id == "original":
            valid = valid and intensity == 0.0
            expected = ("album_default", "album_default_original")
        else:
            expected = ("album_default", "album_default_preset")
    elif resolution.source == "fallback":
        valid = resolution.preset_id == "original" and resolution.resolved_hex is None and intensity == 0.0
        expected = ("fallback", "no_usable_auto_color")
    else:
        valid, expected = False, ("", "")
    if not valid or (resolution.source, resolution.reason) != expected:
        raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Color resolution fields are inconsistent.")
    return resolution


def _treatment_identity(resolution: ColorResolution) -> PreviewTreatmentIdentity:
    validated = validate_color_resolution(resolution)
    intensity = _normalize_number(validated.intensity, "treatment.intensity", minimum=0.0, maximum=0.6)
    state = "untreated" if validated.resolved_hex is None else "treated"
    return PreviewTreatmentIdentity(
        state=state,
        resolved_hex=validated.resolved_hex,
        intensity=intensity,
        resolver_version=validated.resolver_version,
        preset_mapping_version=validated.preset_mapping_version,
    )


def _color_resolution_from_dict(value: Any) -> ColorResolution:
    if type(value) is not dict or set(value) != _COLOR_RESOLUTION_FIELDS:
        raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Resolved treatment fields are invalid.")
    return validate_color_resolution(ColorResolution(**value))


def _validate_sha256(value: Any, field: str) -> str:
    if type(value) is not str or not _SHA256_PATTERN.fullmatch(value):
        raise PreviewContractError("PREVIEW_INVALID_REQUEST", "SHA-256 value is invalid.", {"field": field})
    return value


def _validate_identifier(value: Any, field: str) -> str:
    if type(value) is not str or not value:
        raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Identifier must be non-empty text.", {"field": field})
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Identifier contains malformed Unicode.", {"field": field}) from error
    return value


def _validate_artwork_asset_id(value: Any) -> str:
    if type(value) is not str or not _OPAQUE_ARTWORK_ID_PATTERN.fullmatch(value):
        raise PreviewContractError(
            "PREVIEW_INVALID_REQUEST",
            "Artwork asset identifier must use 1-128 ASCII letters, digits, underscores, or hyphens.",
            {"field": "target.artwork_asset_id"},
        )
    return value


def _validate_optional_identifier(value: Any, field: str) -> str | None:
    return None if value is None else _validate_identifier(value, field)


def _normalize_number(value: Any, field: str, *, minimum: float, maximum: float) -> float:
    if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)) or not minimum <= value <= maximum:
        raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Numeric value is outside its supported range.", {"field": field})
    normalized = float(value)
    return 0.0 if normalized == 0.0 else normalized


def _normalize_dimension(value: Any, field: str) -> int:
    if type(value) is int:
        normalized = value
    elif type(value) is float and math.isfinite(value) and value.is_integer():
        normalized = int(value)
    else:
        raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview dimension is invalid.", {"field": field})
    if not 1 <= normalized <= STILL_OUTPUT_MAX_DIMENSION:
        raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Preview dimension is invalid.", {"field": field})
    return normalized


def _freeze_json(value: Any, path: str) -> Any:
    if value is None or type(value) in (str, bool, int):
        if type(value) is str:
            try:
                value.encode("utf-8", errors="strict")
            except UnicodeEncodeError as error:
                raise PreviewContractError(
                    "PREVIEW_INVALID_REQUEST", "Error details contain malformed Unicode.", {"field": path}
                ) from error
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Error details must contain finite JSON values.", {"field": path})
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Error detail keys must be strings.", {"field": path})
            try:
                key.encode("utf-8", errors="strict")
            except UnicodeEncodeError as error:
                raise PreviewContractError(
                    "PREVIEW_INVALID_REQUEST",
                    "Error detail keys must be valid UTF-8.",
                    {"field": path},
                ) from error
            frozen[key] = _freeze_json(item, f"{path}.{key}")
        return MappingProxyType(frozen)
    if type(value) is list:
        return tuple(_freeze_json(item, f"{path}[{index}]") for index, item in enumerate(value))
    raise PreviewContractError("PREVIEW_INVALID_REQUEST", "Error details must be JSON-compatible.", {"field": path})


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value
