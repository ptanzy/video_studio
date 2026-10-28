from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.motion_preview import MotionPreviewExcerpt
from wrld_video_studio.domain.player_overlay import ResolvedPlayerConfiguration
from wrld_video_studio.domain.video_effects_v3 import VideoEffectsV3
from wrld_video_studio.domain.video_export import ExportTarget, VideoTrack
from wrld_video_studio.domain.video_export_v2 import _object, _parse_target
from wrld_video_studio.domain.video_export_v4 import PLAYER_PROFILE_ID, PlayerVideoManifest


PLAYER_MOTION_PREVIEW_REQUEST_VERSION = "motion-preview-request/3.0"


@dataclass(frozen=True, slots=True)
class PlayerMotionPreviewRequest:
    target: ExportTarget
    effects: VideoEffectsV3
    resolved_player: ResolvedPlayerConfiguration
    excerpt: MotionPreviewExcerpt = MotionPreviewExcerpt()
    profile_id: str = PLAYER_PROFILE_ID
    contract_version: str = PLAYER_MOTION_PREVIEW_REQUEST_VERSION

    def __post_init__(self) -> None:
        if type(self.target) is not ExportTarget or type(self.effects) is not VideoEffectsV3 or type(self.resolved_player) is not ResolvedPlayerConfiguration or type(self.excerpt) is not MotionPreviewExcerpt:
            raise ValueError("player preview request contains invalid values")
        if self.profile_id != PLAYER_PROFILE_ID or self.contract_version != PLAYER_MOTION_PREVIEW_REQUEST_VERSION:
            raise ValueError("unsupported player preview request")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "target": self.target.to_dict(),
            "profile_id": self.profile_id,
            "effects": self.effects.to_dict(),
            "resolved_player": self.resolved_player.to_dict(),
            "excerpt": self.excerpt.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class PlayerMotionPreviewPlan:
    manifest: PlayerVideoManifest
    request: PlayerMotionPreviewRequest
    selected_tracks: tuple[VideoTrack, ...]


def parse_player_motion_preview_request(document: Mapping[str, Any]) -> PlayerMotionPreviewRequest:
    try:
        if set(document) != {"contract_version", "target", "profile_id", "effects", "resolved_player", "excerpt"}:
            raise ValueError("request fields")
        if document["contract_version"] != PLAYER_MOTION_PREVIEW_REQUEST_VERSION or document["profile_id"] != PLAYER_PROFILE_ID:
            raise ValueError("version or profile")
        excerpt = _object(document["excerpt"], "excerpt")
        if set(excerpt) != {"start_sample", "sample_count"}:
            raise ValueError("excerpt fields")
        return PlayerMotionPreviewRequest(
            target=_parse_target(_object(document["target"], "target")),
            effects=VideoEffectsV3.from_dict(_object(document["effects"], "effects")),
            resolved_player=ResolvedPlayerConfiguration.from_dict(_object(document["resolved_player"], "resolved_player")),
            excerpt=MotionPreviewExcerpt(excerpt["start_sample"], excerpt["sample_count"]),
        )
    except (KeyError, TypeError, ValueError, MediaInfrastructureError) as error:
        raise MediaInfrastructureError("PREVIEW_INVALID_REQUEST", "The player preview request is invalid or unsupported.") from error


def create_player_motion_preview_plan(manifest: PlayerVideoManifest, request: PlayerMotionPreviewRequest) -> PlayerMotionPreviewPlan:
    if request.profile_id != manifest.profile_id or request.effects != manifest.effects:
        raise MediaInfrastructureError("PROFILE_MISMATCH", "The preview request does not match the player project.")
    if request.target.kind == "album":
        tracks = manifest.tracks
    elif request.target.kind == "track" and request.target.track_id is not None:
        tracks = (manifest.track(request.target.track_id),)
    else:
        raise MediaInfrastructureError("PREVIEW_INVALID_REQUEST", "A supported preview target is required.")
    if tuple(item.track_id for item in request.resolved_player.display_tracks) != tuple(item.id for item in tracks):
        raise MediaInfrastructureError("PREVIEW_INVALID_REQUEST", "Resolved player metadata does not match the preview timeline.")
    return PlayerMotionPreviewPlan(manifest, request, tracks)


def resolve_player_motion_preview_request(
    manifest: PlayerVideoManifest,
    target: ExportTarget,
    resolved_player: ResolvedPlayerConfiguration,
    excerpt: MotionPreviewExcerpt | None = None,
) -> PlayerMotionPreviewRequest:
    return PlayerMotionPreviewRequest(
        target=target,
        effects=manifest.effects,
        resolved_player=resolved_player,
        excerpt=excerpt or MotionPreviewExcerpt(),
    )
