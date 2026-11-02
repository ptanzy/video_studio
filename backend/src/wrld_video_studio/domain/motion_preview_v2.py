from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.motion_preview import MotionPreviewExcerpt, validate_excerpt
from wrld_video_studio.domain.video_effects_v2 import VideoEffectsV2
from wrld_video_studio.domain.video_export import ExportTarget, VideoTrack
from wrld_video_studio.domain.video_export_v2 import _object, _parse_target
from wrld_video_studio.domain.video_export_v3 import (
    REFINED_PROFILE_ID,
    RefinedVideoManifest,
)


REFINED_MOTION_PREVIEW_REQUEST_VERSION = "motion-preview-request/2.0"


@dataclass(frozen=True, slots=True)
class RefinedMotionPreviewRequest:
    target: ExportTarget
    effects: VideoEffectsV2
    excerpt: MotionPreviewExcerpt = MotionPreviewExcerpt()
    profile_id: str = REFINED_PROFILE_ID
    contract_version: str = REFINED_MOTION_PREVIEW_REQUEST_VERSION

    def __post_init__(self) -> None:
        if type(self.target) is not ExportTarget:
            raise ValueError("target must be ExportTarget")
        if type(self.effects) is not VideoEffectsV2:
            raise ValueError("effects must be VideoEffectsV2")
        if type(self.excerpt) is not MotionPreviewExcerpt:
            raise ValueError("excerpt must be MotionPreviewExcerpt")
        if self.profile_id != REFINED_PROFILE_ID:
            raise ValueError("unsupported refined motion profile")
        if self.contract_version != REFINED_MOTION_PREVIEW_REQUEST_VERSION:
            raise ValueError("unsupported refined motion preview request version")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "target": self.target.to_dict(),
            "profile_id": self.profile_id,
            "effects": self.effects.to_dict(),
            "excerpt": self.excerpt.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class RefinedMotionPreviewPlan:
    manifest: RefinedVideoManifest
    request: RefinedMotionPreviewRequest
    selected_tracks: tuple[VideoTrack, ...]


def parse_refined_motion_preview_request(
    document: Mapping[str, Any],
) -> RefinedMotionPreviewRequest:
    try:
        if set(document) != {
            "contract_version",
            "target",
            "profile_id",
            "effects",
            "excerpt",
        }:
            raise ValueError("request fields")
        if document["contract_version"] != REFINED_MOTION_PREVIEW_REQUEST_VERSION:
            raise ValueError("version")
        if document["profile_id"] != REFINED_PROFILE_ID:
            raise ValueError("profile")
        excerpt_value = _object(document["excerpt"], "excerpt")
        if set(excerpt_value) != {"start_sample", "sample_count"}:
            raise ValueError("excerpt fields")
        return RefinedMotionPreviewRequest(
            target=_parse_target(_object(document["target"], "target")),
            effects=VideoEffectsV2.from_dict(_object(document["effects"], "effects")),
            excerpt=MotionPreviewExcerpt(
                start_sample=excerpt_value["start_sample"],
                sample_count=excerpt_value["sample_count"],
            ),
        )
    except (KeyError, TypeError, ValueError, MediaInfrastructureError) as error:
        raise MediaInfrastructureError(
            "PREVIEW_INVALID_REQUEST",
            "The refined motion-preview request is invalid or unsupported.",
        ) from error


def resolve_refined_motion_preview_request(
    manifest: RefinedVideoManifest,
    target: ExportTarget,
    excerpt: MotionPreviewExcerpt | None = None,
) -> RefinedMotionPreviewRequest:
    return RefinedMotionPreviewRequest(
        target=target,
        effects=manifest.effects_for(target),
        excerpt=excerpt or MotionPreviewExcerpt(),
    )


def create_refined_motion_preview_plan(
    manifest: RefinedVideoManifest,
    request: RefinedMotionPreviewRequest,
) -> RefinedMotionPreviewPlan:
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
    return RefinedMotionPreviewPlan(manifest, request, tracks)


__all__ = [
    "REFINED_MOTION_PREVIEW_REQUEST_VERSION",
    "RefinedMotionPreviewPlan",
    "RefinedMotionPreviewRequest",
    "create_refined_motion_preview_plan",
    "parse_refined_motion_preview_request",
    "resolve_refined_motion_preview_request",
    "validate_excerpt",
]
