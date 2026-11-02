from __future__ import annotations

import sys
import warnings
from array import array
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from wrld_video_studio.domain.audio_visualization import (
    BAR_GAP,
    BAR_ZONE_HEIGHT,
    FRAME_RATE,
    OUTPUT_HEIGHT,
    PROGRESS_WIDTH,
    SAFE_MARGIN,
    SAMPLES_PER_FRAME,
    bar_heights,
    bar_layout,
    filled_segments,
    output_frame_count,
    progress_pixels,
    rms_to_amplitude,
    smooth_amplitude,
    track_index_for_sample,
    track_progress,
)
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.video_effects import VideoEffects
from wrld_video_studio.domain.video_effects_v2 import VideoEffectsV2
from wrld_video_studio.domain.video_effects_v3 import VideoEffectsV3
from wrld_video_studio.domain.video_export import (
    BYTES_PER_SAMPLE_FRAME,
    TimelineEntry,
)
from wrld_video_studio.domain.visual_refinement import (
    GLOW_PADDING_PX,
    OUTPUT_HEIGHT as REFINED_OUTPUT_HEIGHT,
    PROGRESS_WIDTH as REFINED_PROGRESS_WIDTH,
    SAFE_MARGIN as REFINED_SAFE_MARGIN,
    derive_rail_color,
    refined_bar_heights,
    refined_bar_layout,
)


try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from audioop import rms as _accelerated_rms
except ImportError:  # pragma: no cover - exercised on Python 3.13+
    _accelerated_rms = None


@dataclass(frozen=True)
class EffectControlPlan:
    filters: tuple[str, ...]
    command_count: int
    frame_count: int
    bar_control_path: Path | None = None
    bar_control_width: int = 0


class VideoEffectControlBuilder:
    """Build a duration-bounded FFmpeg command stream from normalized PCM."""

    def build(
        self,
        pcm_paths: tuple[Path, ...],
        timeline: tuple[TimelineEntry, ...],
        effects: VideoEffects | VideoEffectsV2 | VideoEffectsV3,
        destination: Path,
        *,
        start_sample: int = 0,
        sample_count: int | None = None,
        cancel_event: Any = None,
        heartbeat: Any = None,
        progress_width: int | None = None,
        progress_color: str | None = None,
        pcm_windows: tuple[tuple[int, int], ...] | None = None,
        compact_player_bars: bool = False,
    ) -> EffectControlPlan:
        bars = effects.audio_bars
        progress = effects.track_progress
        if not bars.enabled and not progress.enabled:
            return EffectControlPlan((), 0, 0)
        if len(pcm_paths) != len(timeline) or not timeline:
            raise MediaInfrastructureError(
                "INVALID_RENDER_PLAN", "Effect-control timeline inputs are inconsistent."
            )
        total_samples = timeline[-1].start_sample + timeline[-1].sample_count
        if type(start_sample) is not int or start_sample < 0 or start_sample >= total_samples:
            raise MediaInfrastructureError(
                "PREVIEW_RANGE_INVALID", "The effect-control start is outside the timeline."
            )
        is_excerpt = sample_count is not None or start_sample != 0
        selected_samples = total_samples - start_sample if sample_count is None else sample_count
        if (
            type(selected_samples) is not int
            or selected_samples < 1
            or start_sample + selected_samples > total_samples
        ):
            raise MediaInfrastructureError(
                "PREVIEW_RANGE_INVALID", "The effect-control excerpt exceeds the timeline."
            )
        frame_count = output_frame_count(selected_samples)
        filters = self._filters(effects)
        command_count = 0
        bar_control_path = (
            destination.with_suffix(".bars.gray16")
            if compact_player_bars and isinstance(effects, VideoEffectsV3) and bars.enabled
            else None
        )
        bar_control_width = (
            bars.zone_width_px + 2 * GLOW_PADDING_PX
            if bar_control_path is not None
            else 0
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with ExitStack() as stack:
                streams = tuple(stack.enter_context(path.open("rb")) for path in pcm_paths)
                windows = pcm_windows or tuple((0, entry.sample_count) for entry in timeline)
                if len(windows) != len(timeline):
                    raise MediaInfrastructureError(
                        "INVALID_RENDER_PLAN", "Effect-control PCM windows are inconsistent."
                    )
                self._validate_pcm(pcm_paths, timeline, windows)
                bar_control = (
                    stack.enter_context(bar_control_path.open("wb"))
                    if bar_control_path is not None
                    else None
                )
                with destination.open("w", encoding="ascii", newline="\n") as output:
                    previous_heights = (2,) * bars.bar_count
                    previous_amplitude = 0.0
                    previous_track = -1
                    previous_progress_width = 0
                    progress_visible = False
                    previous_segments = 0
                    if isinstance(effects, VideoEffectsV3):
                        visible_color = self._hex_color(
                            progress_color or "#FFFFFF", progress.fill_opacity
                        )
                    elif isinstance(effects, VideoEffectsV2):
                        visible_color = self._hex_color(
                            progress.color,
                            progress.fill_opacity,
                        )
                    else:
                        visible_color = self._color(
                            progress.opacity if progress.enabled else bars.opacity
                        )
                    if bars.enabled and start_sample:
                        first_track = track_index_for_sample(timeline, start_sample)
                        entry = timeline[first_track]
                        window_start, _window_count = windows[first_track]
                        first_center = window_start + (
                            bars.rms_window_samples // 2 if window_start else 0
                        )
                        first_frame = (
                            entry.start_sample + first_center + SAMPLES_PER_FRAME - 1
                        ) // SAMPLES_PER_FRAME
                        for absolute_frame in range(first_frame, start_sample // SAMPLES_PER_FRAME):
                            self._cancel(cancel_event)
                            presentation = absolute_frame * SAMPLES_PER_FRAME
                            raw_rms = self._window_rms(
                                streams[first_track],
                                presentation - entry.start_sample,
                                entry.sample_count,
                                bars.rms_window_samples,
                                window_start,
                            )
                            previous_amplitude = smooth_amplitude(
                                previous_amplitude,
                                rms_to_amplitude(raw_rms),
                                attack_ms=bars.attack_ms,
                                release_ms=bars.release_ms,
                            )
                        previous_track = first_track
                    for frame_index in range(frame_count):
                        self._cancel(cancel_event)
                        if heartbeat is not None and frame_index % 256 == 0:
                            heartbeat()
                        presentation = start_sample + frame_index * SAMPLES_PER_FRAME
                        track_index = track_index_for_sample(timeline, presentation)
                        entry = timeline[track_index]
                        if track_index != previous_track:
                            previous_amplitude = 0.0
                            previous_track = track_index
                        commands: list[str] = []
                        if bars.enabled:
                            raw_rms = self._window_rms(
                                streams[track_index],
                                presentation - entry.start_sample,
                                entry.sample_count,
                                bars.rms_window_samples,
                                windows[track_index][0],
                            )
                            raw_amplitude = rms_to_amplitude(raw_rms)
                            previous_amplitude = smooth_amplitude(
                                previous_amplitude,
                                raw_amplitude,
                                attack_ms=bars.attack_ms,
                                release_ms=bars.release_ms,
                            )
                            if isinstance(effects, (VideoEffectsV2, VideoEffectsV3)):
                                heights = refined_bar_heights(
                                    previous_amplitude,
                                    bars.bar_count,
                                    bars.zone_height_px,
                                    bars.variation_mode,
                                    presentation,
                                )
                            else:
                                heights = bar_heights(previous_amplitude, bars.bar_count)
                            if bar_control is not None:
                                bar_control.write(self._player_bar_control_row(bars, heights))
                            else:
                                for index, (old, new) in enumerate(
                                    zip(previous_heights, heights, strict=True)
                                ):
                                    if (is_excerpt and frame_index == 0) or old != new:
                                        commands.append(f"drawbox@wrld_bar_{index:02d} h {new}")
                            previous_heights = heights
                        if progress.enabled:
                            value = (
                                min(1.0, max(0.0, presentation / total_samples))
                                if isinstance(effects, VideoEffectsV3)
                                and effects.player is not None
                                and effects.player.progress.mode == "album"
                                else track_progress(entry, presentation)
                            )
                            if progress.style == "line":
                                width = (
                                    min(progress_width, max(0, int(value * progress_width)))
                                    if progress_width is not None
                                    else progress_pixels(value)
                                )
                                if width == 0:
                                    if progress_visible:
                                        commands.append("drawbox@wrld_progress color white@0")
                                        progress_visible = False
                                else:
                                    if (is_excerpt and frame_index == 0) or width != previous_progress_width:
                                        commands.append(
                                            f"drawbox@wrld_progress w {max(1, width)}"
                                        )
                                    if not progress_visible:
                                        commands.append(
                                            f"drawbox@wrld_progress color {visible_color}"
                                        )
                                        progress_visible = True
                                previous_progress_width = width
                            else:
                                filled = filled_segments(value, progress.segment_count)
                                if is_excerpt and frame_index == 0:
                                    for index in range(filled):
                                        commands.append(
                                            f"drawbox@wrld_segment_{index:02d} color {visible_color}"
                                        )
                                elif filled < previous_segments:
                                    for index in range(filled, previous_segments):
                                        commands.append(
                                            f"drawbox@wrld_segment_{index:02d} color white@0"
                                        )
                                elif filled > previous_segments:
                                    for index in range(previous_segments, filled):
                                        commands.append(
                                            f"drawbox@wrld_segment_{index:02d} color {visible_color}"
                                        )
                                previous_segments = filled
                        if commands:
                            timestamp = frame_index / FRAME_RATE
                            output.write(f"{timestamp:.9f} {','.join(commands)};\n")
                            command_count += len(commands)
        except MediaInfrastructureError:
            raise
        except OSError as error:
            raise MediaInfrastructureError(
                "STORAGE_ERROR", "Could not build the attempt-owned effect control stream."
            ) from error
        return EffectControlPlan(
            filters,
            command_count,
            frame_count,
            bar_control_path,
            bar_control_width,
        )

    @staticmethod
    def _player_bar_control_row(bars: Any, heights: tuple[int, ...]) -> bytes:
        start_x, _zone_y, bar_width, _occupied, zone_x = refined_bar_layout(
            bars.bar_count,
            bars.placement,
            bars.zone_width_px,
            bars.zone_height_px,
            bars.gap_px,
            bars.horizontal_offset_px,
            bars.bottom_margin_px,
        )
        if bars.zone_height_px > 65_535 or any(height < 0 or height > 65_535 for height in heights):
            raise MediaInfrastructureError(
                "INVALID_RENDER_PLAN",
                "Player bar geometry exceeds the compact control-stream range.",
            )
        width = bars.zone_width_px + 2 * GLOW_PADDING_PX
        local_start = start_x - zone_x + GLOW_PADDING_PX
        row = array("H", [0]) * width
        for index, height in enumerate(heights):
            left = local_start + index * (bar_width + bars.gap_px)
            row[left : left + bar_width] = array("H", [height]) * bar_width
        if sys.byteorder != "little":
            row.byteswap()
        return row.tobytes()

    @staticmethod
    def _validate_pcm(
        pcm_paths: tuple[Path, ...],
        timeline: tuple[TimelineEntry, ...],
        windows: tuple[tuple[int, int], ...],
    ) -> None:
        for path, entry, window in zip(pcm_paths, timeline, windows, strict=True):
            window_start, window_count = window
            if (
                type(window_start) is not int
                or type(window_count) is not int
                or window_start < 0
                or window_count < 0
                or window_start + window_count > entry.sample_count
            ):
                raise MediaInfrastructureError(
                    "INVALID_RENDER_PLAN", "Effect-control PCM window exceeds its track."
                )
            try:
                size = path.stat().st_size
            except OSError as error:
                raise MediaInfrastructureError(
                    "NORMALIZED_AUDIO_INVALID", "Normalized audio is unavailable."
                ) from error
            if size != window_count * BYTES_PER_SAMPLE_FRAME:
                raise MediaInfrastructureError(
                    "NORMALIZED_AUDIO_INVALID",
                    "Normalized audio does not match the sample timeline.",
                )

    @staticmethod
    def _window_rms(
        stream: BinaryIO,
        center_sample: int,
        track_samples: int,
        window_samples: int,
        pcm_start_sample: int = 0,
    ) -> float:
        left = window_samples // 2
        start = max(0, center_sample - left)
        end = min(track_samples, center_sample + (window_samples - left))
        byte_count = (end - start) * BYTES_PER_SAMPLE_FRAME
        try:
            relative_start = start - pcm_start_sample
            if relative_start < 0:
                raise MediaInfrastructureError(
                    "NORMALIZED_AUDIO_INVALID", "The RMS analysis window precedes normalized PCM."
                )
            stream.seek(relative_start * BYTES_PER_SAMPLE_FRAME)
            data = stream.read(byte_count)
        except OSError as error:
            raise MediaInfrastructureError(
                "STORAGE_ERROR", "Could not read normalized audio for RMS analysis."
            ) from error
        if len(data) != byte_count or not data:
            raise MediaInfrastructureError(
                "NORMALIZED_AUDIO_INVALID", "The RMS analysis window is incomplete."
            )
        if _accelerated_rms is not None:
            return float(_accelerated_rms(data, 2))
        samples = array("h")
        samples.frombytes(data)
        if sys.byteorder != "little":  # raw PCM is little-endian
            samples.byteswap()
        return (sum(sample * sample for sample in samples) / len(samples)) ** 0.5

    @staticmethod
    def _filters(effects: VideoEffects | VideoEffectsV2 | VideoEffectsV3) -> tuple[str, ...]:
        if isinstance(effects, VideoEffectsV3):
            return ()
        if isinstance(effects, VideoEffectsV2):
            return VideoEffectControlBuilder._refined_filters(effects)
        return VideoEffectControlBuilder._legacy_filters(effects)

    @staticmethod
    def _legacy_filters(effects: VideoEffects) -> tuple[str, ...]:
        filters: list[str] = []
        progress = effects.track_progress
        bars = effects.audio_bars
        if bars.enabled:
            start_x, bar_width, _occupied = bar_layout(bars.bar_count, bars.placement)
            progress_shift = (
                progress.thickness_px
                if progress.enabled and progress.placement == "bottom"
                else 0
            )
            zone_bottom = OUTPUT_HEIGHT - SAFE_MARGIN - progress_shift
            color = VideoEffectControlBuilder._color(bars.opacity)
            for index in range(bars.bar_count):
                x = start_x + index * (bar_width + BAR_GAP)
                filters.append(
                    f"drawbox@wrld_bar_{index:02d}=x={x}:y={zone_bottom}-h:"
                    f"w={bar_width}:h=2:color={color}:t=fill"
                )
        if progress.enabled:
            y = (
                SAFE_MARGIN
                if progress.placement == "top"
                else OUTPUT_HEIGHT - SAFE_MARGIN - progress.thickness_px
            )
            if progress.style == "line":
                filters.append(
                    f"drawbox@wrld_progress=x={SAFE_MARGIN}:y={y}:w=1:"
                    f"h={progress.thickness_px}:color=white@0:t=fill"
                )
            else:
                cell_width = (
                    PROGRESS_WIDTH - BAR_GAP * (progress.segment_count - 1)
                ) // progress.segment_count
                occupied = (
                    cell_width * progress.segment_count
                    + BAR_GAP * (progress.segment_count - 1)
                )
                start_x = SAFE_MARGIN + (PROGRESS_WIDTH - occupied) // 2
                for index in range(progress.segment_count):
                    x = start_x + index * (cell_width + BAR_GAP)
                    filters.append(
                        f"drawbox@wrld_segment_{index:02d}=x={x}:y={y}:w={cell_width}:"
                        f"h={progress.thickness_px}:color=white@0:t=fill"
                    )
        return tuple(filters)

    @staticmethod
    def _refined_filters(effects: VideoEffectsV2) -> tuple[str, ...]:
        filters: list[str] = []
        progress = effects.track_progress
        bars = effects.audio_bars
        if bars.enabled:
            start_x, zone_y, bar_width, _occupied, _zone_x = refined_bar_layout(
                bars.bar_count,
                bars.placement,
                bars.zone_width_px,
                bars.zone_height_px,
                bars.gap_px,
                bars.horizontal_offset_px,
                bars.bottom_margin_px,
            )
            color = VideoEffectControlBuilder._hex_color(bars.color, bars.opacity)
            for index in range(bars.bar_count):
                x = start_x + index * (bar_width + bars.gap_px)
                filters.append(
                    f"drawbox@wrld_bar_{index:02d}=x={x}:y={zone_y}+{bars.zone_height_px}-h:"
                    f"w={bar_width}:h=2:color={color}:t=fill"
                )
        if progress.enabled:
            y = (
                REFINED_SAFE_MARGIN
                if progress.placement == "top"
                else REFINED_OUTPUT_HEIGHT - REFINED_SAFE_MARGIN - progress.thickness_px
            )
            rail_color = progress.rail_color or derive_rail_color(
                progress.color, progress.rail_contrast_strength
            )
            filters.append(
                f"drawbox@wrld_progress_rail=x={REFINED_SAFE_MARGIN}:y={y}:"
                f"w={REFINED_PROGRESS_WIDTH}:h={progress.thickness_px}:"
                f"color={VideoEffectControlBuilder._hex_color(rail_color, progress.rail_opacity)}:t=fill"
            )
            if progress.style == "line":
                filters.append(
                    f"drawbox@wrld_progress=x={REFINED_SAFE_MARGIN}:y={y}:w=1:"
                    f"h={progress.thickness_px}:color={VideoEffectControlBuilder._hex_color(progress.color, 0.0)}:t=fill"
                )
            else:
                cell_width = (
                    REFINED_PROGRESS_WIDTH - BAR_GAP * (progress.segment_count - 1)
                ) // progress.segment_count
                occupied = (
                    cell_width * progress.segment_count
                    + BAR_GAP * (progress.segment_count - 1)
                )
                start_x = REFINED_SAFE_MARGIN + (REFINED_PROGRESS_WIDTH - occupied) // 2
                for index in range(progress.segment_count):
                    x = start_x + index * (cell_width + BAR_GAP)
                    filters.append(
                        f"drawbox@wrld_segment_{index:02d}=x={x}:y={y}:w={cell_width}:"
                        f"h={progress.thickness_px}:color={VideoEffectControlBuilder._hex_color(progress.color, 0.0)}:t=fill"
                    )
        return tuple(filters)

    @staticmethod
    def _color(opacity: float) -> str:
        return f"white@{opacity:.6f}"

    @staticmethod
    def _hex_color(color: str, opacity: float) -> str:
        return f"0x{color[1:]}@{opacity:.6f}"

    @staticmethod
    def _cancel(cancel_event: Any) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise MediaInfrastructureError("PROCESS_CANCELLED", "Export was cancelled.")
