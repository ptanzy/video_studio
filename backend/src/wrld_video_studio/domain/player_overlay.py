from __future__ import annotations

import math
import struct
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from wrld_video_studio.domain.canonical_json import canonical_sha256
from wrld_video_studio.domain.video_export import SAMPLE_RATE, TimelineEntry, validate_portable_path
from wrld_video_studio.domain.visual_refinement import normalize_hex


PLAYER_OVERLAY_VERSION = "player-overlay/1.0"
PALETTE_ALGORITHM_VERSION = "wrld-artwork-palette/1.0"
LAYOUT_VERSION = "wrld-player-layout/1.0"
CANVAS_WIDTH = 1920
CANVAS_HEIGHT = 1080
SAFE_MARGIN = 64
GLOW_PADDING_PX = 36
MIN_GLOW_FOOTER_GAP_PX = 32
THEME_MODES = frozenset({"automatic", "manual", "hybrid"})
THEME_PRESETS = frozenset({"subtle", "balanced", "vibrant"})
PROGRESS_MODES = frozenset({"track", "album"})
METADATA_POLICIES = frozenset({"prefer_reliable_analyzed_then_intended"})


@dataclass(frozen=True, slots=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


@dataclass(frozen=True, slots=True)
class FooterSettings:
    enabled: bool = True
    height_px: int = 110
    background_color: str = "#101827"
    opacity: float = 0.65

    def __post_init__(self) -> None:
        _boolean(self.enabled, "footer.enabled")
        _integer(self.height_px, 80, 180, "footer.height_px")
        object.__setattr__(self, "background_color", normalize_hex(self.background_color))
        object.__setattr__(self, "opacity", _number(self.opacity, 0.10, 1.0, "footer.opacity"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "height_px": self.height_px,
            "background_color": self.background_color,
            "opacity": self.opacity,
        }


@dataclass(frozen=True, slots=True)
class PlayerProgressSettings:
    enabled: bool = True
    mode: str = "album"
    thickness_px: int = 6
    fill_opacity: float = 0.80
    rail_opacity: float = 0.35

    def __post_init__(self) -> None:
        _boolean(self.enabled, "progress.enabled")
        _enum(self.mode, PROGRESS_MODES, "progress.mode")
        _integer(self.thickness_px, 2, 16, "progress.thickness_px")
        object.__setattr__(self, "fill_opacity", _number(self.fill_opacity, 0.10, 1.0, "progress.fill_opacity"))
        object.__setattr__(self, "rail_opacity", _number(self.rail_opacity, 0.10, 1.0, "progress.rail_opacity"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "thickness_px": self.thickness_px,
            "fill_opacity": self.fill_opacity,
            "rail_opacity": self.rail_opacity,
        }


@dataclass(frozen=True, slots=True)
class MetadataSettings:
    enabled: bool = True
    bpm_key_policy: str = "prefer_reliable_analyzed_then_intended"
    transition_seconds: float = 6.0

    def __post_init__(self) -> None:
        _boolean(self.enabled, "metadata.enabled")
        _enum(self.bpm_key_policy, METADATA_POLICIES, "metadata.bpm_key_policy")
        if self.transition_seconds != 6.0:
            raise ValueError("metadata.transition_seconds must be 6.0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "bpm_key_policy": self.bpm_key_policy,
            "transition_seconds": self.transition_seconds,
        }


@dataclass(frozen=True, slots=True)
class AnnouncementSettings:
    enabled: bool = False
    fade_in_seconds: float = 0.5
    hold_seconds: float = 2.0
    fade_out_seconds: float = 0.5

    def __post_init__(self) -> None:
        _boolean(self.enabled, "announcement.enabled")
        object.__setattr__(self, "fade_in_seconds", _number(self.fade_in_seconds, 0.1, 2.0, "announcement.fade_in_seconds"))
        object.__setattr__(self, "hold_seconds", _number(self.hold_seconds, 0.0, 10.0, "announcement.hold_seconds"))
        object.__setattr__(self, "fade_out_seconds", _number(self.fade_out_seconds, 0.1, 2.0, "announcement.fade_out_seconds"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "fade_in_seconds": self.fade_in_seconds,
            "hold_seconds": self.hold_seconds,
            "fade_out_seconds": self.fade_out_seconds,
        }


@dataclass(frozen=True, slots=True)
class FontSettings:
    path: str
    metadata_size_px: int = 22
    timer_size_px: int = 20
    announcement_size_px: int = 36

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", validate_portable_path(self.path))
        if not self.path.casefold().endswith((".ttf", ".otf")):
            raise ValueError("font.path must identify a TTF or OTF file")
        _integer(self.metadata_size_px, 16, 32, "font.metadata_size_px")
        _integer(self.timer_size_px, 14, 28, "font.timer_size_px")
        _integer(self.announcement_size_px, 24, 64, "font.announcement_size_px")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "metadata_size_px": self.metadata_size_px,
            "timer_size_px": self.timer_size_px,
            "announcement_size_px": self.announcement_size_px,
        }


@dataclass(frozen=True, slots=True)
class ThemeOverrides:
    footer_background: str | None = "#101827"
    primary_text: str | None = None
    secondary_text: str | None = None
    progress_fill: str | None = None
    progress_rail: str | None = None
    visualizer: str | None = None

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, normalize_hex(value))

    def to_dict(self) -> dict[str, str | None]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class ThemeSettings:
    mode: str = "hybrid"
    preset: str = "subtle"
    overrides: ThemeOverrides = field(default_factory=ThemeOverrides)

    def __post_init__(self) -> None:
        _enum(self.mode, THEME_MODES, "theme.mode")
        _enum(self.preset, THEME_PRESETS, "theme.preset")
        if type(self.overrides) is not ThemeOverrides:
            raise ValueError("theme.overrides must be ThemeOverrides")
        if self.mode == "manual" and any(value is None for value in self.overrides.to_dict().values()):
            raise ValueError("manual themes require every color override")

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "preset": self.preset, "overrides": self.overrides.to_dict()}


@dataclass(frozen=True, slots=True)
class PlayerOverlaySettings:
    font: FontSettings
    footer: FooterSettings = field(default_factory=FooterSettings)
    progress: PlayerProgressSettings = field(default_factory=PlayerProgressSettings)
    metadata: MetadataSettings = field(default_factory=MetadataSettings)
    announcement: AnnouncementSettings = field(default_factory=AnnouncementSettings)
    theme: ThemeSettings = field(default_factory=ThemeSettings)
    contract_version: str = PLAYER_OVERLAY_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != PLAYER_OVERLAY_VERSION:
            raise ValueError("unsupported player overlay version")
        expected = (FontSettings, FooterSettings, PlayerProgressSettings, MetadataSettings, AnnouncementSettings, ThemeSettings)
        if tuple(type(value) for value in (self.font, self.footer, self.progress, self.metadata, self.announcement, self.theme)) != expected:
            raise ValueError("player overlay settings contain invalid values")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "font": self.font.to_dict(),
            "footer": self.footer.to_dict(),
            "progress": self.progress.to_dict(),
            "metadata": self.metadata.to_dict(),
            "announcement": self.announcement.to_dict(),
            "theme": self.theme.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PlayerOverlaySettings":
        _keys(value, {"contract_version", "font", "footer", "progress", "metadata", "announcement", "theme"}, "player")
        theme = _object(value["theme"], "theme")
        _keys(theme, {"mode", "preset", "overrides"}, "theme")
        overrides = _object(theme["overrides"], "theme.overrides")
        _keys(overrides, set(ThemeOverrides.__dataclass_fields__), "theme.overrides")
        return cls(
            contract_version=value["contract_version"],
            font=FontSettings(**_exact_dataclass(value["font"], FontSettings, "font")),
            footer=FooterSettings(**_exact_dataclass(value["footer"], FooterSettings, "footer")),
            progress=PlayerProgressSettings(**_exact_dataclass(value["progress"], PlayerProgressSettings, "progress")),
            metadata=MetadataSettings(**_exact_dataclass(value["metadata"], MetadataSettings, "metadata")),
            announcement=AnnouncementSettings(**_exact_dataclass(value["announcement"], AnnouncementSettings, "announcement")),
            theme=ThemeSettings(mode=theme["mode"], preset=theme["preset"], overrides=ThemeOverrides(**overrides)),
        )


@dataclass(frozen=True, slots=True)
class ResolvedTheme:
    artwork_sha256: str
    palette_algorithm_version: str
    mode: str
    preset: str
    dominant_color: str
    footer_background: str
    primary_text: str
    secondary_text: str
    progress_fill: str
    progress_rail: str
    visualizer: str
    provenance: Mapping[str, str]

    def __post_init__(self) -> None:
        _sha256(self.artwork_sha256, "artwork_sha256")
        if self.palette_algorithm_version != PALETTE_ALGORITHM_VERSION:
            raise ValueError("unsupported palette algorithm")
        _enum(self.mode, THEME_MODES, "theme mode")
        _enum(self.preset, THEME_PRESETS, "theme preset")
        for name in ("dominant_color", "footer_background", "primary_text", "secondary_text", "progress_fill", "progress_rail", "visualizer"):
            object.__setattr__(self, name, normalize_hex(getattr(self, name)))
        expected = {"footer_background", "primary_text", "secondary_text", "progress_fill", "progress_rail", "visualizer"}
        if set(self.provenance) != expected or any(value not in {"artwork", "manual", "derived"} for value in self.provenance.values()):
            raise ValueError("resolved theme provenance is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "artwork_sha256": self.artwork_sha256,
            "palette_algorithm_version": self.palette_algorithm_version,
            "mode": self.mode,
            "preset": self.preset,
            "dominant_color": self.dominant_color,
            "colors": {name: getattr(self, name) for name in ("footer_background", "primary_text", "secondary_text", "progress_fill", "progress_rail", "visualizer")},
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ResolvedTheme":
        _keys(value, {"artwork_sha256", "palette_algorithm_version", "mode", "preset", "dominant_color", "colors", "provenance"}, "resolved_theme")
        colors = _object(value["colors"], "resolved_theme.colors")
        color_fields = {"footer_background", "primary_text", "secondary_text", "progress_fill", "progress_rail", "visualizer"}
        _keys(colors, color_fields, "resolved_theme.colors")
        return cls(
            artwork_sha256=value["artwork_sha256"], palette_algorithm_version=value["palette_algorithm_version"],
            mode=value["mode"], preset=value["preset"], dominant_color=value["dominant_color"],
            provenance=dict(_object(value["provenance"], "resolved_theme.provenance")), **colors,
        )


@dataclass(frozen=True, slots=True)
class ResolvedPlayerLayout:
    safe_area: Rect
    footer: Rect
    progress_row: Rect
    metadata_row: Rect
    visualizer: Rect
    visualizer_glow: Rect
    announcement: Rect
    layout_version: str = LAYOUT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {"layout_version": self.layout_version, **{name: getattr(self, name).to_dict() for name in ("safe_area", "footer", "progress_row", "metadata_row", "visualizer", "visualizer_glow", "announcement")}}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ResolvedPlayerLayout":
        fields = {"layout_version", "safe_area", "footer", "progress_row", "metadata_row", "visualizer", "visualizer_glow", "announcement"}
        _keys(value, fields, "layout")
        if value["layout_version"] != LAYOUT_VERSION:
            raise ValueError("unsupported layout version")
        return cls(layout_version=value["layout_version"], **{name: Rect(**_exact_dataclass(value[name], Rect, name)) for name in fields - {"layout_version"}})


@dataclass(frozen=True, slots=True)
class DisplayTrackMetadata:
    track_id: str
    album_title: str
    track_title: str
    bpm: str | None
    bpm_provenance: str | None
    musical_key: str | None
    key_provenance: str | None
    parent_channel: str
    genre_channel: str

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DisplayTrackMetadata":
        return cls(**_exact_dataclass(value, cls, "display metadata"))


@dataclass(frozen=True, slots=True)
class ResolvedPlayerConfiguration:
    layout: ResolvedPlayerLayout
    theme: ResolvedTheme
    font_sha256: str
    display_tracks: tuple[DisplayTrackMetadata, ...]

    def __post_init__(self) -> None:
        _sha256(self.font_sha256, "font_sha256")

    def to_dict(self) -> dict[str, Any]:
        return {"layout": self.layout.to_dict(), "theme": self.theme.to_dict(), "font_sha256": self.font_sha256, "display_tracks": [item.to_dict() for item in self.display_tracks]}

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ResolvedPlayerConfiguration":
        _keys(value, {"layout", "theme", "font_sha256", "display_tracks"}, "resolved_player")
        tracks = value["display_tracks"]
        if not isinstance(tracks, list):
            raise ValueError("display_tracks must be an array")
        return cls(
            layout=ResolvedPlayerLayout.from_dict(_object(value["layout"], "layout")),
            theme=ResolvedTheme.from_dict(_object(value["theme"], "theme")),
            font_sha256=value["font_sha256"],
            display_tracks=tuple(DisplayTrackMetadata.from_dict(_object(item, "display track")) for item in tracks),
        )


def resolve_player_layout(
    *,
    footer_height: int,
    visualizer_width: int,
    visualizer_height: int,
    visualizer_gap: int,
    glow_enabled: bool,
    placement: str = "bottom_center",
    horizontal_offset: int = 0,
    bottom_margin: int = 242,
) -> ResolvedPlayerLayout:
    safe = Rect(SAFE_MARGIN, SAFE_MARGIN, CANVAS_WIDTH - 2 * SAFE_MARGIN, CANVAS_HEIGHT - 2 * SAFE_MARGIN)
    footer = Rect(safe.x, safe.bottom - footer_height, safe.width, footer_height)
    progress = Rect(footer.x + 12, footer.y + 12, footer.width - 24, 30)
    metadata = Rect(footer.x + 12, footer.y + 58, footer.width - 24, 36)
    glow = GLOW_PADDING_PX if glow_enabled else 0
    if placement == "bottom_left":
        visualizer_x = safe.x
    elif placement == "bottom_center":
        visualizer_x = safe.x + (safe.width - visualizer_width) // 2
    elif placement == "bottom_right":
        visualizer_x = safe.right - visualizer_width
    else:
        raise ValueError("visualizer placement is unsupported")
    visualizer = Rect(
        visualizer_x + horizontal_offset,
        CANVAS_HEIGHT - bottom_margin - visualizer_height,
        visualizer_width,
        visualizer_height,
    )
    visualizer_glow = Rect(visualizer.x - glow, visualizer.y - glow, visualizer.width + 2 * glow, visualizer.height + 2 * glow)
    announcement = Rect(safe.x + 240, visualizer_glow.y - 88, safe.width - 480, 64)
    for name, rect in (("footer", footer), ("progress", progress), ("metadata", metadata), ("visualizer glow", visualizer_glow), ("announcement", announcement)):
        if rect.x < safe.x or rect.y < safe.y or rect.right > safe.right or rect.bottom > safe.bottom:
            raise ValueError(f"{name} is outside the safe area")
    if footer.y - visualizer_glow.bottom < MIN_GLOW_FOOTER_GAP_PX:
        raise ValueError("visualizer glow is too close to the footer")
    if visualizer_gap < 0:
        raise ValueError("visualizer gap is invalid")
    return ResolvedPlayerLayout(safe, footer, progress, metadata, visualizer, visualizer_glow, announcement)


def progress_fraction(timeline: Sequence[TimelineEntry], presentation_sample: int, mode: str) -> float:
    _enum(mode, PROGRESS_MODES, "progress mode")
    if not timeline:
        raise ValueError("timeline must not be empty")
    total = timeline[-1].start_sample + timeline[-1].sample_count
    sample = min(max(presentation_sample, 0), total)
    if mode == "album":
        return sample / total
    entry = next((item for item in timeline if item.start_sample <= sample < item.start_sample + item.sample_count), timeline[-1])
    return min(max((sample - entry.start_sample) / entry.sample_count, 0.0), 1.0)


def format_timeline_time(sample: int, total_samples: int) -> str:
    if type(sample) is not int or type(total_samples) is not int or sample < 0 or total_samples < 1:
        raise ValueError("timeline samples are invalid")
    seconds = min(sample, total_samples) // SAMPLE_RATE
    total_seconds = total_samples // SAMPLE_RATE
    if total_seconds >= 3600:
        return f"{seconds // 3600:02d}:{(seconds // 60) % 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class TrueTypeFontMetrics:
    """Dependency-free advance-width reader for deterministic TTF/OTF layout."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        tables = self._tables(data)
        self.units_per_em = self._u16(tables["head"] + 18)
        metrics = self._u16(tables["hhea"] + 34)
        glyphs = self._u16(tables["maxp"] + 4)
        hmtx = tables["hmtx"]
        advances = [self._u16(hmtx + index * 4) for index in range(metrics)]
        self._advances = tuple(advances + [advances[-1]] * (glyphs - metrics))
        self._cmap = self._select_cmap(tables["cmap"])

    def width(self, text: str, size_px: int) -> float:
        return sum(self._advances[min(self._glyph(ord(char)), len(self._advances) - 1)] for char in text) * size_px / self.units_per_em

    def truncate(self, text: str, size_px: int, max_width: float) -> str:
        if self.width(text, size_px) <= max_width:
            return text
        ellipsis = "…"
        budget = max_width - self.width(ellipsis, size_px)
        if budget <= 0:
            return ellipsis
        result: list[str] = []
        current = 0.0
        for char in text:
            width = self.width(char, size_px)
            if current + width > budget:
                break
            result.append(char)
            current += width
        return "".join(result).rstrip() + ellipsis

    def missing_codepoints(self, text: str) -> tuple[int, ...]:
        return tuple(sorted({ord(char) for char in text if self._glyph(ord(char)) == 0}))

    def supports(self, text: str) -> bool:
        return not self.missing_codepoints(text)

    @staticmethod
    def _tables(data: bytes) -> dict[str, int]:
        if len(data) < 12:
            raise ValueError("font is truncated")
        count = struct.unpack_from(">H", data, 4)[0]
        result: dict[str, int] = {}
        for index in range(count):
            offset = 12 + index * 16
            tag, _checksum, table_offset, length = struct.unpack_from(">4sIII", data, offset)
            if table_offset + length > len(data):
                raise ValueError("font table is truncated")
            result[tag.decode("ascii")] = table_offset
        for required in ("head", "hhea", "maxp", "hmtx", "cmap"):
            if required not in result:
                raise ValueError(f"font lacks {required}")
        return result

    def _select_cmap(self, offset: int) -> tuple[int, int]:
        count = self._u16(offset + 2)
        choices: list[tuple[int, int, int]] = []
        for index in range(count):
            platform, encoding, relative = struct.unpack_from(">HHI", self._data, offset + 4 + index * 8)
            subtable = offset + relative
            fmt = self._u16(subtable)
            priority = 3 if (platform, encoding, fmt) == (3, 10, 12) else 2 if platform == 3 and fmt in {4, 12} else 1 if fmt in {4, 12} else 0
            choices.append((priority, fmt, subtable))
        priority, fmt, subtable = max(choices, default=(0, 0, 0))
        if not priority:
            raise ValueError("font has no supported Unicode cmap")
        return fmt, subtable

    def _glyph(self, codepoint: int) -> int:
        fmt, offset = self._cmap
        if fmt == 12:
            count = struct.unpack_from(">I", self._data, offset + 12)[0]
            for index in range(count):
                start, end, glyph = struct.unpack_from(">III", self._data, offset + 16 + index * 12)
                if start <= codepoint <= end:
                    return glyph + codepoint - start
            return 0
        if codepoint > 0xFFFF:
            return 0
        seg_count = self._u16(offset + 6) // 2
        ends = offset + 14
        starts = ends + 2 * seg_count + 2
        deltas = starts + 2 * seg_count
        ranges = deltas + 2 * seg_count
        for index in range(seg_count):
            end = self._u16(ends + 2 * index)
            start = self._u16(starts + 2 * index)
            if start <= codepoint <= end:
                delta = struct.unpack_from(">h", self._data, deltas + 2 * index)[0]
                range_offset = self._u16(ranges + 2 * index)
                if range_offset == 0:
                    return (codepoint + delta) & 0xFFFF
                glyph_address = ranges + 2 * index + range_offset + 2 * (codepoint - start)
                glyph = self._u16(glyph_address)
                return 0 if glyph == 0 else (glyph + delta) & 0xFFFF
        return 0

    def _u16(self, offset: int) -> int:
        if offset + 2 > len(self._data):
            raise ValueError("font is truncated")
        return struct.unpack_from(">H", self._data, offset)[0]


def normalize_display_text(value: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError("display text must be nonempty")
    return unicodedata.normalize("NFC", " ".join(value.split()))


def fixed_metadata_text(metadata: DisplayTrackMetadata) -> tuple[str, str]:
    """Return label-free fixed album/channel presentation text."""
    return metadata.album_title, f"{metadata.parent_channel}   {metadata.genre_channel}"


def track_metadata_text(metadata: DisplayTrackMetadata) -> str:
    """Return label-free track values while retaining typed provenance off-screen."""
    parts = [metadata.track_title]
    if metadata.bpm is not None:
        parts.append(metadata.bpm)
    if metadata.musical_key is not None:
        parts.append(metadata.musical_key)
    return "   ".join(parts)


def select_resolved_player(
    value: ResolvedPlayerConfiguration, track_ids: Sequence[str]
) -> ResolvedPlayerConfiguration:
    selected = tuple(item for track_id in track_ids for item in value.display_tracks if item.track_id == track_id)
    if len(selected) != len(track_ids):
        raise ValueError("resolved player metadata does not contain the selected tracks")
    return ResolvedPlayerConfiguration(value.layout, value.theme, value.font_sha256, selected)


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} fields do not match the contract")


def _exact_dataclass(value: Any, cls: type, label: str) -> dict[str, Any]:
    result = dict(_object(value, label))
    expected = {name for name, item in cls.__dataclass_fields__.items() if item.init}
    _keys(result, expected, label)
    return result


def _number(value: Any, minimum: float, maximum: float, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)) or not minimum <= float(value) <= maximum:
        raise ValueError(f"{label} is outside the supported range")
    return float(value)


def _integer(value: Any, minimum: int, maximum: int, label: str) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} is outside the supported range")


def _boolean(value: Any, label: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"{label} must be a boolean")


def _enum(value: Any, allowed: frozenset[str], label: str) -> None:
    if type(value) is not str or value not in allowed:
        raise ValueError(f"{label} is unsupported")


def _sha256(value: Any, label: str) -> None:
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
