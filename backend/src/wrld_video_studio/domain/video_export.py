from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from wrld_video_studio.domain.media_errors import MediaInfrastructureError


MANIFEST_FORMAT = "wrld-video-album/1.0"
EXPORT_REQUEST_VERSION = "video-export-request/1.0"
EXPORT_RESULT_VERSION = "video-export-result/1.0"
RENDER_REPORT_VERSION = "wrld-render-report/1.0"
PROFILE_ID = "youtube-1080p30-v1"
SAMPLE_RATE = 48_000
CHANNELS = 2
BYTES_PER_SAMPLE_FRAME = 4


@dataclass(frozen=True)
class AlbumIdentity:
    id: str
    title: str
    artist: str
    channel: str


@dataclass(frozen=True)
class VideoTrack:
    id: str
    number: int
    title: str
    audio: str


@dataclass(frozen=True)
class VideoManifest:
    format: str
    album: AlbumIdentity
    background: str
    cover: str | None
    thumbnail: str | None
    tracks: tuple[VideoTrack, ...]
    profile_id: str
    source: Mapping[str, Any]

    def track(self, track_id: str) -> VideoTrack:
        for item in self.tracks:
            if item.id == track_id:
                return item
        raise MediaInfrastructureError(
            "TRACK_NOT_FOUND", "The requested track ID is not present in the album manifest."
        )


@dataclass(frozen=True)
class ExportTarget:
    kind: str
    track_id: str | None = None

    def to_dict(self) -> dict[str, str]:
        value = {"kind": self.kind}
        if self.track_id is not None:
            value["track_id"] = self.track_id
        return value


@dataclass(frozen=True)
class VideoExportRequest:
    target: ExportTarget
    profile_id: str = PROFILE_ID
    contract_version: str = EXPORT_REQUEST_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "target": self.target.to_dict(),
            "profile_id": self.profile_id,
        }


@dataclass(frozen=True)
class TimelineEntry:
    track_id: str
    number: int
    title: str
    start_sample: int
    sample_count: int

    @property
    def display_seconds(self) -> int:
        return self.start_sample // SAMPLE_RATE

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "number": self.number,
            "title": self.title,
            "start_sample": self.start_sample,
            "sample_count": self.sample_count,
            "display_seconds": self.display_seconds,
        }


@dataclass(frozen=True)
class VideoExportPlan:
    manifest: VideoManifest
    request: VideoExportRequest
    selected_tracks: tuple[VideoTrack, ...]
    output_relative_path: str
    artifact_kind: str


def parse_manifest(document: Mapping[str, Any]) -> VideoManifest:
    """Build the semantic model after machine-schema validation."""
    try:
        _exact_keys(document, {"format", "album", "visual", "tracks", "render"})
        album_value = document["album"]
        visual = document["visual"]
        render = document["render"]
        raw_tracks = document["tracks"]
        _exact_keys(album_value, {"id", "title", "artist", "channel"})
        _allowed_keys(visual, {"background", "cover", "thumbnail"}, {"background"})
        _exact_keys(render, {"profile_id"})
        for item in raw_tracks:
            _allowed_keys(
                item,
                {"id", "number", "title", "audio", "clips"},
                {"id", "number", "title", "audio"},
            )
        album = AlbumIdentity(
            id=_text(album_value["id"]),
            title=_text(album_value["title"]),
            artist=_text(album_value["artist"]),
            channel=_text(album_value["channel"]),
        )
        tracks = tuple(
            VideoTrack(
                id=_text(item["id"]),
                number=int(item["number"]),
                title=_text(item["title"]),
                audio=validate_portable_path(item["audio"]),
            )
            for item in raw_tracks
        )
        manifest = VideoManifest(
            format=_text(document["format"]),
            album=album,
            background=validate_portable_path(visual["background"]),
            cover=(validate_portable_path(visual["cover"]) if "cover" in visual else None),
            thumbnail=(
                validate_portable_path(visual["thumbnail"])
                if "thumbnail" in visual
                else None
            ),
            tracks=tracks,
            profile_id=_text(render["profile_id"]),
            source=dict(document),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise MediaInfrastructureError(
            "MANIFEST_INVALID", "The video manifest is incomplete or malformed."
        ) from error
    if manifest.format != MANIFEST_FORMAT or manifest.profile_id != PROFILE_ID:
        raise MediaInfrastructureError(
            "MANIFEST_UNSUPPORTED", "The video manifest version or render profile is unsupported."
        )
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
    return manifest


def parse_export_request(document: Mapping[str, Any]) -> VideoExportRequest:
    try:
        _exact_keys(document, {"contract_version", "target", "profile_id"})
        if document["contract_version"] != EXPORT_REQUEST_VERSION:
            raise ValueError("version")
        if document["profile_id"] != PROFILE_ID:
            raise ValueError("profile")
        raw_target = document["target"]
        kind = raw_target["kind"]
        if kind == "album" and set(raw_target) == {"kind"}:
            target = ExportTarget("album")
        elif kind == "track" and set(raw_target) == {"kind", "track_id"}:
            target = ExportTarget("track", _text(raw_target["track_id"]))
        else:
            raise ValueError("target")
        return VideoExportRequest(target=target)
    except (KeyError, TypeError, ValueError) as error:
        raise MediaInfrastructureError(
            "INVALID_EXPORT_REQUEST", "The video-export request is invalid or unsupported."
        ) from error


def create_plan(manifest: VideoManifest, request: VideoExportRequest) -> VideoExportPlan:
    if request.profile_id != manifest.profile_id:
        raise MediaInfrastructureError(
            "PROFILE_MISMATCH", "The request profile does not match the manifest profile."
        )
    if request.target.kind == "album":
        tracks = manifest.tracks
        relative = f"album/{safe_title(manifest.album.title)}.mp4"
        kind = "album_video"
    else:
        if request.target.track_id is None:
            raise MediaInfrastructureError("INVALID_EXPORT_REQUEST", "A track ID is required.")
        track = manifest.track(request.target.track_id)
        tracks = (track,)
        relative = f"tracks/{track.number:02d} - {safe_title(track.title)}.mp4"
        kind = "track_video"
    return VideoExportPlan(manifest, request, tracks, relative, kind)


def build_timeline(
    tracks: tuple[VideoTrack, ...], sample_counts: tuple[int, ...]
) -> tuple[TimelineEntry, ...]:
    if len(tracks) != len(sample_counts) or not tracks:
        raise MediaInfrastructureError("TIMELINE_INVALID", "Timeline inputs are inconsistent.")
    entries: list[TimelineEntry] = []
    start = 0
    for track, count in zip(tracks, sample_counts, strict=True):
        if type(count) is not int or count <= 0:
            raise MediaInfrastructureError(
                "TIMELINE_INVALID", "Normalized audio must contain positive sample frames."
            )
        entries.append(TimelineEntry(track.id, track.number, track.title, start, count))
        start += count
    return tuple(entries)


def chapters_text(timeline: tuple[TimelineEntry, ...]) -> str:
    lines = []
    for entry in timeline:
        seconds = entry.display_seconds
        hours, remainder = divmod(seconds, 3600)
        minutes, second = divmod(remainder, 60)
        timestamp = (
            f"{hours}:{minutes:02d}:{second:02d}"
            if hours
            else f"{minutes:02d}:{second:02d}"
        )
        title = re.sub(r"[\r\n]+", " ", entry.title)
        lines.append(f"{timestamp} {title}")
    return "\n".join(lines) + "\n"


def validate_portable_path(value: Any) -> str:
    text = _text(value)
    posix = PurePosixPath(text)
    windows = PureWindowsPath(text)
    if (
        "\\" in text
        or posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or not posix.parts
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        raise ValueError("path must be a portable project-relative POSIX path")
    return posix.as_posix()


def safe_title(value: str) -> str:
    text = unicodedata.normalize("NFC", value).strip()
    text = re.sub(r"[\x00-\x1f\x7f<>:\"/\\|?*]", "_", text)
    text = re.sub(r"\s+", " ", text).rstrip(" .")
    if not text or text.casefold() in {
        "con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }:
        raise MediaInfrastructureError("INVALID_OUTPUT_NAME", "Title cannot form a safe filename.")
    return text


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("expected a nonempty trimmed string")
    value.encode("utf-8", errors="strict")
    return value


def _exact_keys(value: Any, expected: set[str]) -> None:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError("object fields do not match the contract")


def _allowed_keys(value: Any, allowed: set[str], required: set[str]) -> None:
    if (
        not isinstance(value, Mapping)
        or not required.issubset(value)
        or not set(value).issubset(allowed)
    ):
        raise ValueError("object fields do not match the contract")
