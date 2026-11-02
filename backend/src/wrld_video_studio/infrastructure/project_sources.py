from __future__ import annotations

import json
import hashlib
import os
import stat
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.video_export import VideoManifest, parse_manifest
from wrld_video_studio.domain.video_export_v2 import (
    MOTION_MANIFEST_FORMAT,
    MotionVideoManifest,
    parse_motion_manifest,
)
from wrld_video_studio.domain.video_export_v3 import (
    REFINED_MANIFEST_FORMAT,
    RefinedVideoManifest,
    parse_refined_manifest,
)
from wrld_video_studio.domain.player_overlay import (
    ResolvedPlayerConfiguration,
    TrueTypeFontMetrics,
    fixed_metadata_text,
    resolve_player_layout,
    track_metadata_text,
)
from wrld_video_studio.domain.video_export_v4 import (
    PLAYER_MANIFEST_FORMAT,
    PlayerVideoManifest,
    parse_player_manifest,
    resolve_display_metadata,
)


@dataclass(frozen=True)
class FilesystemVideoProject:
    root: Path
    manifest: VideoManifest | MotionVideoManifest | RefinedVideoManifest | PlayerVideoManifest
    manifest_document: Mapping[str, Any]
    resolved_player: ResolvedPlayerConfiguration | None = None
    normalized_sample_counts: tuple[int, ...] | None = None


class FilesystemVideoProjectLoader:
    def __init__(
        self,
        manifest_schema: str | Path | tuple[str | Path, ...],
        *,
        prober: Any = None,
        theme_resolver: Any = None,
    ) -> None:
        try:
            paths = (
                tuple(Path(item) for item in manifest_schema)
                if isinstance(manifest_schema, tuple)
                else (Path(manifest_schema),)
            )
            schema_dir = paths[0].parent
            resources = []
            for path in schema_dir.glob("*.schema.json"):
                document = json.loads(path.read_text(encoding="utf-8"))
                if "$id" in document:
                    resources.append((document["$id"], Resource.from_contents(document)))
            registry = Registry().with_resources(resources)
            validators: dict[str, Draft202012Validator] = {}
            for path in paths:
                schema = json.loads(path.read_text(encoding="utf-8"))
                Draft202012Validator.check_schema(schema)
                manifest_format = schema["properties"]["format"]["const"]
                validators[manifest_format] = Draft202012Validator(
                    schema,
                    registry=registry,
                    format_checker=FormatChecker(),
                )
        except (OSError, json.JSONDecodeError, TypeError) as error:
            raise MediaInfrastructureError(
                "SCHEMA_INVALID", "The video-manifest schema could not be loaded."
            ) from error
        self._validators = validators
        self._prober = prober
        self._theme_resolver = theme_resolver

    def load(self, album_project: str | Path) -> FilesystemVideoProject:
        supplied = Path(album_project).expanduser()
        if not supplied.is_absolute():
            raise MediaInfrastructureError(
                "PROJECT_PATH_INVALID", "The album-project path must be absolute."
            )
        try:
            root = supplied.resolve(strict=True)
        except OSError as error:
            raise MediaInfrastructureError(
                "PROJECT_NOT_FOUND", "The album-project directory does not exist."
            ) from error
        if not root.is_dir() or self._is_reparse(root):
            raise MediaInfrastructureError(
                "PROJECT_PATH_INVALID", "The album-project path must be a regular directory."
            )
        output = root / "output"
        if output.exists() and (not output.is_dir() or self._is_reparse(output)):
            raise MediaInfrastructureError(
                "INVALID_OUTPUT_PATH", "The project output path must be a regular directory."
            )
        manifest_path = self._resolve_source(root, "video_manifest.json")
        try:
            document = json.loads(
                manifest_path.read_text(encoding="utf-8"),
                parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
                object_pairs_hook=self._unique_object,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise MediaInfrastructureError(
                "MANIFEST_INVALID", "The video manifest is not valid UTF-8 JSON."
            ) from error
        if not isinstance(document, dict):
            raise MediaInfrastructureError("MANIFEST_INVALID", "The video manifest must be an object.")
        validator = self._validators.get(document.get("format"))
        if validator is None:
            raise MediaInfrastructureError(
                "MANIFEST_UNSUPPORTED", "The video manifest version is unsupported."
            )
        errors = sorted(validator.iter_errors(document), key=lambda item: list(item.path))
        if errors:
            first = errors[0]
            location = "$" + "".join(
                f"[{part}]" if isinstance(part, int) else f".{part}" for part in first.path
            )
            raise MediaInfrastructureError(
                "MANIFEST_SCHEMA_INVALID",
                "The video manifest does not satisfy the approved schema.",
                {"property_path": location, "reason": first.message},
            )
        if document["format"] == PLAYER_MANIFEST_FORMAT:
            manifest = parse_player_manifest(document)
        elif document["format"] == REFINED_MANIFEST_FORMAT:
            manifest = parse_refined_manifest(document)
        elif document["format"] == MOTION_MANIFEST_FORMAT:
            manifest = parse_motion_manifest(document)
        else:
            manifest = parse_manifest(document)
        sample_counts = self._validate_media(root, manifest)
        resolved_player = self._resolve_player(root, manifest) if isinstance(manifest, PlayerVideoManifest) else None
        return FilesystemVideoProject(root, manifest, document, resolved_player, sample_counts)

    def _validate_media(
        self,
        root: Path,
        manifest: VideoManifest | MotionVideoManifest | RefinedVideoManifest | PlayerVideoManifest,
    ) -> tuple[int, ...] | None:
        artwork = [manifest.background]
        artwork.extend(item for item in (manifest.cover, manifest.thumbnail) if item is not None)
        for relative in artwork:
            path = self._resolve_source(root, relative)
            if path.suffix.casefold() not in {".png", ".jpg", ".jpeg"}:
                raise MediaInfrastructureError(
                    "UNSUPPORTED_IMAGE", "Artwork must use a supported PNG or JPEG format."
                )
            if self._prober is not None:
                probe = self._prober.probe(path)
                if not any(
                    stream.codec_type == "video" and stream.width and stream.height
                    for stream in probe.streams
                ):
                    raise MediaInfrastructureError(
                        "UNSUPPORTED_IMAGE", "Artwork does not contain a decodable image stream."
                    )
        sample_counts: list[int] = []
        for track in manifest.tracks:
            path = self._resolve_source(root, track.audio)
            if path.suffix.casefold() != ".wav":
                raise MediaInfrastructureError(
                    "UNSUPPORTED_AUDIO", "WU3A source audio must use WAV format."
                )
            if self._prober is not None:
                probe = self._prober.probe(path)
                audio_streams = tuple(stream for stream in probe.streams if stream.codec_type == "audio")
                if probe.duration_seconds is None or not audio_streams:
                    raise MediaInfrastructureError(
                        "UNSUPPORTED_AUDIO", "A WAV source has no decodable positive-duration audio."
                    )
                stream = audio_streams[0]
                if (
                    stream.duration_ts is not None
                    and stream.duration_ts > 0
                    and stream.time_base_numerator is not None
                    and stream.time_base_denominator is not None
                ):
                    normalized = Fraction(
                        stream.duration_ts * stream.time_base_numerator * 48000,
                        stream.time_base_denominator,
                    )
                    count = (normalized.numerator + normalized.denominator // 2) // normalized.denominator
                else:
                    count = round(float(probe.duration_seconds) * 48000)
                if count <= 0:
                    raise MediaInfrastructureError(
                        "UNSUPPORTED_AUDIO", "A WAV source has no positive normalized sample timeline."
                    )
                sample_counts.append(count)
        return tuple(sample_counts) if self._prober is not None else None

    def _resolve_player(
        self, root: Path, manifest: PlayerVideoManifest
    ) -> ResolvedPlayerConfiguration:
        if self._theme_resolver is None:
            raise MediaInfrastructureError(
                "THEME_ANALYSIS_UNAVAILABLE",
                "The player profile requires the configured artwork theme resolver.",
            )
        assert manifest.effects.player is not None
        player = manifest.effects.player
        font_path = self._resolve_source(root, player.font.path)
        try:
            font_bytes = font_path.read_bytes()
            font_metrics = TrueTypeFontMetrics(font_bytes)
        except (OSError, ValueError) as error:
            raise MediaInfrastructureError(
                "FONT_INVALID", "The configured player font is unavailable or unsupported."
            ) from error
        font_sha256 = hashlib.sha256(font_bytes).hexdigest()
        bars = manifest.effects.audio_bars
        try:
            layout = resolve_player_layout(
                footer_height=player.footer.height_px,
                visualizer_width=bars.zone_width_px,
                visualizer_height=bars.zone_height_px,
                visualizer_gap=bars.gap_px,
                glow_enabled=bars.glow.enabled and bars.glow.intensity > 0,
                placement=bars.placement,
                horizontal_offset=bars.horizontal_offset_px,
                bottom_margin=bars.bottom_margin_px,
            )
        except ValueError as error:
            raise MediaInfrastructureError(
                "PLAYER_LAYOUT_INVALID", "The player layout contains overlapping or unsafe regions."
            ) from error
        background = self._resolve_source(root, manifest.background)
        theme = self._theme_resolver.resolve(
            background,
            player.theme,
            footer_opacity=player.footer.opacity,
        )
        from wrld_video_studio.domain.video_export import ExportTarget
        display_tracks = resolve_display_metadata(manifest, ExportTarget("album"))
        rendered_text = "".join(
            text
            for item in display_tracks
            for text in (*fixed_metadata_text(item), track_metadata_text(item), item.track_title)
        ) + "0123456789:…"
        missing = font_metrics.missing_codepoints(rendered_text)
        if missing:
            raise MediaInfrastructureError(
                "FONT_GLYPH_MISSING",
                "The configured player font does not support all required rendered characters.",
                {"codepoints": [f"U+{value:04X}" for value in missing]},
            )
        return ResolvedPlayerConfiguration(
            layout=layout,
            theme=theme,
            font_sha256=font_sha256,
            display_tracks=display_tracks,
        )

    def _resolve_source(self, root: Path, relative: str) -> Path:
        parts = tuple(relative.split("/"))
        if not parts or parts[0].casefold() == "output":
            raise MediaInfrastructureError(
                "INVALID_INPUT_PATH", "Source paths may not target the generated output tree."
            )
        candidate = root
        for part in parts:
            candidate = candidate / part
            if candidate.exists() and self._is_reparse(candidate):
                raise MediaInfrastructureError(
                    "INVALID_INPUT_PATH", "Source paths may not traverse links or reparse points."
                )
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError) as error:
            raise MediaInfrastructureError(
                "ASSET_NOT_FOUND", "A manifest source file is missing or outside the project."
            ) from error
        if not resolved.is_file() or self._is_reparse(resolved):
            raise MediaInfrastructureError(
                "INVALID_INPUT_PATH", "Manifest sources must be regular project files."
            )
        return resolved

    @staticmethod
    def _is_reparse(path: Path) -> bool:
        try:
            info = path.lstat()
        except OSError:
            return False
        if stat.S_ISLNK(info.st_mode):
            return True
        attributes = getattr(info, "st_file_attributes", 0)
        return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))

    @staticmethod
    def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON object key")
            value[key] = item
        return value
