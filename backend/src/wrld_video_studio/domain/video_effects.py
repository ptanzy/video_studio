from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from wrld_video_studio.domain.canonical_json import canonical_json_bytes, canonical_sha256
from wrld_video_studio.domain.media_errors import MediaInfrastructureError


PAN_PATHS = frozenset(
    {"center", "horizontal", "vertical", "diagonal_down_right", "diagonal_up_right"}
)
BAR_PLACEMENTS = frozenset({"bottom_left", "bottom_center", "bottom_right"})
PROGRESS_STYLES = frozenset({"line", "segmented"})
PROGRESS_PLACEMENTS = frozenset({"top", "bottom"})


@dataclass(frozen=True)
class PanZoomSettings:
    enabled: bool = False
    max_zoom: float = 1.04
    path: str = "diagonal_down_right"
    cycle_seconds: float = 180.0
    return_to_origin: bool = True
    return_duration_seconds: float = 5.0
    easing: str = "smoothstep"

    def __post_init__(self) -> None:
        _require_bool(self.enabled, "pan_zoom.enabled")
        object.__setattr__(self, "max_zoom", _number(self.max_zoom, 1.0, 1.05, "pan_zoom.max_zoom"))
        _enum(self.path, PAN_PATHS, "pan_zoom.path")
        object.__setattr__(
            self,
            "cycle_seconds",
            _number(self.cycle_seconds, 15.0, 600.0, "pan_zoom.cycle_seconds"),
        )
        _require_bool(self.return_to_origin, "pan_zoom.return_to_origin")
        object.__setattr__(
            self,
            "return_duration_seconds",
            _number(
                self.return_duration_seconds,
                0.5,
                30.0,
                "pan_zoom.return_duration_seconds",
            ),
        )
        if self.easing != "smoothstep":
            raise ValueError("pan_zoom.easing must be smoothstep")

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "max_zoom": self.max_zoom,
            "path": self.path,
            "cycle_seconds": self.cycle_seconds,
            "return_to_origin": self.return_to_origin,
            "return_duration_seconds": self.return_duration_seconds,
            "easing": self.easing,
        }


@dataclass(frozen=True)
class AudioBarsSettings:
    enabled: bool = False
    bar_count: int = 24
    opacity: float = 0.65
    placement: str = "bottom_center"
    rms_window_samples: int = 1920
    attack_ms: float = 60.0
    release_ms: float = 240.0

    def __post_init__(self) -> None:
        _require_bool(self.enabled, "audio_bars.enabled")
        _integer(self.bar_count, 8, 64, "audio_bars.bar_count")
        object.__setattr__(
            self, "opacity", _number(self.opacity, 0.1, 1.0, "audio_bars.opacity")
        )
        _enum(self.placement, BAR_PLACEMENTS, "audio_bars.placement")
        _integer(
            self.rms_window_samples,
            480,
            4800,
            "audio_bars.rms_window_samples",
        )
        object.__setattr__(
            self, "attack_ms", _number(self.attack_ms, 0.0, 500.0, "audio_bars.attack_ms")
        )
        object.__setattr__(
            self,
            "release_ms",
            _number(self.release_ms, 0.0, 1000.0, "audio_bars.release_ms"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "bar_count": self.bar_count,
            "opacity": self.opacity,
            "placement": self.placement,
            "rms_window_samples": self.rms_window_samples,
            "attack_ms": self.attack_ms,
            "release_ms": self.release_ms,
        }


@dataclass(frozen=True)
class TrackProgressSettings:
    enabled: bool = False
    style: str = "line"
    placement: str = "bottom"
    opacity: float = 0.8
    thickness_px: int = 6
    segment_count: int = 20

    def __post_init__(self) -> None:
        _require_bool(self.enabled, "track_progress.enabled")
        _enum(self.style, PROGRESS_STYLES, "track_progress.style")
        _enum(self.placement, PROGRESS_PLACEMENTS, "track_progress.placement")
        object.__setattr__(
            self, "opacity", _number(self.opacity, 0.1, 1.0, "track_progress.opacity")
        )
        _integer(self.thickness_px, 2, 16, "track_progress.thickness_px")
        _integer(self.segment_count, 5, 60, "track_progress.segment_count")

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "style": self.style,
            "placement": self.placement,
            "opacity": self.opacity,
            "thickness_px": self.thickness_px,
            "segment_count": self.segment_count,
        }


@dataclass(frozen=True)
class VideoEffects:
    pan_zoom: PanZoomSettings = field(default_factory=PanZoomSettings)
    audio_bars: AudioBarsSettings = field(default_factory=AudioBarsSettings)
    track_progress: TrackProgressSettings = field(default_factory=TrackProgressSettings)

    def __post_init__(self) -> None:
        if type(self.pan_zoom) is not PanZoomSettings:
            raise ValueError("pan_zoom must be PanZoomSettings")
        if type(self.audio_bars) is not AudioBarsSettings:
            raise ValueError("audio_bars must be AudioBarsSettings")
        if type(self.track_progress) is not TrackProgressSettings:
            raise ValueError("track_progress must be TrackProgressSettings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "pan_zoom": self.pan_zoom.to_dict(),
            "audio_bars": self.audio_bars.to_dict(),
            "track_progress": self.track_progress.to_dict(),
        }

    def canonical_json(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.to_dict())

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> VideoEffects:
        _mapping(document, {"pan_zoom", "audio_bars", "track_progress"}, "effects")
        pan_zoom = _required_mapping(document, "pan_zoom", "effects")
        audio_bars = _required_mapping(document, "audio_bars", "effects")
        track_progress = _required_mapping(document, "track_progress", "effects")
        _mapping(
            pan_zoom,
            {
                "enabled",
                "max_zoom",
                "path",
                "cycle_seconds",
                "return_to_origin",
                "return_duration_seconds",
                "easing",
            },
            "pan_zoom",
        )
        _mapping(
            audio_bars,
            {
                "enabled",
                "bar_count",
                "opacity",
                "placement",
                "rms_window_samples",
                "attack_ms",
                "release_ms",
            },
            "audio_bars",
        )
        _mapping(
            track_progress,
            {"enabled", "style", "placement", "opacity", "thickness_px", "segment_count"},
            "track_progress",
        )
        return cls(
            pan_zoom=PanZoomSettings(**pan_zoom),
            audio_bars=AudioBarsSettings(**audio_bars),
            track_progress=TrackProgressSettings(**track_progress),
        )


def parse_video_effects(
    document: Mapping[str, Any], *, error_code: str = "INVALID_EXPORT_REQUEST"
) -> VideoEffects:
    try:
        return VideoEffects.from_dict(document)
    except (KeyError, TypeError, ValueError) as error:
        raise MediaInfrastructureError(
            error_code, "The video-effects configuration is invalid or unsupported."
        ) from error


def _mapping(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{label} fields do not match the contract")
    return value


def _required_mapping(document: Mapping[str, Any], key: str, label: str) -> Mapping[str, Any]:
    value = document[key]
    if not isinstance(value, Mapping):
        raise ValueError(f"{label}.{key} must be an object")
    return value


def _require_bool(value: Any, label: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"{label} must be a boolean")


def _number(value: Any, minimum: float, maximum: float, label: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite number")
    normalized = float(value)
    if normalized != normalized or normalized in (float("inf"), float("-inf")):
        raise ValueError(f"{label} must be a finite number")
    if normalized < minimum or normalized > maximum:
        raise ValueError(f"{label} is outside the supported range")
    return normalized


def _integer(value: Any, minimum: int, maximum: int, label: str) -> None:
    if type(value) is not int or value < minimum or value > maximum:
        raise ValueError(f"{label} is outside the supported integer range")


def _enum(value: Any, allowed: frozenset[str], label: str) -> None:
    if type(value) is not str or value not in allowed:
        raise ValueError(f"{label} is unsupported")
