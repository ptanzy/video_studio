from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from wrld_video_studio.domain.canonical_json import canonical_json_bytes, canonical_sha256
from wrld_video_studio.domain.player_overlay import PlayerOverlaySettings
from wrld_video_studio.domain.video_effects import PanZoomSettings
from wrld_video_studio.domain.video_effects_v2 import (
    AudioBarsSettingsV2,
    GlowSettings,
    TrackProgressSettingsV2,
    _mapping,
    _required_mapping,
)


@dataclass(frozen=True)
class VideoEffectsV3:
    pan_zoom: PanZoomSettings = field(default_factory=PanZoomSettings)
    audio_bars: AudioBarsSettingsV2 = field(
        default_factory=lambda: AudioBarsSettingsV2(
            enabled=True,
            variation_mode="organic_rms",
            bar_count=32,
            color="#FFFFFF",
            opacity=0.55,
            placement="bottom_center",
            zone_width_px=900,
            zone_height_px=110,
            gap_px=8,
            horizontal_offset_px=0,
            bottom_margin_px=242,
            glow=GlowSettings(enabled=True, intensity=0.25),
        )
    )
    player: PlayerOverlaySettings | None = None

    def __post_init__(self) -> None:
        if type(self.pan_zoom) is not PanZoomSettings:
            raise ValueError("pan_zoom must be PanZoomSettings")
        if type(self.audio_bars) is not AudioBarsSettingsV2:
            raise ValueError("audio_bars must be AudioBarsSettingsV2")
        if type(self.player) is not PlayerOverlaySettings:
            raise ValueError("player must be PlayerOverlaySettings")

    @property
    def track_progress(self) -> TrackProgressSettingsV2:
        assert self.player is not None
        progress = self.player.progress
        return TrackProgressSettingsV2(
            enabled=progress.enabled,
            style="line",
            placement="bottom",
            color="#FFFFFF",
            fill_opacity=progress.fill_opacity,
            rail_color="#808080",
            rail_contrast_strength=0.6,
            rail_opacity=progress.rail_opacity,
            thickness_px=progress.thickness_px,
            segment_count=20,
        )

    def to_dict(self) -> dict[str, Any]:
        assert self.player is not None
        return {
            "pan_zoom": self.pan_zoom.to_dict(),
            "audio_bars": self.audio_bars.to_dict(),
            "player": self.player.to_dict(),
        }

    def canonical_json(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.to_dict())

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "VideoEffectsV3":
        _mapping(document, {"pan_zoom", "audio_bars", "player"}, "effects")
        pan = _required_mapping(document, "pan_zoom", "effects")
        bars = _required_mapping(document, "audio_bars", "effects")
        player = _required_mapping(document, "player", "effects")
        _mapping(
            pan,
            {"enabled", "max_zoom", "path", "cycle_seconds", "return_to_origin", "return_duration_seconds", "easing"},
            "pan_zoom",
        )
        _mapping(
            bars,
            {"enabled", "variation_mode", "bar_count", "color", "opacity", "placement", "zone_width_px", "zone_height_px", "gap_px", "horizontal_offset_px", "bottom_margin_px", "rms_window_samples", "attack_ms", "release_ms", "glow"},
            "audio_bars",
        )
        glow = _required_mapping(bars, "glow", "audio_bars")
        _mapping(glow, {"enabled", "intensity"}, "audio_bars.glow")
        bars_values = dict(bars)
        bars_values["glow"] = GlowSettings(**glow)
        return cls(
            pan_zoom=PanZoomSettings(**pan),
            audio_bars=AudioBarsSettingsV2(**bars_values),
            player=PlayerOverlaySettings.from_dict(player),
        )
