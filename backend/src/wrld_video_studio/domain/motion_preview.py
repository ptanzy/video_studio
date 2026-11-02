from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.video_effects import VideoEffects
from wrld_video_studio.domain.video_export import ExportTarget, VideoTrack
from wrld_video_studio.domain.video_export_v2 import (
    MOTION_PROFILE_ID,
    MotionVideoManifest,
    parse_motion_export_request,
)


MOTION_PREVIEW_REQUEST_VERSION = "motion-preview-request/1.0"
MIN_PREVIEW_SAMPLES = 144_000
DEFAULT_PREVIEW_SAMPLES = 240_000
MAX_PREVIEW_SAMPLES = 720_000


@dataclass(frozen=True, slots=True)
class MotionPreviewExcerpt:
    start_sample: int = 0
    sample_count: int = DEFAULT_PREVIEW_SAMPLES

    def __post_init__(self) -> None:
        if type(self.start_sample) is not int or self.start_sample < 0:
            raise ValueError("start_sample must be a nonnegative integer")
        if (
            type(self.sample_count) is not int
            or not MIN_PREVIEW_SAMPLES <= self.sample_count <= MAX_PREVIEW_SAMPLES
        ):
            raise ValueError("sample_count is outside the approved preview bounds")

    def to_dict(self) -> dict[str, int]:
        return {"start_sample": self.start_sample, "sample_count": self.sample_count}


@dataclass(frozen=True, slots=True)
class MotionPreviewRequest:
    target: ExportTarget
    effects: VideoEffects
    excerpt: MotionPreviewExcerpt = MotionPreviewExcerpt()
    profile_id: str = MOTION_PROFILE_ID
    contract_version: str = MOTION_PREVIEW_REQUEST_VERSION

    def __post_init__(self) -> None:
        if type(self.target) is not ExportTarget:
            raise ValueError("target must be ExportTarget")
        if type(self.effects) is not VideoEffects:
            raise ValueError("effects must be VideoEffects")
        if type(self.excerpt) is not MotionPreviewExcerpt:
            raise ValueError("excerpt must be MotionPreviewExcerpt")
        if self.profile_id != MOTION_PROFILE_ID:
            raise ValueError("unsupported motion profile")
        if self.contract_version != MOTION_PREVIEW_REQUEST_VERSION:
            raise ValueError("unsupported motion preview request version")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "target": self.target.to_dict(),
            "profile_id": self.profile_id,
            "effects": self.effects.to_dict(),
            "excerpt": self.excerpt.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class MotionPreviewPlan:
    manifest: MotionVideoManifest
    request: MotionPreviewRequest
    selected_tracks: tuple[VideoTrack, ...]


def parse_motion_preview_request(document: Mapping[str, Any]) -> MotionPreviewRequest:
    try:
        if set(document) != {"contract_version", "target", "profile_id", "effects", "excerpt"}:
            raise ValueError("request fields")
        if document["contract_version"] != MOTION_PREVIEW_REQUEST_VERSION:
            raise ValueError("version")
        if document["profile_id"] != MOTION_PROFILE_ID:
            raise ValueError("profile")
        target = parse_motion_export_request(
            {
                "contract_version": "video-export-request/2.0",
                "target": dict(_object(document["target"])),
                "profile_id": MOTION_PROFILE_ID,
                "effects": dict(_object(document["effects"])),
            }
        ).target
        excerpt_value = _object(document["excerpt"])
        if set(excerpt_value) != {"start_sample", "sample_count"}:
            raise ValueError("excerpt fields")
        return MotionPreviewRequest(
            target=target,
            effects=VideoEffects.from_dict(_object(document["effects"])),
            excerpt=MotionPreviewExcerpt(
                start_sample=excerpt_value["start_sample"],
                sample_count=excerpt_value["sample_count"],
            ),
        )
    except (KeyError, TypeError, ValueError, MediaInfrastructureError) as error:
        raise MediaInfrastructureError(
            "PREVIEW_INVALID_REQUEST", "The motion-preview request is invalid or unsupported."
        ) from error


def resolve_motion_preview_request(
    manifest: MotionVideoManifest,
    target: ExportTarget,
    excerpt: MotionPreviewExcerpt | None = None,
) -> MotionPreviewRequest:
    return MotionPreviewRequest(
        target=target,
        effects=manifest.effects_for(target),
        excerpt=excerpt or MotionPreviewExcerpt(),
    )


def create_motion_preview_plan(
    manifest: MotionVideoManifest, request: MotionPreviewRequest
) -> MotionPreviewPlan:
    if request.profile_id != manifest.profile_id:
        raise MediaInfrastructureError(
            "PROFILE_MISMATCH", "The preview profile does not match the manifest profile."
        )
    if request.effects != manifest.effects_for(request.target):
        raise MediaInfrastructureError(
            "PREVIEW_INVALID_REQUEST",
            "The preview effects do not match the resolved manifest configuration.",
        )
    if request.target.kind == "album":
        tracks = manifest.tracks
    elif request.target.kind == "track" and request.target.track_id is not None:
        tracks = (manifest.track(request.target.track_id),)
    else:
        raise MediaInfrastructureError(
            "PREVIEW_INVALID_REQUEST", "A supported preview target is required."
        )
    return MotionPreviewPlan(manifest, request, tracks)


def validate_excerpt(excerpt: MotionPreviewExcerpt, total_samples: int) -> None:
    if total_samples <= 0:
        raise MediaInfrastructureError("PREVIEW_RANGE_INVALID", "The preview timeline is empty.")
    if excerpt.start_sample >= total_samples:
        raise MediaInfrastructureError(
            "PREVIEW_RANGE_INVALID", "The preview start is outside the selected timeline."
        )
    if excerpt.start_sample + excerpt.sample_count > total_samples:
        raise MediaInfrastructureError(
            "PREVIEW_RANGE_INVALID", "The preview excerpt exceeds the selected timeline."
        )


def _object(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("expected object")
    return value


