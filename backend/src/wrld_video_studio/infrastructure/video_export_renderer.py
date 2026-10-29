from __future__ import annotations

import shutil
import re
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wrld_video_studio.application.ports.media import ProcessRunner
from wrld_video_studio.domain.camera_motion import camera_filter
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.motion_preview import MotionPreviewPlan, validate_excerpt
from wrld_video_studio.domain.motion_preview_v2 import RefinedMotionPreviewPlan
from wrld_video_studio.domain.motion_preview_v3 import PlayerMotionPreviewPlan
from wrld_video_studio.domain.video_export import (
    BYTES_PER_SAMPLE_FRAME,
    SAMPLE_RATE,
    TimelineEntry,
    VideoExportPlan,
    build_timeline,
)
from wrld_video_studio.domain.video_export_v2 import MotionVideoExportPlan
from wrld_video_studio.domain.video_export_v3 import RefinedVideoExportPlan
from wrld_video_studio.domain.video_export_v4 import PlayerVideoExportPlan
from wrld_video_studio.domain.player_overlay import (
    TrueTypeFontMetrics,
    fixed_metadata_text,
    track_metadata_text,
)
from wrld_video_studio.domain.visual_refinement import (
    GLOW_PADDING_PX,
    GLOW_SIGMA_PX,
    OUTPUT_HEIGHT,
    PROGRESS_WIDTH,
    SAFE_MARGIN,
    derive_glow_color,
    derive_rail_color,
    refined_bar_layout,
)
from wrld_video_studio.infrastructure.media_tools import MediaToolchain
from wrld_video_studio.infrastructure.progress import FFmpegProgressParser
from wrld_video_studio.infrastructure.video_effect_controls import (
    EffectControlPlan,
    VideoEffectControlBuilder,
)


ResolvedRenderPlan = (
    VideoExportPlan
    | MotionVideoExportPlan
    | RefinedVideoExportPlan
    | MotionPreviewPlan
    | RefinedMotionPreviewPlan
    | PlayerVideoExportPlan
    | PlayerMotionPreviewPlan
)
MotionRenderPlan = (
    MotionVideoExportPlan
    | RefinedVideoExportPlan
    | MotionPreviewPlan
    | RefinedMotionPreviewPlan
    | PlayerVideoExportPlan
    | PlayerMotionPreviewPlan
)


@dataclass(frozen=True)
class RenderedVideo:
    timeline: tuple[TimelineEntry, ...]
    total_samples: int
    duration_seconds: float
    command: tuple[str, ...]
    stderr_tail: str


@dataclass(frozen=True)
class VideoExportTimeouts:
    normalization_min_seconds: float = 120.0
    normalization_duration_factor: float = 2.0
    render_min_seconds: float = 600.0
    render_duration_factor: float = 4.0


class StaticVideoExportRenderer:
    """WU3A product renderer; deliberately separate from SyntheticMediaEncoder."""

    def __init__(
        self,
        toolchain: MediaToolchain,
        runner: ProcessRunner,
        *,
        timeouts: VideoExportTimeouts | None = None,
        effect_controls: VideoEffectControlBuilder | None = None,
    ) -> None:
        self.toolchain = toolchain
        self.runner = runner
        self.timeouts = timeouts or VideoExportTimeouts()
        self.effect_controls = effect_controls or VideoEffectControlBuilder()
        self._available_filters: frozenset[str] | None = None
        self._validated_player_fonts: set[str] = set()

    def render(
        self,
        plan: ResolvedRenderPlan,
        audio_sources: tuple[Path, ...],
        background: Path,
        staged_output: Path,
        pcm_paths: tuple[Path, ...],
        combined_pcm: Path,
        request_digest: str,
        cancel_event: Any = None,
        heartbeat: Any = None,
        progress: Any = None,
        effect_control_path: Path | None = None,
        font_path: Path | None = None,
        source_sample_counts: tuple[int, ...] | None = None,
    ) -> RenderedVideo:
        if len(pcm_paths) != len(plan.selected_tracks) or len(audio_sources) != len(plan.selected_tracks):
            raise MediaInfrastructureError("INVALID_RENDER_PLAN", "PCM staging is incomplete.")
        ffmpeg = self.toolchain.resolve("ffmpeg")
        if isinstance(
            plan,
            (MotionVideoExportPlan, RefinedVideoExportPlan, PlayerVideoExportPlan, MotionPreviewPlan, RefinedMotionPreviewPlan, PlayerMotionPreviewPlan),
        ) and (
            plan.request.effects.audio_bars.enabled
            or plan.request.effects.track_progress.enabled
            or isinstance(plan, (PlayerVideoExportPlan, PlayerMotionPreviewPlan))
        ):
            self._require_effect_filters(ffmpeg.path, plan)
        preview = isinstance(plan, (MotionPreviewPlan, RefinedMotionPreviewPlan, PlayerMotionPreviewPlan))
        bounded_preview = preview and source_sample_counts is not None
        if source_sample_counts is not None and (
            len(source_sample_counts) != len(audio_sources)
            or any(type(value) is not int or value <= 0 for value in source_sample_counts)
        ):
            raise MediaInfrastructureError(
                "INVALID_RENDER_PLAN", "Preview source sample counts are inconsistent."
            )
        sample_counts: list[int] = list(source_sample_counts or ())
        timeline = build_timeline(plan.selected_tracks, tuple(sample_counts)) if bounded_preview else ()
        target_total_samples = sum(sample_counts) if bounded_preview else 0
        excerpt_start = plan.request.excerpt.start_sample if preview else 0
        excerpt_samples = plan.request.excerpt.sample_count if preview else target_total_samples
        if bounded_preview:
            validate_excerpt(plan.request.excerpt, target_total_samples)
        pcm_windows: list[tuple[int, int]] = []
        track_total = len(audio_sources)
        for track_index, (source, destination) in enumerate(
            zip(audio_sources, pcm_paths, strict=True), start=1
        ):
            self._report(
                progress,
                phase="normalizing_audio",
                current_track=track_index,
                total_tracks=track_total,
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            duration = self._probe_duration(source)
            normalize_args = [
                str(ffmpeg.path), "-hide_banner", "-nostdin", "-v", "error", "-xerror",
                "-i", str(source), "-map", "0:a:0", "-vn", "-ac", "2", "-ar", "48000",
            ]
            expected_samples: int | None = None
            if bounded_preview:
                entry = timeline[track_index - 1]
                overlap_start = max(excerpt_start, entry.start_sample)
                overlap_end = min(excerpt_start + excerpt_samples, entry.start_sample + entry.sample_count)
                if overlap_start >= overlap_end:
                    destination.touch()
                    pcm_windows.append((0, 0))
                    continue
                bars = plan.request.effects.audio_bars
                analysis_margin = (
                    int(max(bars.rms_window_samples // 2, bars.release_ms * SAMPLE_RATE / 100))
                    if bars.enabled
                    else 0
                )
                analysis_tail = bars.rms_window_samples // 2 if bars.enabled else 0
                window_start = max(0, overlap_start - entry.start_sample - analysis_margin)
                window_end = min(
                    entry.sample_count,
                    overlap_end - entry.start_sample + analysis_tail,
                )
                expected_samples = window_end - window_start
                pcm_windows.append((window_start, expected_samples))
                normalize_args.extend(
                    [
                        "-af",
                        f"aresample=48000,atrim=start_sample={window_start}:end_sample={window_end},asetpts=PTS-STARTPTS",
                    ]
                )
            normalize_args.extend(["-c:a", "pcm_s16le", "-f", "s16le", "-y", str(destination)])
            result = self.runner.run(
                normalize_args,
                timeout_seconds=max(
                    self.timeouts.normalization_min_seconds,
                    (
                        (expected_samples / SAMPLE_RATE)
                        if expected_samples is not None
                        else duration
                    ) * self.timeouts.normalization_duration_factor,
                ),
                cancel_event=cancel_event,
                heartbeat=heartbeat,
            )
            self._check_process(result, "Audio normalization")
            size = destination.stat().st_size if destination.is_file() else 0
            if size <= 0 or size % BYTES_PER_SAMPLE_FRAME:
                raise MediaInfrastructureError(
                    "NORMALIZED_AUDIO_INVALID", "Normalized audio has an invalid sample-frame size."
                )
            actual_samples = size // BYTES_PER_SAMPLE_FRAME
            if expected_samples is not None:
                if actual_samples < expected_samples:
                    raise MediaInfrastructureError(
                        "NORMALIZED_AUDIO_INVALID", "Bounded preview normalization is incomplete."
                    )
                if actual_samples > expected_samples:
                    with destination.open("r+b") as stream:
                        stream.truncate(expected_samples * BYTES_PER_SAMPLE_FRAME)
            else:
                sample_counts.append(actual_samples)
                pcm_windows.append((0, actual_samples))
        if not bounded_preview:
            timeline = build_timeline(plan.selected_tracks, tuple(sample_counts))
            target_total_samples = sum(sample_counts)
            excerpt_samples = plan.request.excerpt.sample_count if preview else target_total_samples
        if preview:
            validate_excerpt(plan.request.excerpt, target_total_samples)
        self._report(
            progress,
            phase="assembling_audio",
            current_track=None,
            total_tracks=track_total,
        )
        combined_pcm.parent.mkdir(parents=True, exist_ok=True)
        effect_control = EffectControlPlan((), 0, 0)
        if isinstance(
            plan,
            (MotionVideoExportPlan, RefinedVideoExportPlan, PlayerVideoExportPlan, MotionPreviewPlan, RefinedMotionPreviewPlan, PlayerMotionPreviewPlan),
        ) and (
            plan.request.effects.audio_bars.enabled
            or plan.request.effects.track_progress.enabled
        ):
            if effect_control_path is None:
                raise MediaInfrastructureError(
                    "INVALID_RENDER_PLAN", "Effect-control staging was not allocated."
                )
            control_options: dict[str, Any] = {}
            if preview:
                control_options = {
                    "start_sample": excerpt_start,
                    "sample_count": excerpt_samples,
                }
            effect_control = self.effect_controls.build(
                pcm_paths,
                timeline,
                plan.request.effects,
                effect_control_path,
                cancel_event=cancel_event,
                heartbeat=heartbeat,
                progress_width=(
                    plan.request.resolved_player.layout.progress_row.width - 216
                    if isinstance(plan, (PlayerVideoExportPlan, PlayerMotionPreviewPlan))
                    else None
                ),
                progress_color=(
                    plan.request.resolved_player.theme.progress_fill
                    if isinstance(plan, (PlayerVideoExportPlan, PlayerMotionPreviewPlan))
                    else None
                ),
                pcm_windows=tuple(pcm_windows) if bounded_preview else None,
                compact_player_bars=isinstance(
                    plan, (PlayerVideoExportPlan, PlayerMotionPreviewPlan)
                ),
                **control_options,
            )
        try:
            with combined_pcm.open("wb") as output:
                for index, path in enumerate(pcm_paths):
                    if cancel_event is not None and cancel_event.is_set():
                        raise MediaInfrastructureError("PROCESS_CANCELLED", "Export was cancelled.")
                    if bounded_preview:
                        entry = timeline[index]
                        overlap_start = max(excerpt_start, entry.start_sample)
                        overlap_end = min(
                            excerpt_start + excerpt_samples,
                            entry.start_sample + entry.sample_count,
                        )
                        if overlap_start >= overlap_end:
                            continue
                        window_start, _window_count = pcm_windows[index]
                        local_start = overlap_start - entry.start_sample - window_start
                        byte_count = (overlap_end - overlap_start) * BYTES_PER_SAMPLE_FRAME
                        with path.open("rb") as source:
                            source.seek(local_start * BYTES_PER_SAMPLE_FRAME)
                            self._copy_exact(source, output, byte_count)
                        continue
                    with path.open("rb") as source:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
        except OSError as error:
            raise MediaInfrastructureError(
                "STORAGE_ERROR", "Could not assemble normalized album audio."
            ) from error
        duration = excerpt_samples / SAMPLE_RATE
        target_duration = target_total_samples / SAMPLE_RATE
        self._report(
            progress,
            phase="encoding",
            phase_progress_percent=0.0,
            current_track=None,
            total_tracks=track_total,
            processed_duration_seconds=0.0,
            total_duration_seconds=duration,
        )
        staged_output.parent.mkdir(parents=True, exist_ok=True)
        player_overlays = isinstance(plan, (PlayerVideoExportPlan, PlayerMotionPreviewPlan))
        refined_overlays = isinstance(
            plan, (RefinedVideoExportPlan, RefinedMotionPreviewPlan)
        ) and (
            plan.request.effects.audio_bars.enabled
            or plan.request.effects.track_progress.enabled
        )
        args = [
            str(ffmpeg.path), "-hide_banner", "-nostdin", "-v", "error", "-xerror", "-nostats",
            "-progress", "pipe:1", "-loop", "1", "-framerate", "30", "-i", str(background),
        ]
        if excerpt_start and not bounded_preview:
            args.extend(["-ss", f"{excerpt_start / SAMPLE_RATE:.9f}"])
        args.extend([
            "-f", "s16le", "-ar", "48000", "-ac", "2", "-i", str(combined_pcm),
        ])
        if effect_control.bar_control_path is not None:
            args.extend([
                "-f", "rawvideo", "-pixel_format", "gray16le", "-video_size",
                f"{effect_control.bar_control_width}x1", "-framerate", "30",
                "-i", str(effect_control.bar_control_path),
            ])
        if player_overlays:
            if font_path is None:
                raise MediaInfrastructureError("INVALID_RENDER_PLAN", "Player font staging is unavailable.")
            complex_filter = self._player_filter_complex(
                plan,
                duration,
                effect_control,
                effect_control_path,
                font_path,
                timeline,
                target_duration=target_duration,
                start_sample=excerpt_start,
                preview=preview,
            )
            self._require_player_text(
                ffmpeg.path,
                font_path,
            )
            args.extend(["-filter_complex", complex_filter, "-map", "[vout]", "-map", "1:a:0"])
        elif refined_overlays:
            complex_filter = self._refined_filter_complex(
                plan,
                duration,
                effect_control,
                effect_control_path,
                target_duration=target_duration,
                start_sample=excerpt_start,
                preview=preview,
            )
            args.extend(
                ["-filter_complex", complex_filter, "-map", "[vout]", "-map", "1:a:0"]
            )
        else:
            video_filter = self._video_filter(
                plan,
                duration,
                effect_control,
                effect_control_path,
                target_duration=target_duration,
                start_sample=excerpt_start,
                preview=preview,
            )
            args.extend(["-map", "0:v:0", "-map", "1:a:0", "-vf", video_filter])
        args.extend([
            "-r", "30", "-fps_mode", "cfr", "-t", f"{duration:.9f}",
            "-c:v", "libx264", "-profile:v", "high",
            "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-shortest", "-metadata", f"comment=wrld_request:{request_digest}",
            "-movflags", "+faststart", "-y", str(staged_output),
        ])
        parser = FFmpegProgressParser(duration)
        pending = ""

        def parse_progress(chunk: str) -> None:
            nonlocal pending
            pending += chunk
            lines = pending.splitlines(keepends=True)
            pending = ""
            if lines and not lines[-1].endswith(("\n", "\r")):
                pending = lines.pop()
            for line in lines:
                update = parser.feed_line(line)
                if update and update.progress_percent is not None:
                    processed = self._processed_seconds(update.values)
                    self._report(
                        progress,
                        phase="encoding",
                        phase_progress_percent=update.progress_percent,
                        current_track=None,
                        total_tracks=track_total,
                        processed_duration_seconds=(
                            duration if update.ended else processed
                        ),
                        total_duration_seconds=duration,
                    )

        result = self.runner.run(
            args,
            timeout_seconds=max(
                self.timeouts.render_min_seconds,
                duration * self.timeouts.render_duration_factor,
            ),
            cancel_event=cancel_event,
            heartbeat=heartbeat,
            progress_callback=parse_progress,
            working_directory=(
                font_path.parent
                if player_overlays and font_path is not None
                else None
            ),
        )
        self._check_process(result, "Video encoding")
        return RenderedVideo(
            timeline,
            excerpt_samples,
            duration,
            result.sanitized_argv,
            self.runner.sanitize_diagnostic(result.stderr_tail),
        )

    @staticmethod
    def _video_filter(
        plan: ResolvedRenderPlan,
        duration: float,
        effect_control: EffectControlPlan | None = None,
        effect_control_path: Path | None = None,
        *,
        target_duration: float | None = None,
        start_sample: int = 0,
        preview: bool = False,
    ) -> str:
        static = (
            "scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos:"
            "out_color_matrix=bt709,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,"
        )
        motion = ""
        overlays = ""
        if isinstance(
            plan,
            (MotionVideoExportPlan, RefinedVideoExportPlan, PlayerVideoExportPlan, MotionPreviewPlan, RefinedMotionPreviewPlan, PlayerMotionPreviewPlan),
        ):
            selected = camera_filter(
                plan.request.effects.pan_zoom,
                target_duration if target_duration is not None else duration,
                start_time_seconds=start_sample / SAMPLE_RATE,
                preview=preview,
            )
            if selected is not None:
                motion = selected + ","
            selected_control = effect_control or EffectControlPlan((), 0, 0)
            if selected_control.filters:
                if selected_control.command_count:
                    if effect_control_path is None:
                        raise MediaInfrastructureError(
                            "INVALID_RENDER_PLAN", "Effect-control staging is unavailable."
                        )
                    command_path = StaticVideoExportRenderer._filter_path(effect_control_path)
                    overlays += f"sendcmd=filename='{command_path}',"
                overlays += ",".join(selected_control.filters) + ","
        return (
            static
            + motion
            + overlays
            + "format=yuv420p,"
            + "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709"
        )

    @staticmethod
    def _refined_filter_complex(
        plan: RefinedVideoExportPlan | RefinedMotionPreviewPlan,
        duration: float,
        effect_control: EffectControlPlan,
        effect_control_path: Path | None,
        *,
        target_duration: float,
        start_sample: int,
        preview: bool,
    ) -> str:
        effects = plan.request.effects
        base = (
            "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos:"
            "out_color_matrix=bt709,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black"
        )
        camera = camera_filter(
            effects.pan_zoom,
            target_duration,
            start_time_seconds=start_sample / SAMPLE_RATE,
            preview=preview,
        )
        if camera is not None:
            base += "," + camera
        base += ",format=rgba"
        sendcmd = ""
        if effect_control.command_count:
            if effect_control_path is None:
                raise MediaInfrastructureError(
                    "INVALID_RENDER_PLAN", "Effect-control staging is unavailable."
                )
            command_path = StaticVideoExportRenderer._filter_path(effect_control_path)
            sendcmd = f",sendcmd=filename='{command_path}'"
            if not effects.audio_bars.enabled or effect_control.bar_control_path is not None:
                base += sendcmd
        graph = [base + "[base]"]
        current = "base"

        bars = effects.audio_bars
        if bars.enabled:
            start_x, zone_y, bar_width, _occupied, zone_x = refined_bar_layout(
                bars.bar_count,
                bars.placement,
                bars.zone_width_px,
                bars.zone_height_px,
                bars.gap_px,
                bars.horizontal_offset_px,
                bars.bottom_margin_px,
            )
            padding = GLOW_PADDING_PX
            layer_width = bars.zone_width_px + 2 * padding
            layer_height = bars.zone_height_px + 2 * padding
            crop_x = zone_x - padding
            crop_y = zone_y - padding
            draw = (
                f"color=c=black@0.0:s={layer_width}x{layer_height}:r=30:"
                f"d={duration:.9f},format=rgba"
                + sendcmd
            )
            local_start = start_x - zone_x + padding
            zone_bottom = padding + bars.zone_height_px
            for index in range(bars.bar_count):
                x = local_start + index * (bar_width + bars.gap_px)
                draw += (
                    f",drawbox@wrld_bar_{index:02d}=x={x}:y={zone_bottom}-h:"
                    f"w={bar_width}:h=2:color=white@1.0:t=fill:replace=1"
                )
            glow_enabled = bars.glow.enabled and bars.glow.intensity > 0.0
            if glow_enabled:
                graph.append(draw + "[bar_mask]")
                graph.append("[bar_mask]split=2[glow_mask][crisp_mask]")
                glow_alpha = bars.opacity * bars.glow.intensity * 0.60
                graph.append(
                    "[glow_mask]"
                    + StaticVideoExportRenderer._color_matrix(
                        derive_glow_color(bars.color), glow_alpha
                    )
                    + f",gblur=sigma={GLOW_SIGMA_PX}[glow_layer]"
                )
                graph.append(
                    "[crisp_mask]"
                    + StaticVideoExportRenderer._color_matrix(bars.color, bars.opacity)
                    + "[crisp_layer]"
                )
                graph.append(
                    "[glow_layer][crisp_layer]overlay=0:0:format=auto[bar_layer]"
                )
            else:
                graph.append(
                    draw
                    + ","
                    + StaticVideoExportRenderer._color_matrix(bars.color, bars.opacity)
                    + "[bar_layer]"
                )
            graph.append(
                f"[base][bar_layer]overlay={crop_x}:{crop_y}:"
                "format=auto[with_bars]"
            )
            current = "with_bars"

        progress = effects.track_progress
        if progress.enabled:
            y = (
                SAFE_MARGIN
                if progress.placement == "top"
                else OUTPUT_HEIGHT - SAFE_MARGIN - progress.thickness_px
            )
            rail = progress.rail_color or derive_rail_color(
                progress.color, progress.rail_contrast_strength
            )
            chain = (
                f"[{current}]drawbox@wrld_progress_rail=x={SAFE_MARGIN}:y={y}:"
                f"w={PROGRESS_WIDTH}:h={progress.thickness_px}:"
                f"color={StaticVideoExportRenderer._ffmpeg_color(rail, progress.rail_opacity)}:"
                "t=fill"
            )
            if progress.style == "line":
                chain += (
                    f",drawbox@wrld_progress=x={SAFE_MARGIN}:y={y}:w=1:"
                    f"h={progress.thickness_px}:"
                    f"color={StaticVideoExportRenderer._ffmpeg_color(progress.color, 0.0)}:"
                    "t=fill"
                )
            else:
                gap = 4
                cell_width = (
                    PROGRESS_WIDTH - gap * (progress.segment_count - 1)
                ) // progress.segment_count
                occupied = cell_width * progress.segment_count + gap * (
                    progress.segment_count - 1
                )
                segment_start = SAFE_MARGIN + (PROGRESS_WIDTH - occupied) // 2
                for index in range(progress.segment_count):
                    x = segment_start + index * (cell_width + gap)
                    chain += (
                        f",drawbox@wrld_segment_{index:02d}=x={x}:y={y}:"
                        f"w={cell_width}:h={progress.thickness_px}:"
                        f"color={StaticVideoExportRenderer._ffmpeg_color(progress.color, 0.0)}:"
                        "t=fill"
                    )
            graph.append(chain + "[with_progress]")
            current = "with_progress"

        graph.append(
            f"[{current}]format=yuv420p,"
            "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709[vout]"
        )
        return ";".join(graph)

    @staticmethod
    def _player_filter_complex(
        plan: PlayerVideoExportPlan | PlayerMotionPreviewPlan,
        duration: float,
        effect_control: EffectControlPlan,
        effect_control_path: Path | None,
        font_path: Path,
        timeline: tuple[TimelineEntry, ...],
        *,
        target_duration: float,
        start_sample: int,
        preview: bool,
    ) -> str:
        effects = plan.request.effects
        resolved = plan.request.resolved_player
        assert effects.player is not None
        player = effects.player
        theme = resolved.theme
        layout = resolved.layout
        base = (
            "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos:"
            "out_color_matrix=bt709,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black"
        )
        camera = camera_filter(
            effects.pan_zoom,
            target_duration,
            start_time_seconds=start_sample / SAMPLE_RATE,
            preview=preview,
        )
        if camera is not None:
            base += "," + camera
        base += ",format=rgba"
        sendcmd = ""
        if effect_control.command_count:
            if effect_control_path is None:
                raise MediaInfrastructureError("INVALID_RENDER_PLAN", "Effect-control staging is unavailable.")
            sendcmd = f",sendcmd=filename='{StaticVideoExportRenderer._filter_path(effect_control_path)}'"
            if not effects.audio_bars.enabled:
                base += sendcmd
        graph = [base + "[base]"]
        current = "base"

        bars = effects.audio_bars
        if bars.enabled:
            start_x, _zone_y, bar_width, _occupied, _zone_x = refined_bar_layout(
                bars.bar_count, bars.placement, bars.zone_width_px, bars.zone_height_px,
                bars.gap_px, bars.horizontal_offset_px, bars.bottom_margin_px,
            )
            padding = GLOW_PADDING_PX
            layer_width = bars.zone_width_px + 2 * padding
            layer_height = bars.zone_height_px + 2 * padding
            local_start = start_x - layout.visualizer.x + padding
            zone_bottom = padding + bars.zone_height_px
            if effect_control.bar_control_path is not None:
                graph.extend([
                    f"[2:v]scale={layer_width}:{layer_height}:flags=neighbor,"
                    f"geq=lum='if(eq(p(X,Y),0),0,if(between(Y,{zone_bottom}-p(X,Y),{zone_bottom - 1}),255,0))'[bar_alpha]",
                    f"color=c=white:s={layer_width}x{layer_height}:r=30:d={duration:.9f},format=rgba[bar_white]",
                    "[bar_white][bar_alpha]alphamerge[bar_mask]",
                ])
                draw = ""
            else:
                draw = f"color=c=black@0.0:s={layer_width}x{layer_height}:r=30:d={duration:.9f},format=rgba" + sendcmd
                for index in range(bars.bar_count):
                    draw += (
                        f",drawbox@wrld_bar_{index:02d}=x={local_start + index * (bar_width + bars.gap_px)}:"
                        f"y={zone_bottom}-h:w={bar_width}:h=2:color=white@1.0:t=fill:replace=1"
                    )
            if bars.glow.enabled and bars.glow.intensity > 0:
                if draw:
                    graph.append(draw + "[bar_mask]")
                graph.extend([
                    "[bar_mask]split=2[glow_mask][crisp_mask]",
                    "[glow_mask]" + StaticVideoExportRenderer._color_matrix(
                        theme.visualizer, bars.opacity * bars.glow.intensity * 0.60
                    ) + f",gblur=sigma={GLOW_SIGMA_PX}[glow_layer]",
                    "[crisp_mask]" + StaticVideoExportRenderer._color_matrix(
                        theme.visualizer, bars.opacity
                    ) + "[crisp_layer]",
                    "[glow_layer][crisp_layer]overlay=0:0:format=auto[bar_layer]",
                ])
            else:
                graph.append(
                    ((draw + ",") if draw else "[bar_mask]")
                    + StaticVideoExportRenderer._color_matrix(theme.visualizer, bars.opacity)
                    + "[bar_layer]"
                )
            graph.append(
                f"[base][bar_layer]overlay={layout.visualizer_glow.x}:{layout.visualizer_glow.y}:format=auto[with_bars]"
            )
            current = "with_bars"

        chain = f"[{current}]"
        if player.footer.enabled:
            footer = layout.footer
            chain += (
                f"drawbox=x={footer.x}:y={footer.y}:w={footer.width}:h={footer.height}:"
                f"color={StaticVideoExportRenderer._ffmpeg_color(theme.footer_background, player.footer.opacity)}:t=fill,"
            )
        progress = player.progress
        progress_row = layout.progress_row
        timer_width = 92
        gap = 16
        rail_x = progress_row.x + timer_width + gap
        rail_width = progress_row.width - 2 * (timer_width + gap)
        rail_y = progress_row.y + (progress_row.height - progress.thickness_px) // 2
        if progress.enabled:
            chain += (
                f"drawbox@wrld_progress_rail=x={rail_x}:y={rail_y}:w={rail_width}:h={progress.thickness_px}:"
                f"color={StaticVideoExportRenderer._ffmpeg_color(theme.progress_rail, progress.rail_opacity)}:t=fill,"
                f"drawbox@wrld_progress=x={rail_x}:y={rail_y}:w=1:h={progress.thickness_px}:"
                f"color={StaticVideoExportRenderer._ffmpeg_color(theme.progress_fill, 0.0)}:t=fill,"
            )
        chain = chain.rstrip(",") + "[player_base]"
        graph.append(chain)
        current = "player_base"

        text_root = (effect_control_path or font_path).parent / "player-text"
        try:
            text_root.mkdir(parents=True, exist_ok=True)
            metrics = TrueTypeFontMetrics(font_path.read_bytes())
        except (OSError, ValueError) as error:
            raise MediaInfrastructureError("FONT_INVALID", "The staged player font is unavailable or unsupported.") from error
        text_cwd = font_path.parent
        font = StaticVideoExportRenderer._relative_filter_path(font_path, text_cwd)
        primary = StaticVideoExportRenderer._ffmpeg_color(theme.primary_text, 1.0)
        secondary = StaticVideoExportRenderer._ffmpeg_color(theme.secondary_text, 1.0)
        timer_size = player.font.timer_size_px
        metadata_size = player.font.metadata_size_px
        total_samples = timeline[-1].start_sample + timeline[-1].sample_count
        total_seconds = total_samples // SAMPLE_RATE
        elapsed_expression = StaticVideoExportRenderer._timer_expression(
            start_sample / SAMPLE_RATE, total_seconds >= 3600
        )
        total_text = StaticVideoExportRenderer._format_seconds(total_seconds, total_seconds >= 3600)
        total_file = StaticVideoExportRenderer._write_text_asset(text_root / "total.txt", total_text)
        graph.append(
            f"[{current}]drawtext=fontfile='{font}':text='{elapsed_expression}':fontcolor={primary}:fontsize={timer_size}:"
            f"x={progress_row.x}:y={progress_row.y + 3},"
            f"drawtext=fontfile='{font}':textfile='{StaticVideoExportRenderer._relative_filter_path(total_file, text_cwd)}':fontcolor={primary}:fontsize={timer_size}:"
            f"x={progress_row.right}-text_w:y={progress_row.y + 3}[with_timers]"
        )
        current = "with_timers"

        if player.metadata.enabled:
            row = layout.metadata_row
            display = resolved.display_tracks
            album_value, channels_value = fixed_metadata_text(display[0])
            album_text = metrics.truncate(album_value, metadata_size, 390)
            album_file = StaticVideoExportRenderer._write_text_asset(text_root / "album.txt", album_text)
            album_width = int(math.ceil(metrics.width(album_text, metadata_size)))
            right_text = metrics.truncate(
                channels_value,
                metadata_size,
                560,
            )
            right_file = StaticVideoExportRenderer._write_text_asset(text_root / "channels.txt", right_text)
            right_width = int(math.ceil(metrics.width(right_text, metadata_size)))
            dynamic_x = row.x + album_width + 24
            dynamic_width = max(80, row.right - right_width - 24 - dynamic_x)
            graph.append(
                f"[{current}]drawtext=fontfile='{font}':textfile='{StaticVideoExportRenderer._relative_filter_path(album_file, text_cwd)}':"
                f"fontcolor={primary}:fontsize={metadata_size}:x={row.x}:y={row.y + 4},"
                f"drawtext=fontfile='{font}':textfile='{StaticVideoExportRenderer._relative_filter_path(right_file, text_cwd)}':"
                f"fontcolor={secondary}:fontsize={metadata_size}:x={row.right - right_width}:y={row.y + 4}[fixed_metadata]"
            )
            current = "fixed_metadata"
            for index, (entry, metadata) in enumerate(zip(timeline, display, strict=True)):
                value = metrics.truncate(track_metadata_text(metadata), metadata_size, dynamic_width)
                path = StaticVideoExportRenderer._write_text_asset(text_root / f"track-{index:03d}.txt", value)
                start = (entry.start_sample - start_sample) / SAMPLE_RATE
                end = (entry.start_sample + entry.sample_count - start_sample) / SAMPLE_RATE
                alpha = StaticVideoExportRenderer._metadata_alpha(start, end, index, len(timeline))
                output = f"track_metadata_{index:03d}"
                graph.append(
                    f"[{current}]drawtext=fontfile='{font}':textfile='{StaticVideoExportRenderer._relative_filter_path(path, text_cwd)}':"
                    f"fontcolor={primary}:fontsize={metadata_size}:x={dynamic_x}:y={row.y + 4}:"
                    f"alpha='{alpha}':enable='between(t,{max(0.0, start):.9f},{min(duration, end):.9f})'[{output}]"
                )
                current = output

        if player.announcement.enabled:
            announcement = layout.announcement
            size = player.font.announcement_size_px
            for index, (entry, metadata) in enumerate(zip(timeline, resolved.display_tracks, strict=True)):
                start = (entry.start_sample - start_sample) / SAMPLE_RATE
                stop = start + player.announcement.fade_in_seconds + player.announcement.hold_seconds + player.announcement.fade_out_seconds
                path = StaticVideoExportRenderer._write_text_asset(
                    text_root / f"announcement-{index:03d}.txt",
                    metrics.truncate(metadata.track_title, size, announcement.width),
                )
                alpha = StaticVideoExportRenderer._announcement_alpha(start, player.announcement.fade_in_seconds, player.announcement.hold_seconds, player.announcement.fade_out_seconds)
                output = f"announcement_{index:03d}"
                graph.append(
                    f"[{current}]drawtext=fontfile='{font}':textfile='{StaticVideoExportRenderer._relative_filter_path(path, text_cwd)}':"
                    f"fontcolor={primary}:fontsize={size}:x=(w-text_w)/2:y={announcement.y}:alpha='{alpha}':"
                    f"enable='between(t,{max(0.0, start):.9f},{min(duration, stop):.9f})'[{output}]"
                )
                current = output

        graph.append(
            f"[{current}]format=yuv420p,setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709[vout]"
        )
        return ";".join(graph)

    @staticmethod
    def _write_text_asset(path: Path, value: str) -> Path:
        try:
            path.write_text(value, encoding="utf-8", newline="\n")
        except OSError as error:
            raise MediaInfrastructureError("STORAGE_ERROR", "Player text staging failed.") from error
        return path

    @staticmethod
    def _timer_expression(start_seconds: float, hours: bool) -> str:
        base = f"t+{start_seconds:.9f}"
        if hours:
            return (
                f"%{{eif\\:floor(({base})/3600)\\:d\\:2}}\\:"
                f"%{{eif\\:mod(floor(({base})/60),60)\\:d\\:2}}\\:"
                f"%{{eif\\:mod(floor({base}),60)\\:d\\:2}}"
            )
        return (
            f"%{{eif\\:floor(({base})/60)\\:d\\:2}}\\:"
            f"%{{eif\\:mod(floor({base}),60)\\:d\\:2}}"
        )

    @staticmethod
    def _format_seconds(seconds: int, hours: bool) -> str:
        if hours:
            return f"{seconds // 3600:02d}:{(seconds // 60) % 60:02d}:{seconds % 60:02d}"
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    @staticmethod
    def _metadata_alpha(start: float, end: float, index: int, count: int) -> str:
        fade_in = "1"
        fade_out = "1"
        if index > 0:
            fade_in = f"clip((t-({start:.9f}))/3,0,1)"
        if index < count - 1:
            fade_out = f"clip((({end:.9f})-t)/3,0,1)"
        return f"({fade_in})*({fade_out})"

    @staticmethod
    def _announcement_alpha(start: float, fade_in: float, hold: float, fade_out: float) -> str:
        hold_end = start + fade_in + hold
        return (
            f"if(lt(t,{start + fade_in:.9f}),clip((t-{start:.9f})/{fade_in:.9f},0,1),"
            f"if(lt(t,{hold_end:.9f}),1,clip(({hold_end + fade_out:.9f}-t)/{fade_out:.9f},0,1)))"
        )

    @staticmethod
    def _color_matrix(color: str, opacity: float) -> str:
        red, green, blue = (
            int(color[index : index + 2], 16) / 255.0 for index in (1, 3, 5)
        )
        return (
            f"colorchannelmixer=rr={red:.9f}:gg={green:.9f}:bb={blue:.9f}:"
            f"aa={opacity:.9f}"
        )

    @staticmethod
    def _ffmpeg_color(color: str, opacity: float) -> str:
        return f"0x{color[1:]}@{opacity:.6f}"

    def _require_effect_filters(
        self, ffmpeg: Path, plan: MotionRenderPlan
    ) -> None:
        if self._available_filters is None:
            result = self.runner.run(
                [str(ffmpeg), "-hide_banner", "-filters"], timeout_seconds=30.0
            )
            if result.returncode != 0 or result.timed_out or result.cancelled:
                raise MediaInfrastructureError(
                    "MEDIA_TOOL_INVALID", "FFmpeg filter capabilities could not be verified."
                )
            names: set[str] = set()
            for line in result.stdout.splitlines():
                match = re.match(r"^\s*[.A-Z]{2,3}\s+(\S+)\s", line)
                if match is not None:
                    names.add(match.group(1))
            self._available_filters = frozenset(names)
        required = {"scale", "pad", "format", "setparams", "sendcmd", "drawbox"}
        if isinstance(plan, (PlayerVideoExportPlan, PlayerMotionPreviewPlan)) and plan.request.effects.audio_bars.enabled:
            required.update({"geq", "alphamerge"})
        if isinstance(plan, (RefinedVideoExportPlan, RefinedMotionPreviewPlan, PlayerVideoExportPlan, PlayerMotionPreviewPlan)):
            required.update({"color", "overlay", "colorchannelmixer"})
            bars = plan.request.effects.audio_bars
            if bars.enabled and bars.glow.enabled and bars.glow.intensity > 0.0:
                required.update({"split", "gblur"})
        if isinstance(plan, (PlayerVideoExportPlan, PlayerMotionPreviewPlan)):
            required.add("drawtext")
        if plan.request.effects.pan_zoom.enabled:
            required.add("zoompan")
        missing = sorted(required - self._available_filters)
        if missing:
            raise MediaInfrastructureError(
                "MEDIA_TOOL_INVALID",
                "FFmpeg lacks filters required by the selected motion effects.",
                {"missing_filters": missing},
            )

    def _require_player_text(self, ffmpeg: Path, font_path: Path) -> None:
        import hashlib

        digest = hashlib.sha256(font_path.read_bytes()).hexdigest()
        if digest in self._validated_player_fonts:
            return
        graph = (
            "drawtext=fontfile='"
            + self._relative_filter_path(font_path, font_path.parent)
            + "':text='WRLD':fontcolor=white:fontsize=16"
        )
        result = self.runner.run(
            [
                str(ffmpeg), "-hide_banner", "-nostdin", "-v", "error", "-xerror",
                "-f", "lavfi", "-i", "color=c=black:s=16x16:d=0.04",
                "-vf", graph, "-f", "null", "-",
            ],
            timeout_seconds=30.0,
            working_directory=font_path.parent,
        )
        if result.returncode != 0 or result.timed_out or result.cancelled:
            raise MediaInfrastructureError(
                "MEDIA_TOOL_INVALID",
                "FFmpeg could not load the configured player font and text assets.",
                {"stderr_tail": self.runner.sanitize_diagnostic(result.stderr_tail)},
            )
        self._validated_player_fonts.add(digest)

    @staticmethod
    def _filter_path(path: Path) -> str:
        value = path.resolve().as_posix()
        return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

    @staticmethod
    def _drawtext_path(path: Path) -> str:
        value = str(path.resolve())
        return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

    @staticmethod
    def _relative_filter_path(path: Path, base: Path) -> str:
        try:
            value = path.resolve().relative_to(base.resolve()).as_posix()
        except ValueError as error:
            raise MediaInfrastructureError(
                "INVALID_RENDER_PLAN", "Player text assets do not share attempt ownership."
            ) from error
        return value.replace("'", "\\'")

    @staticmethod
    def _processed_seconds(values: dict[str, str]) -> float | None:
        raw = values.get("out_time_us") or values.get("out_time_ms")
        if raw is None:
            return None
        try:
            return max(0.0, int(raw) / 1_000_000)
        except ValueError:
            return None

    @staticmethod
    def _report(progress: Any, **value: Any) -> None:
        if progress is not None:
            progress(value)

    @staticmethod
    def _copy_exact(source: Any, destination: Any, byte_count: int) -> None:
        remaining = byte_count
        while remaining:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                raise MediaInfrastructureError(
                    "NORMALIZED_AUDIO_INVALID", "Bounded preview PCM is incomplete."
                )
            destination.write(chunk)
            remaining -= len(chunk)

    def _probe_duration(self, path: Path) -> float:
        ffprobe = self.toolchain.resolve("ffprobe")
        result = self.runner.run(
            [
                str(ffprobe.path), "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path),
            ],
            timeout_seconds=30.0,
        )
        if result.returncode != 0 or result.timed_out:
            raise MediaInfrastructureError("PROBE_FAILED", "Could not determine source duration.")
        try:
            duration = float(result.stdout.strip())
        except ValueError as error:
            raise MediaInfrastructureError("PROBE_INVALID", "Source duration is invalid.") from error
        if duration <= 0:
            raise MediaInfrastructureError("PROBE_INVALID", "Source duration must be positive.")
        return duration

    def _check_process(self, result: Any, stage: str) -> None:
        if result.cancelled:
            raise MediaInfrastructureError("PROCESS_CANCELLED", f"{stage} was cancelled.")
        if result.timed_out:
            raise MediaInfrastructureError(
                "PROCESS_TIMEOUT", f"{stage} exceeded its configured time budget.",
                {"stderr_tail": self.runner.sanitize_diagnostic(result.stderr_tail)},
            )
        if result.returncode != 0:
            raise MediaInfrastructureError(
                "PROCESS_FAILED", f"{stage} failed.",
                {
                    "stderr_tail": self.runner.sanitize_diagnostic(result.stderr_tail),
                    "command": list(result.sanitized_argv),
                },
            )
