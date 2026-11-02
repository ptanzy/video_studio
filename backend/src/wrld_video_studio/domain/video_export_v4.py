from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from wrld_video_studio.domain.canonical_json import canonical_sha256
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.player_overlay import (
    DisplayTrackMetadata,
    ResolvedPlayerConfiguration,
    normalize_display_text,
)
from wrld_video_studio.domain.video_effects_v3 import VideoEffectsV3
from wrld_video_studio.domain.video_export import AlbumIdentity, ExportTarget, VideoTrack, safe_title, validate_portable_path
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


PLAYER_MANIFEST_FORMAT = "wrld-video-album/4.0"
PLAYER_EXPORT_REQUEST_VERSION = "video-export-request/4.0"
PLAYER_EXPORT_RESULT_VERSION = "video-export-result/4.0"
PLAYER_PROFILE_ID = "youtube-1080p30-player-v1"
PLAYER_RENDERER_VERSION = "wu3b-player-export-2"
PLAYER_PRESENTATION_VERSION = "wrld-player-presentation/2.0"


@dataclass(frozen=True, slots=True)
class Measurement:
    value: float | str
    confidence: float
    reliable: bool

    def __post_init__(self) -> None:
        if type(self.value) not in (int, float, str) or type(self.value) is bool:
            raise ValueError("measurement value is invalid")
        if type(self.value) in (int, float) and (not math.isfinite(float(self.value)) or not 1 <= float(self.value) <= 400):
            raise ValueError("BPM measurement is invalid")
        if type(self.value) is str and not self.value.strip():
            raise ValueError("key measurement is invalid")
        if type(self.confidence) not in (int, float) or type(self.confidence) is bool or not math.isfinite(float(self.confidence)) or not 0 <= float(self.confidence) <= 1:
            raise ValueError("measurement confidence is invalid")
        if type(self.reliable) is not bool:
            raise ValueError("measurement reliability is invalid")


@dataclass(frozen=True, slots=True)
class TrackMusicMetadata:
    intended_bpm: float | None = None
    intended_key: str | None = None
    analyzed_bpm: Measurement | None = None
    analyzed_key: Measurement | None = None

    def __post_init__(self) -> None:
        if self.intended_bpm is not None and (type(self.intended_bpm) not in (int, float) or type(self.intended_bpm) is bool or not math.isfinite(float(self.intended_bpm)) or not 1 <= float(self.intended_bpm) <= 400):
            raise ValueError("intended BPM is invalid")
        if self.intended_key is not None and (type(self.intended_key) is not str or not self.intended_key.strip()):
            raise ValueError("intended key is invalid")
        if self.analyzed_bpm is not None and (type(self.analyzed_bpm) is not Measurement or type(self.analyzed_bpm.value) not in (int, float)):
            raise ValueError("analyzed BPM is invalid")
        if self.analyzed_key is not None and (type(self.analyzed_key) is not Measurement or type(self.analyzed_key.value) is not str):
            raise ValueError("analyzed key is invalid")


@dataclass(frozen=True, slots=True)
class PlayerVideoManifest:
    format: str
    album: AlbumIdentity
    parent_channel: str
    genre_channel: str
    background: str
    cover: str | None
    thumbnail: str | None
    tracks: tuple[VideoTrack, ...]
    track_music: Mapping[str, TrackMusicMetadata]
    profile_id: str
    effects: VideoEffectsV3
    source: Mapping[str, Any]

    def track(self, track_id: str) -> VideoTrack:
        for track in self.tracks:
            if track.id == track_id:
                return track
        raise MediaInfrastructureError("TRACK_NOT_FOUND", "The requested track ID is not present in the album manifest.")


@dataclass(frozen=True, slots=True)
class PlayerVideoExportRequest:
    target: ExportTarget
    effects: VideoEffectsV3
    resolved_player: ResolvedPlayerConfiguration
    profile_id: str = PLAYER_PROFILE_ID
    contract_version: str = PLAYER_EXPORT_REQUEST_VERSION

    def __post_init__(self) -> None:
        if type(self.target) is not ExportTarget or type(self.effects) is not VideoEffectsV3 or type(self.resolved_player) is not ResolvedPlayerConfiguration:
            raise ValueError("player request contains invalid values")
        if self.profile_id != PLAYER_PROFILE_ID or self.contract_version != PLAYER_EXPORT_REQUEST_VERSION:
            raise ValueError("unsupported player request")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "target": self.target.to_dict(),
            "profile_id": self.profile_id,
            "effects": self.effects.to_dict(),
            "resolved_player": self.resolved_player.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class PlayerVideoExportPlan:
    manifest: PlayerVideoManifest
    request: PlayerVideoExportRequest
    selected_tracks: tuple[VideoTrack, ...]
    output_relative_path: str
    artifact_kind: str
    effect_config_digest: str


@dataclass(frozen=True, slots=True)
class PlayerVideoExportResult:
    job_id: str
    attempt_id: str
    state: str
    target: ExportTarget
    effects: VideoEffectsV3
    resolved_player: ResolvedPlayerConfiguration
    request_digest: str
    artifacts: tuple[Mapping[str, Any], ...]
    timeline: tuple[Mapping[str, Any], ...]
    warnings: tuple[str, ...]
    started_at: str
    finished_at: str
    profile_id: str = PLAYER_PROFILE_ID
    contract_version: str = PLAYER_EXPORT_RESULT_VERSION

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "contract_version": self.contract_version,
            "job_id": self.job_id,
            "attempt_id": self.attempt_id,
            "state": self.state,
            "target": self.target.to_dict(),
            "profile_id": self.profile_id,
            "effects": self.effects.to_dict(),
            "resolved_player": self.resolved_player.to_dict(),
            "request_digest": self.request_digest,
            "artifacts": [dict(item) for item in self.artifacts],
            "warnings": list(self.warnings),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }
        if self.timeline:
            value["timeline"] = [dict(item) for item in self.timeline]
        return value


def parse_player_manifest(document: Mapping[str, Any]) -> PlayerVideoManifest:
    try:
        _exact_keys(document, {"format", "album", "visual", "tracks", "render"})
        album_value = _object(document["album"], "album")
        visual = _object(document["visual"], "visual")
        render = _object(document["render"], "render")
        _exact_keys(album_value, {"id", "title", "artist", "parent_channel", "genre_channel"})
        _allowed_keys(visual, {"background", "cover", "thumbnail"}, {"background"})
        _exact_keys(render, {"profile_id", "effects"})
        raw_tracks = document["tracks"]
        if not isinstance(raw_tracks, list):
            raise ValueError("tracks must be an array")
        tracks: list[VideoTrack] = []
        music: dict[str, TrackMusicMetadata] = {}
        for raw in raw_tracks:
            item = _object(raw, "track")
            _allowed_keys(item, {"id", "number", "title", "audio", "clips", "music"}, {"id", "number", "title", "audio"})
            track_id = _stable_id(item["id"])
            tracks.append(VideoTrack(track_id, _positive_int(item["number"], "track.number"), _text(item["title"]), validate_portable_path(item["audio"])))
            music[track_id] = _parse_music(item.get("music"))
        manifest = PlayerVideoManifest(
            format=_text(document["format"]),
            album=AlbumIdentity(_stable_id(album_value["id"]), _text(album_value["title"]), _text(album_value["artist"]), _text(album_value["parent_channel"])),
            parent_channel=_text(album_value["parent_channel"]),
            genre_channel=_text(album_value["genre_channel"]),
            background=validate_portable_path(visual["background"]),
            cover=validate_portable_path(visual["cover"]) if "cover" in visual else None,
            thumbnail=validate_portable_path(visual["thumbnail"]) if "thumbnail" in visual else None,
            tracks=tuple(tracks), track_music=music,
            profile_id=_text(render["profile_id"]),
            effects=VideoEffectsV3.from_dict(_object(render["effects"], "effects")),
            source=dict(document),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise MediaInfrastructureError("MANIFEST_INVALID", "The player manifest is incomplete or malformed.") from error
    if manifest.format != PLAYER_MANIFEST_FORMAT or manifest.profile_id != PLAYER_PROFILE_ID:
        raise MediaInfrastructureError("MANIFEST_UNSUPPORTED", "The player manifest version or profile is unsupported.")
    _validate_tracks(manifest.tracks)
    return manifest


def parse_player_export_request(document: Mapping[str, Any]) -> PlayerVideoExportRequest:
    try:
        _exact_keys(document, {"contract_version", "target", "profile_id", "effects", "resolved_player"})
        if document["contract_version"] != PLAYER_EXPORT_REQUEST_VERSION or document["profile_id"] != PLAYER_PROFILE_ID:
            raise ValueError("version or profile")
        return PlayerVideoExportRequest(
            target=_parse_target(_object(document["target"], "target")),
            effects=VideoEffectsV3.from_dict(_object(document["effects"], "effects")),
            resolved_player=ResolvedPlayerConfiguration.from_dict(_object(document["resolved_player"], "resolved_player")),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise MediaInfrastructureError("INVALID_EXPORT_REQUEST", "The player export request is invalid or unsupported.") from error


def resolve_player_export_request(manifest: PlayerVideoManifest, target: ExportTarget, resolved: ResolvedPlayerConfiguration) -> PlayerVideoExportRequest:
    selected = _selected_tracks(manifest, target)
    if tuple(item.track_id for item in resolved.display_tracks) != tuple(item.id for item in selected):
        raise MediaInfrastructureError("INVALID_EXPORT_REQUEST", "Resolved player metadata does not match the selected tracks.")
    return PlayerVideoExportRequest(target, manifest.effects, resolved)


def create_player_plan(manifest: PlayerVideoManifest, request: PlayerVideoExportRequest) -> PlayerVideoExportPlan:
    if request.profile_id != manifest.profile_id or request.effects != manifest.effects:
        raise MediaInfrastructureError("PROFILE_MISMATCH", "The player request does not match the manifest profile and effects.")
    tracks = _selected_tracks(manifest, request.target)
    if tuple(item.track_id for item in request.resolved_player.display_tracks) != tuple(item.id for item in tracks):
        raise MediaInfrastructureError("INVALID_EXPORT_REQUEST", "Resolved metadata does not match the selected timeline.")
    digest = canonical_sha256({
        "effects": request.effects.to_dict(),
        "resolved_player": request.resolved_player.to_dict(),
        "presentation_version": PLAYER_PRESENTATION_VERSION,
    })
    root = f"profiles/{PLAYER_PROFILE_ID}/{digest}"
    if request.target.kind == "album":
        relative, kind = f"{root}/album/{safe_title(manifest.album.title)}.mp4", "album_video"
    else:
        track = tracks[0]
        relative, kind = f"{root}/tracks/{track.number:02d} - {safe_title(track.title)}.mp4", "track_video"
    return PlayerVideoExportPlan(manifest, request, tracks, relative, kind, digest)


def parse_player_export_result(document: Mapping[str, Any]) -> PlayerVideoExportResult:
    try:
        allowed = {
            "contract_version", "job_id", "attempt_id", "state", "target", "profile_id",
            "effects", "resolved_player", "request_digest", "artifacts", "timeline", "warnings",
            "started_at", "finished_at",
        }
        _allowed_keys(document, allowed, allowed - {"timeline"})
        if document["contract_version"] != PLAYER_EXPORT_RESULT_VERSION or document["profile_id"] != PLAYER_PROFILE_ID:
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
        return PlayerVideoExportResult(
            job_id=_text(document["job_id"]),
            attempt_id=_text(document["attempt_id"]),
            state=document["state"],
            target=_parse_target(_object(document["target"], "target")),
            effects=VideoEffectsV3.from_dict(_object(document["effects"], "effects")),
            resolved_player=ResolvedPlayerConfiguration.from_dict(_object(document["resolved_player"], "resolved_player")),
            request_digest=digest,
            artifacts=tuple(_validate_artifact(item) for item in artifacts),
            timeline=tuple(_validate_timeline_entry(item) for item in timeline),
            warnings=tuple(warnings),
            started_at=_date_time(document["started_at"]),
            finished_at=_date_time(document["finished_at"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise MediaInfrastructureError("OUTPUT_INVALID", "The player video-export result is invalid or unsupported.") from error


def resolve_display_metadata(manifest: PlayerVideoManifest, target: ExportTarget) -> tuple[DisplayTrackMetadata, ...]:
    result: list[DisplayTrackMetadata] = []
    for track in _selected_tracks(manifest, target):
        source = manifest.track_music[track.id]
        bpm: str | None = None
        bpm_provenance: str | None = None
        if source.analyzed_bpm is not None and source.analyzed_bpm.reliable:
            value = float(source.analyzed_bpm.value)
            bpm, bpm_provenance = (str(int(value)) if value.is_integer() else f"{value:.1f}"), "analyzed"
        elif source.intended_bpm is not None:
            value = float(source.intended_bpm)
            bpm, bpm_provenance = (str(int(value)) if value.is_integer() else f"{value:.1f}"), "intended"
        key: str | None = None
        key_provenance: str | None = None
        if source.analyzed_key is not None and source.analyzed_key.reliable:
            key, key_provenance = normalize_display_text(str(source.analyzed_key.value)), "analyzed"
        elif source.intended_key is not None:
            key, key_provenance = normalize_display_text(source.intended_key), "intended"
        result.append(DisplayTrackMetadata(
            track.id, normalize_display_text(manifest.album.title), normalize_display_text(track.title),
            bpm, bpm_provenance, key, key_provenance,
            normalize_display_text(manifest.parent_channel), normalize_display_text(manifest.genre_channel),
        ))
    return tuple(result)


def _selected_tracks(manifest: PlayerVideoManifest, target: ExportTarget) -> tuple[VideoTrack, ...]:
    if target.kind == "album":
        return manifest.tracks
    if target.kind == "track" and target.track_id is not None:
        return (manifest.track(target.track_id),)
    raise MediaInfrastructureError("INVALID_EXPORT_REQUEST", "A supported export target is required.")


def _parse_music(value: Any) -> TrackMusicMetadata:
    if value is None:
        return TrackMusicMetadata()
    item = _object(value, "track.music")
    _exact_keys(item, {"intended", "analyzed"})
    intended = _object(item["intended"], "track.music.intended")
    analyzed = _object(item["analyzed"], "track.music.analyzed")
    _exact_keys(intended, {"bpm", "key"})
    _exact_keys(analyzed, {"bpm", "key"})
    return TrackMusicMetadata(
        intended_bpm=intended["bpm"], intended_key=intended["key"],
        analyzed_bpm=_parse_measurement(analyzed["bpm"]), analyzed_key=_parse_measurement(analyzed["key"]),
    )


def _parse_measurement(value: Any) -> Measurement | None:
    if value is None:
        return None
    item = _object(value, "measurement")
    _exact_keys(item, {"value", "confidence", "reliable"})
    return Measurement(item["value"], item["confidence"], item["reliable"])


def _date_time(value: Any) -> str:
    text = _text(value)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return text
