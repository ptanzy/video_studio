from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.video_effects import VideoEffects
from wrld_video_studio.domain.video_export import (
    AlbumIdentity,
    ExportTarget,
    VideoTrack,
    safe_title,
    validate_portable_path,
)


MOTION_MANIFEST_FORMAT = "wrld-video-album/2.0"
MOTION_EXPORT_REQUEST_VERSION = "video-export-request/2.0"
MOTION_EXPORT_RESULT_VERSION = "video-export-result/2.0"
MOTION_PROFILE_ID = "youtube-1080p30-motion-v1"
MOTION_RENDERER_VERSION = "wu3b-motion-export-1"
_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class TrackEffectsOverride:
    track_id: str
    effects: VideoEffects

    def __post_init__(self) -> None:
        _stable_id(self.track_id)
        if type(self.effects) is not VideoEffects:
            raise ValueError("effects must be VideoEffects")

    def to_dict(self) -> dict[str, Any]:
        return {"track_id": self.track_id, "effects": self.effects.to_dict()}


@dataclass(frozen=True)
class MotionVideoManifest:
    format: str
    album: AlbumIdentity
    background: str
    cover: str | None
    thumbnail: str | None
    tracks: tuple[VideoTrack, ...]
    profile_id: str
    effects: VideoEffects
    track_effects: tuple[TrackEffectsOverride, ...]
    source: Mapping[str, Any]

    def track(self, track_id: str) -> VideoTrack:
        for item in self.tracks:
            if item.id == track_id:
                return item
        raise MediaInfrastructureError(
            "TRACK_NOT_FOUND", "The requested track ID is not present in the album manifest."
        )

    def effects_for(self, target: ExportTarget) -> VideoEffects:
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


@dataclass(frozen=True)
class MotionVideoExportRequest:
    target: ExportTarget
    effects: VideoEffects
    profile_id: str = MOTION_PROFILE_ID
    contract_version: str = MOTION_EXPORT_REQUEST_VERSION

    def __post_init__(self) -> None:
        if type(self.target) is not ExportTarget:
            raise ValueError("target must be ExportTarget")
        if type(self.effects) is not VideoEffects:
            raise ValueError("effects must be VideoEffects")
        if self.profile_id != MOTION_PROFILE_ID:
            raise ValueError("unsupported motion profile")
        if self.contract_version != MOTION_EXPORT_REQUEST_VERSION:
            raise ValueError("unsupported motion request version")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "target": self.target.to_dict(),
            "profile_id": self.profile_id,
            "effects": self.effects.to_dict(),
        }


@dataclass(frozen=True)
class MotionVideoExportPlan:
    manifest: MotionVideoManifest
    request: MotionVideoExportRequest
    selected_tracks: tuple[VideoTrack, ...]
    output_relative_path: str
    artifact_kind: str
    effect_config_digest: str


@dataclass(frozen=True)
class MotionVideoExportResult:
    job_id: str
    attempt_id: str
    state: str
    target: ExportTarget
    effects: VideoEffects
    request_digest: str
    artifacts: tuple[Mapping[str, Any], ...]
    timeline: tuple[Mapping[str, Any], ...]
    warnings: tuple[str, ...]
    started_at: str
    finished_at: str
    profile_id: str = MOTION_PROFILE_ID
    contract_version: str = MOTION_EXPORT_RESULT_VERSION

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


def parse_motion_manifest(document: Mapping[str, Any]) -> MotionVideoManifest:
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
            _allowed_keys(
                item,
                {"id", "number", "title", "audio", "clips"},
                {"id", "number", "title", "audio"},
            )
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
        overrides: list[TrackEffectsOverride] = []
        for raw_override in raw_overrides:
            item = _object(raw_override, "track_effects entry")
            _exact_keys(item, {"track_id", "effects"})
            overrides.append(
                TrackEffectsOverride(
                    _stable_id(item["track_id"]),
                    VideoEffects.from_dict(_object(item["effects"], "track effects")),
                )
            )
        manifest = MotionVideoManifest(
            format=_text(document["format"]),
            album=album,
            background=validate_portable_path(visual["background"]),
            cover=validate_portable_path(visual["cover"]) if "cover" in visual else None,
            thumbnail=(
                validate_portable_path(visual["thumbnail"]) if "thumbnail" in visual else None
            ),
            tracks=tuple(tracks),
            profile_id=_text(render["profile_id"]),
            effects=VideoEffects.from_dict(_object(render["effects"], "effects")),
            track_effects=tuple(overrides),
            source=dict(document),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise MediaInfrastructureError(
            "MANIFEST_INVALID", "The motion video manifest is incomplete or malformed."
        ) from error
    if manifest.format != MOTION_MANIFEST_FORMAT or manifest.profile_id != MOTION_PROFILE_ID:
        raise MediaInfrastructureError(
            "MANIFEST_UNSUPPORTED", "The motion manifest version or render profile is unsupported."
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


def parse_motion_export_request(document: Mapping[str, Any]) -> MotionVideoExportRequest:
    try:
        _exact_keys(document, {"contract_version", "target", "profile_id", "effects"})
        if document["contract_version"] != MOTION_EXPORT_REQUEST_VERSION:
            raise ValueError("version")
        if document["profile_id"] != MOTION_PROFILE_ID:
            raise ValueError("profile")
        target = _parse_target(_object(document["target"], "target"))
        effects = VideoEffects.from_dict(_object(document["effects"], "effects"))
        return MotionVideoExportRequest(target=target, effects=effects)
    except (KeyError, TypeError, ValueError) as error:
        raise MediaInfrastructureError(
            "INVALID_EXPORT_REQUEST", "The motion video-export request is invalid or unsupported."
        ) from error


def resolve_motion_export_request(
    manifest: MotionVideoManifest, target: ExportTarget
) -> MotionVideoExportRequest:
    """Freeze the complete manifest-selected effect configuration into a request."""
    effects = manifest.effects_for(target)
    return MotionVideoExportRequest(target=target, effects=effects)


def create_motion_plan(
    manifest: MotionVideoManifest, request: MotionVideoExportRequest
) -> MotionVideoExportPlan:
    if manifest.profile_id != request.profile_id:
        raise MediaInfrastructureError(
            "PROFILE_MISMATCH", "The request profile does not match the manifest profile."
        )
    expected_effects = manifest.effects_for(request.target)
    if request.effects != expected_effects:
        raise MediaInfrastructureError(
            "INVALID_EXPORT_REQUEST",
            "The request effects do not match the resolved manifest configuration.",
        )
    effect_digest = request.effects.fingerprint
    root = f"profiles/{MOTION_PROFILE_ID}/{effect_digest}"
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
    return MotionVideoExportPlan(
        manifest,
        request,
        tracks,
        relative,
        kind,
        effect_digest,
    )


def parse_motion_export_result(document: Mapping[str, Any]) -> MotionVideoExportResult:
    try:
        allowed = {
            "contract_version",
            "job_id",
            "attempt_id",
            "state",
            "target",
            "profile_id",
            "effects",
            "request_digest",
            "artifacts",
            "timeline",
            "warnings",
            "started_at",
            "finished_at",
        }
        required = allowed - {"timeline"}
        _allowed_keys(document, allowed, required)
        if document["contract_version"] != MOTION_EXPORT_RESULT_VERSION:
            raise ValueError("version")
        if document["profile_id"] != MOTION_PROFILE_ID:
            raise ValueError("profile")
        state = document["state"]
        if state not in {"completed", "failed", "cancelled"}:
            raise ValueError("state")
        digest = document["request_digest"]
        if type(digest) is not str or _SHA256.fullmatch(digest) is None:
            raise ValueError("request digest")
        artifacts = document["artifacts"]
        timeline = document.get("timeline", [])
        warnings = document["warnings"]
        if not isinstance(artifacts, list) or not isinstance(timeline, list):
            raise ValueError("artifact or timeline collection")
        if not isinstance(warnings, list) or any(type(item) is not str for item in warnings):
            raise ValueError("warnings")
        checked_artifacts = tuple(_validate_artifact(item) for item in artifacts)
        checked_timeline = tuple(_validate_timeline_entry(item) for item in timeline)
        return MotionVideoExportResult(
            job_id=_text(document["job_id"]),
            attempt_id=_text(document["attempt_id"]),
            state=state,
            target=_parse_target(_object(document["target"], "target")),
            effects=VideoEffects.from_dict(_object(document["effects"], "effects")),
            request_digest=digest,
            artifacts=checked_artifacts,
            timeline=checked_timeline,
            warnings=tuple(warnings),
            started_at=_text(document["started_at"]),
            finished_at=_text(document["finished_at"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise MediaInfrastructureError(
            "OUTPUT_INVALID", "The motion video-export result is invalid or unsupported."
        ) from error


def _parse_target(raw_target: Mapping[str, Any]) -> ExportTarget:
    kind = raw_target.get("kind")
    if kind == "album" and set(raw_target) == {"kind"}:
        return ExportTarget("album")
    if kind == "track" and set(raw_target) == {"kind", "track_id"}:
        return ExportTarget("track", _stable_id(raw_target["track_id"]))
    raise ValueError("invalid target")


def _validate_tracks(tracks: tuple[VideoTrack, ...]) -> None:
    if not tracks:
        raise MediaInfrastructureError("MANIFEST_INVALID", "At least one track is required.")
    ids = [item.id for item in tracks]
    numbers = [item.number for item in tracks]
    paths = [item.audio.casefold() for item in tracks]
    if len(set(ids)) != len(ids):
        raise MediaInfrastructureError("DUPLICATE_TRACK_ID", "Track IDs must be unique.")
    if len(set(numbers)) != len(numbers):
        raise MediaInfrastructureError("DUPLICATE_TRACK_NUMBER", "Track numbers must be unique.")
    if len(set(paths)) != len(paths):
        raise MediaInfrastructureError("DUPLICATE_AUDIO_PATH", "Track audio paths must be unique.")
    if numbers != sorted(numbers):
        raise MediaInfrastructureError(
            "TRACK_ORDER_INVALID", "Tracks must be ordered by their unique positive number."
        )


def _validate_artifact(value: Any) -> Mapping[str, Any]:
    item = _object(value, "artifact")
    _allowed_keys(
        item,
        {"kind", "path", "sha256", "byte_size", "verification", "media"},
        {"kind", "path", "sha256", "byte_size", "verification"},
    )
    if item["kind"] not in {"album_video", "track_video", "chapters"}:
        raise ValueError("artifact kind")
    validate_portable_path(item["path"])
    if type(item["sha256"]) is not str or _SHA256.fullmatch(item["sha256"]) is None:
        raise ValueError("artifact digest")
    if type(item["byte_size"]) is not int or item["byte_size"] < 0:
        raise ValueError("artifact byte size")
    if item["verification"] != "verified":
        raise ValueError("artifact verification")
    if "media" in item and not isinstance(item["media"], Mapping):
        raise ValueError("artifact media")
    return dict(item)


def _validate_timeline_entry(value: Any) -> Mapping[str, Any]:
    item = _object(value, "timeline entry")
    fields = {"track_id", "number", "title", "start_sample", "sample_count", "display_seconds"}
    _exact_keys(item, fields)
    _stable_id(item["track_id"])
    _positive_int(item["number"], "timeline.number")
    _text(item["title"])
    for name in ("start_sample", "display_seconds"):
        if type(item[name]) is not int or item[name] < 0:
            raise ValueError(name)
    _positive_int(item["sample_count"], "timeline.sample_count")
    return dict(item)


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str]) -> None:
    if set(value) != expected:
        raise ValueError("object fields do not match the contract")


def _allowed_keys(value: Mapping[str, Any], allowed: set[str], required: set[str]) -> None:
    if not required.issubset(value) or not set(value).issubset(allowed):
        raise ValueError("object fields do not match the contract")


def _text(value: Any) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError("expected a nonempty trimmed string")
    value.encode("utf-8", errors="strict")
    return value


def _stable_id(value: Any) -> str:
    text = _text(value)
    if len(text) > 128 or _STABLE_ID.fullmatch(text) is None:
        raise ValueError("invalid stable ID")
    return text


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value
