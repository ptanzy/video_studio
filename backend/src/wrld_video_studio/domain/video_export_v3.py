from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.video_effects_v2 import VideoEffectsV2
from wrld_video_studio.domain.video_export import (
    AlbumIdentity,
    ExportTarget,
    VideoTrack,
    safe_title,
    validate_portable_path,
)
from wrld_video_studio.domain.video_export_v2 import (
    _allowed_keys,
    _exact_keys,
    _object,
    _parse_target,
    _positive_int,
    _stable_id,
    _text,
    _validate_artifact,
    _validate_timeline_entry,
    _validate_tracks,
)


REFINED_MANIFEST_FORMAT = "wrld-video-album/3.0"
REFINED_EXPORT_REQUEST_VERSION = "video-export-request/3.0"
REFINED_EXPORT_RESULT_VERSION = "video-export-result/3.0"
REFINED_PROFILE_ID = "youtube-1080p30-motion-v2"
REFINED_RENDERER_VERSION = "wu3b-motion-export-2"


@dataclass(frozen=True, slots=True)
class RefinedTrackEffectsOverride:
    track_id: str
    effects: VideoEffectsV2

    def __post_init__(self) -> None:
        _stable_id(self.track_id)
        if type(self.effects) is not VideoEffectsV2:
            raise ValueError("effects must be VideoEffectsV2")

    def to_dict(self) -> dict[str, Any]:
        return {"track_id": self.track_id, "effects": self.effects.to_dict()}


@dataclass(frozen=True, slots=True)
class RefinedVideoManifest:
    format: str
    album: AlbumIdentity
    background: str
    cover: str | None
    thumbnail: str | None
    tracks: tuple[VideoTrack, ...]
    profile_id: str
    effects: VideoEffectsV2
    track_effects: tuple[RefinedTrackEffectsOverride, ...]
    source: Mapping[str, Any]

    def track(self, track_id: str) -> VideoTrack:
        for item in self.tracks:
            if item.id == track_id:
                return item
        raise MediaInfrastructureError(
            "TRACK_NOT_FOUND", "The requested track ID is not present in the album manifest."
        )

    def effects_for(self, target: ExportTarget) -> VideoEffectsV2:
        if target.kind == "album":
            return self.effects
        if target.kind != "track" or target.track_id is None:
            raise MediaInfrastructureError(
                "INVALID_EXPORT_REQUEST", "A supported export target is required."
            )
        self.track(target.track_id)
        for override in self.track_effects:
            if override.track_id == target.track_id:
                return override.effects
        return self.effects


@dataclass(frozen=True, slots=True)
class RefinedVideoExportRequest:
    target: ExportTarget
    effects: VideoEffectsV2
    profile_id: str = REFINED_PROFILE_ID
    contract_version: str = REFINED_EXPORT_REQUEST_VERSION

    def __post_init__(self) -> None:
        if type(self.target) is not ExportTarget:
            raise ValueError("target must be ExportTarget")
        if type(self.effects) is not VideoEffectsV2:
            raise ValueError("effects must be VideoEffectsV2")
        if self.profile_id != REFINED_PROFILE_ID:
            raise ValueError("unsupported refined motion profile")
        if self.contract_version != REFINED_EXPORT_REQUEST_VERSION:
            raise ValueError("unsupported refined request version")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "target": self.target.to_dict(),
            "profile_id": self.profile_id,
            "effects": self.effects.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class RefinedVideoExportPlan:
    manifest: RefinedVideoManifest
    request: RefinedVideoExportRequest
    selected_tracks: tuple[VideoTrack, ...]
    output_relative_path: str
    artifact_kind: str
    effect_config_digest: str


@dataclass(frozen=True, slots=True)
class RefinedVideoExportResult:
    job_id: str
    attempt_id: str
    state: str
    target: ExportTarget
    effects: VideoEffectsV2
    request_digest: str
    artifacts: tuple[Mapping[str, Any], ...]
    timeline: tuple[Mapping[str, Any], ...]
    warnings: tuple[str, ...]
    started_at: str
    finished_at: str
    profile_id: str = REFINED_PROFILE_ID
    contract_version: str = REFINED_EXPORT_RESULT_VERSION

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "contract_version": self.contract_version,
            "job_id": self.job_id,
            "attempt_id": self.attempt_id,
            "state": self.state,
            "target": self.target.to_dict(),
            "profile_id": self.profile_id,
            "effects": self.effects.to_dict(),
            "request_digest": self.request_digest,
            "artifacts": [dict(item) for item in self.artifacts],
            "warnings": list(self.warnings),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }
        if self.timeline:
            value["timeline"] = [dict(item) for item in self.timeline]
        return value


def parse_refined_manifest(document: Mapping[str, Any]) -> RefinedVideoManifest:
    try:
        _exact_keys(document, {"format", "album", "visual", "tracks", "render"})
        album_value = _object(document["album"], "album")
        visual = _object(document["visual"], "visual")
        render = _object(document["render"], "render")
        raw_tracks = document["tracks"]
        _exact_keys(album_value, {"id", "title", "artist", "channel"})
        _allowed_keys(visual, {"background", "cover", "thumbnail"}, {"background"})
        _allowed_keys(render, {"profile_id", "effects", "track_effects"}, {"profile_id", "effects"})
        if not isinstance(raw_tracks, list):
            raise ValueError("tracks must be an array")
        album = AlbumIdentity(
            id=_stable_id(album_value["id"]),
            title=_text(album_value["title"]),
            artist=_text(album_value["artist"]),
            channel=_text(album_value["channel"]),
        )
        tracks: list[VideoTrack] = []
        for raw_track in raw_tracks:
            item = _object(raw_track, "track")
            _allowed_keys(item, {"id", "number", "title", "audio", "clips"}, {"id", "number", "title", "audio"})
            tracks.append(
                VideoTrack(
                    id=_stable_id(item["id"]),
                    number=_positive_int(item["number"], "track.number"),
                    title=_text(item["title"]),
                    audio=validate_portable_path(item["audio"]),
                )
            )
        raw_overrides = render.get("track_effects", [])
        if not isinstance(raw_overrides, list):
            raise ValueError("render.track_effects must be an array")
        overrides: list[RefinedTrackEffectsOverride] = []
        for raw_override in raw_overrides:
            item = _object(raw_override, "track_effects entry")
            _exact_keys(item, {"track_id", "effects"})
            overrides.append(
                RefinedTrackEffectsOverride(
                    _stable_id(item["track_id"]),
                    VideoEffectsV2.from_dict(_object(item["effects"], "track effects")),
                )
            )
        manifest = RefinedVideoManifest(
            format=_text(document["format"]),
            album=album,
            background=validate_portable_path(visual["background"]),
            cover=validate_portable_path(visual["cover"]) if "cover" in visual else None,
            thumbnail=validate_portable_path(visual["thumbnail"]) if "thumbnail" in visual else None,
            tracks=tuple(tracks),
            profile_id=_text(render["profile_id"]),
            effects=VideoEffectsV2.from_dict(_object(render["effects"], "effects")),
            track_effects=tuple(overrides),
            source=dict(document),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise MediaInfrastructureError(
            "MANIFEST_INVALID", "The refined motion manifest is incomplete or malformed."
        ) from error
    if manifest.format != REFINED_MANIFEST_FORMAT or manifest.profile_id != REFINED_PROFILE_ID:
        raise MediaInfrastructureError(
            "MANIFEST_UNSUPPORTED", "The refined manifest version or render profile is unsupported."
        )
    _validate_tracks(manifest.tracks)
    override_ids = [item.track_id for item in manifest.track_effects]
    if len(set(override_ids)) != len(override_ids):
        raise MediaInfrastructureError(
            "MANIFEST_INVALID", "Track effect overrides must have unique track IDs."
        )
    track_ids = {item.id for item in manifest.tracks}
    if any(item not in track_ids for item in override_ids):
        raise MediaInfrastructureError(
            "MANIFEST_INVALID", "Track effect overrides must reference existing track IDs."
        )
    return manifest


def parse_refined_export_request(document: Mapping[str, Any]) -> RefinedVideoExportRequest:
    try:
        _exact_keys(document, {"contract_version", "target", "profile_id", "effects"})
        if document["contract_version"] != REFINED_EXPORT_REQUEST_VERSION:
            raise ValueError("version")
        if document["profile_id"] != REFINED_PROFILE_ID:
            raise ValueError("profile")
        return RefinedVideoExportRequest(
            target=_parse_target(_object(document["target"], "target")),
            effects=VideoEffectsV2.from_dict(_object(document["effects"], "effects")),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise MediaInfrastructureError(
            "INVALID_EXPORT_REQUEST", "The refined video-export request is invalid or unsupported."
        ) from error


def resolve_refined_export_request(
    manifest: RefinedVideoManifest, target: ExportTarget
) -> RefinedVideoExportRequest:
    return RefinedVideoExportRequest(target=target, effects=manifest.effects_for(target))


def create_refined_plan(
    manifest: RefinedVideoManifest, request: RefinedVideoExportRequest
) -> RefinedVideoExportPlan:
    if manifest.profile_id != request.profile_id:
        raise MediaInfrastructureError(
            "PROFILE_MISMATCH", "The request profile does not match the manifest profile."
        )
    if request.effects != manifest.effects_for(request.target):
        raise MediaInfrastructureError(
            "INVALID_EXPORT_REQUEST", "The request effects do not match the resolved manifest configuration."
        )
    digest = request.effects.fingerprint
    root = f"profiles/{REFINED_PROFILE_ID}/{digest}"
    if request.target.kind == "album":
        tracks = manifest.tracks
        relative = f"{root}/album/{safe_title(manifest.album.title)}.mp4"
        kind = "album_video"
    else:
        if request.target.track_id is None:
            raise MediaInfrastructureError("INVALID_EXPORT_REQUEST", "A track ID is required.")
        track = manifest.track(request.target.track_id)
        tracks = (track,)
        relative = f"{root}/tracks/{track.number:02d} - {safe_title(track.title)}.mp4"
        kind = "track_video"
    return RefinedVideoExportPlan(manifest, request, tracks, relative, kind, digest)


def parse_refined_export_result(document: Mapping[str, Any]) -> RefinedVideoExportResult:
    try:
        allowed = {"contract_version", "job_id", "attempt_id", "state", "target", "profile_id", "effects", "request_digest", "artifacts", "timeline", "warnings", "started_at", "finished_at"}
        _allowed_keys(document, allowed, allowed - {"timeline"})
        if document["contract_version"] != REFINED_EXPORT_RESULT_VERSION or document["profile_id"] != REFINED_PROFILE_ID:
            raise ValueError("version or profile")
        if document["state"] not in {"completed", "failed", "cancelled"}:
            raise ValueError("state")
        digest = document["request_digest"]
        if type(digest) is not str or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("request digest")
        artifacts = document["artifacts"]
        timeline = document.get("timeline", [])
        warnings = document["warnings"]
        if not isinstance(artifacts, list) or not isinstance(timeline, list):
            raise ValueError("artifact or timeline collection")
        if not isinstance(warnings, list) or any(type(item) is not str for item in warnings):
            raise ValueError("warnings")
        return RefinedVideoExportResult(
            job_id=_text(document["job_id"]),
            attempt_id=_text(document["attempt_id"]),
            state=document["state"],
            target=_parse_target(_object(document["target"], "target")),
            effects=VideoEffectsV2.from_dict(_object(document["effects"], "effects")),
            request_digest=digest,
            artifacts=tuple(_validate_artifact(item) for item in artifacts),
            timeline=tuple(_validate_timeline_entry(item) for item in timeline),
            warnings=tuple(warnings),
            started_at=_text(document["started_at"]),
            finished_at=_text(document["finished_at"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise MediaInfrastructureError(
            "OUTPUT_INVALID", "The refined video-export result is invalid or unsupported."
        ) from error
