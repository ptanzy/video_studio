from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping

from wrld_video_studio.domain.video_effects import PanZoomSettings
from wrld_video_studio.domain.video_effects_v2 import (
    AudioBarsSettingsV2,
    GlowSettings,
    TrackProgressSettingsV2,
    VideoEffectsV2,
)
from wrld_video_studio.domain.video_export import ExportTarget, VideoTrack


RENDERER_ID = "wrld-creation-renderer"
RENDERER_CONTRACT_VERSION = "wrld-creation-renderer/1.0"
RENDERER_VERSION = "wu6-creation-renderer-1"
CAMERA_DIRECTIONS = (
    "horizontal",
    "vertical",
    "diagonal_down_right",
    "diagonal_up_right",
)


def camera_direction(kind: str, composition_id: str) -> str:
    if kind not in {"album", "single", "short"} or not composition_id:
        raise ValueError("A stable Creation composition identity is required.")
    digest = hashlib.sha256(f"{kind}:{composition_id}".encode("utf-8")).digest()
    return CAMERA_DIRECTIONS[digest[0] % len(CAMERA_DIRECTIONS)]


def effects_from_visual_configuration(
    target: Mapping[str, Any], visual: Mapping[str, Any]
) -> VideoEffectsV2:
    canvas = visual["canvas"]["aspect_ratio"]
    portrait = canvas == "9:16"
    camera = visual["camera"]
    bars = visual["visualizer"]
    progress = visual["progress"]
    return VideoEffectsV2(
        pan_zoom=PanZoomSettings(
            enabled=camera["mode"] == "bounded",
            max_zoom=float(camera["max_zoom"]),
            path=camera_direction(str(target["kind"]), str(target["composition_id"])),
            cycle_seconds=180.0,
            return_to_origin=True,
            return_duration_seconds=5.0,
            easing="smoothstep",
        ),
        audio_bars=AudioBarsSettingsV2(
            enabled=bool(bars["enabled"]),
            variation_mode="organic_rms",
            bar_count=int(bars["bar_count"]),
            color="#FFFFFF",
            opacity=float(bars["opacity"]),
            placement="bottom_center",
            zone_width_px=720 if portrait else 640,
            zone_height_px=240 if portrait else 180,
            gap_px=4,
            horizontal_offset_px=0,
            bottom_margin_px=64,
            rms_window_samples=1920,
            attack_ms=60.0,
            release_ms=240.0,
            glow=GlowSettings(enabled=True, intensity=0.35),
        ),
        track_progress=TrackProgressSettingsV2(
            enabled=bool(progress["enabled"]),
            style="line",
            placement="bottom",
            color="#FFFFFF",
            fill_opacity=0.8,
            rail_color=None,
            rail_contrast_strength=0.6,
            rail_opacity=0.35,
            thickness_px=6,
            segment_count=20,
        ),
    )


@dataclass(frozen=True, slots=True)
class CreationRenderExcerpt:
    start_sample: int
    sample_count: int

    def __post_init__(self) -> None:
        if type(self.start_sample) is not int or self.start_sample < 0:
            raise ValueError("start_sample must be a nonnegative integer")
        if type(self.sample_count) is not int or self.sample_count <= 0:
            raise ValueError("sample_count must be a positive integer")


@dataclass(frozen=True, slots=True)
class CreationRenderRequest:
    target: ExportTarget
    effects: VideoEffectsV2
    excerpt: CreationRenderExcerpt
    visual_configuration: Mapping[str, Any]
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class CreationRenderManifest:
    background: str


@dataclass(frozen=True, slots=True)
class CreationRenderExecutionPlan:
    manifest: CreationRenderManifest
    request: CreationRenderRequest
    selected_tracks: tuple[VideoTrack, ...]
    output_relative_path: str
    artifact_kind: str


__all__ = [
    "CAMERA_DIRECTIONS",
    "CreationRenderExcerpt",
    "CreationRenderExecutionPlan",
    "CreationRenderManifest",
    "CreationRenderRequest",
    "RENDERER_CONTRACT_VERSION",
    "RENDERER_ID",
    "RENDERER_VERSION",
    "camera_direction",
    "effects_from_visual_configuration",
]
