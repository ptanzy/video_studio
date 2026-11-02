from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

from wrld_video_studio.domain.canonical_json import canonical_json_bytes, canonical_sha256
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.video_effects import PanZoomSettings
from wrld_video_studio.domain.visual_refinement import normalize_hex, refined_bar_layout


BAR_PLACEMENTS = frozenset({"bottom_left", "bottom_center", "bottom_right"})
PROGRESS_STYLES = frozenset({"line", "segmented"})
PROGRESS_PLACEMENTS = frozenset({"top", "bottom"})
VARIATION_MODES = frozenset({"organic_rms", "symmetrical"})


@dataclass(frozen=True)
class GlowSettings:
    enabled: bool = True
    intensity: float = 0.35

    def __post_init__(self) -> None:
        _require_bool(self.enabled, "audio_bars.glow.enabled")
        object.__setattr__(self, "intensity", _number(self.intensity, 0.0, 1.0, "audio_bars.glow.intensity"))

    def to_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "intensity": self.intensity}


@dataclass(frozen=True)
class AudioBarsSettingsV2:
    enabled: bool = False
    variation_mode: str = "organic_rms"
    bar_count: int = 24
    color: str = "#FFFFFF"
    opacity: float = 0.65
    placement: str = "bottom_center"
    zone_width_px: int = 640
    zone_height_px: int = 180
    gap_px: int = 4
    horizontal_offset_px: int = 0
    bottom_margin_px: int = 64
    rms_window_samples: int = 1920
    attack_ms: float = 60.0
    release_ms: float = 240.0
    glow: GlowSettings = field(default_factory=GlowSettings)

    def __post_init__(self) -> None:
        _require_bool(self.enabled, "audio_bars.enabled")
        _enum(self.variation_mode, VARIATION_MODES, "audio_bars.variation_mode")
        _integer(self.bar_count, 8, 64, "audio_bars.bar_count")
        object.__setattr__(self, "color", normalize_hex(self.color))
        object.__setattr__(self, "opacity", _number(self.opacity, 0.1, 1.0, "audio_bars.opacity"))
        _enum(self.placement, BAR_PLACEMENTS, "audio_bars.placement")
        _integer(self.zone_width_px, 160, 1792, "audio_bars.zone_width_px")
        _integer(self.zone_height_px, 32, 952, "audio_bars.zone_height_px")
        _integer(self.gap_px, 0, 32, "audio_bars.gap_px")
        _integer(self.horizontal_offset_px, -1792, 1792, "audio_bars.horizontal_offset_px")
        _integer(self.bottom_margin_px, 64, 1016, "audio_bars.bottom_margin_px")
        _integer(self.rms_window_samples, 480, 4800, "audio_bars.rms_window_samples")
        object.__setattr__(self, "attack_ms", _number(self.attack_ms, 0.0, 500.0, "audio_bars.attack_ms"))
        object.__setattr__(self, "release_ms", _number(self.release_ms, 0.0, 1000.0, "audio_bars.release_ms"))
        if type(self.glow) is not GlowSettings:
            raise ValueError("audio_bars.glow must be GlowSettings")
        refined_bar_layout(
            self.bar_count,
            self.placement,
            self.zone_width_px,
            self.zone_height_px,
            self.gap_px,
            self.horizontal_offset_px,
            self.bottom_margin_px,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "variation_mode": self.variation_mode,
            "bar_count": self.bar_count,
            "color": self.color,
            "opacity": self.opacity,
            "placement": self.placement,
            "zone_width_px": self.zone_width_px,
            "zone_height_px": self.zone_height_px,
            "gap_px": self.gap_px,
            "horizontal_offset_px": self.horizontal_offset_px,
            "bottom_margin_px": self.bottom_margin_px,
            "rms_window_samples": self.rms_window_samples,
            "attack_ms": self.attack_ms,
            "release_ms": self.release_ms,
            "glow": self.glow.to_dict(),
        }


@dataclass(frozen=True)
class TrackProgressSettingsV2:
    enabled: bool = False
    style: str = "line"
    placement: str = "bottom"
    color: str = "#FFFFFF"
    fill_opacity: float = 0.8
    rail_color: str | None = None
    rail_contrast_strength: float = 0.6
    rail_opacity: float = 0.35
    thickness_px: int = 6
    segment_count: int = 20

    def __post_init__(self) -> None:
        _require_bool(self.enabled, "track_progress.enabled")
        _enum(self.style, PROGRESS_STYLES, "track_progress.style")
        _enum(self.placement, PROGRESS_PLACEMENTS, "track_progress.placement")
        object.__setattr__(self, "color", normalize_hex(self.color))
        object.__setattr__(self, "fill_opacity", _number(self.fill_opacity, 0.1, 1.0, "track_progress.fill_opacity"))
        if self.rail_color is not None:
            object.__setattr__(self, "rail_color", normalize_hex(self.rail_color))
        object.__setattr__(self, "rail_contrast_strength", _number(self.rail_contrast_strength, 0.0, 1.0, "track_progress.rail_contrast_strength"))
        object.__setattr__(self, "rail_opacity", _number(self.rail_opacity, 0.1, 1.0, "track_progress.rail_opacity"))
        _integer(self.thickness_px, 2, 16, "track_progress.thickness_px")
        _integer(self.segment_count, 5, 60, "track_progress.segment_count")

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "style": self.style,
            "placement": self.placement,
            "color": self.color,
            "fill_opacity": self.fill_opacity,
            "rail_color": self.rail_color,
            "rail_contrast_strength": self.rail_contrast_strength,
            "rail_opacity": self.rail_opacity,
            "thickness_px": self.thickness_px,
            "segment_count": self.segment_count,
        }


@dataclass(frozen=True)
class VideoEffectsV2:
    pan_zoom: PanZoomSettings = field(default_factory=PanZoomSettings)
    audio_bars: AudioBarsSettingsV2 = field(default_factory=AudioBarsSettingsV2)
    track_progress: TrackProgressSettingsV2 = field(default_factory=TrackProgressSettingsV2)

    def __post_init__(self) -> None:
        if type(self.pan_zoom) is not PanZoomSettings:
            raise ValueError("pan_zoom must be PanZoomSettings")
        if type(self.audio_bars) is not AudioBarsSettingsV2:
            raise ValueError("audio_bars must be AudioBarsSettingsV2")
        if type(self.track_progress) is not TrackProgressSettingsV2:
            raise ValueError("track_progress must be TrackProgressSettingsV2")

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
    def from_dict(cls, document: Mapping[str, Any]) -> VideoEffectsV2:
        _mapping(document, {"pan_zoom", "audio_bars", "track_progress"}, "effects")
        pan = _required_mapping(document, "pan_zoom", "effects")
        bars = _required_mapping(document, "audio_bars", "effects")
        progress = _required_mapping(document, "track_progress", "effects")
        _mapping(pan, {"enabled", "max_zoom", "path", "cycle_seconds", "return_to_origin", "return_duration_seconds", "easing"}, "pan_zoom")
        _mapping(bars, {"enabled", "variation_mode", "bar_count", "color", "opacity", "placement", "zone_width_px", "zone_height_px", "gap_px", "horizontal_offset_px", "bottom_margin_px", "rms_window_samples", "attack_ms", "release_ms", "glow"}, "audio_bars")
        _mapping(progress, {"enabled", "style", "placement", "color", "fill_opacity", "rail_color", "rail_contrast_strength", "rail_opacity", "thickness_px", "segment_count"}, "track_progress")
        glow = _required_mapping(bars, "glow", "audio_bars")
        _mapping(glow, {"enabled", "intensity"}, "audio_bars.glow")
        bars_values = dict(bars)
        bars_values["glow"] = GlowSettings(**glow)
        return cls(
            pan_zoom=PanZoomSettings(**pan),
            audio_bars=AudioBarsSettingsV2(**bars_values),
            track_progress=TrackProgressSettingsV2(**progress),
        )


def parse_video_effects_v2(document: Mapping[str, Any], *, error_code: str = "INVALID_EXPORT_REQUEST") -> VideoEffectsV2:
    try:
        return VideoEffectsV2.from_dict(document)
    except (KeyError, TypeError, ValueError) as error:
        raise MediaInfrastructureError(error_code, "The video-effects-v2 configuration is invalid or unsupported.") from error


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
    if not math.isfinite(normalized) or not minimum <= normalized <= maximum:
        raise ValueError(f"{label} is outside the supported range")
    return normalized


def _integer(value: Any, minimum: int, maximum: int, label: str) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} is outside the supported integer range")


def _enum(value: Any, allowed: frozenset[str], label: str) -> None:
    if type(value) is not str or value not in allowed:
        raise ValueError(f"{label} is unsupported")
