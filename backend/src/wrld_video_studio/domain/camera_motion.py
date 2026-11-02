from __future__ import annotations

import math
from dataclasses import dataclass

from wrld_video_studio.domain.video_effects import PanZoomSettings


FRAME_RATE = 30
CANVAS_WIDTH = 1920
CANVAS_HEIGHT = 1080


@dataclass(frozen=True)
class CameraState:
    zoom: float
    x: float
    y: float


def smoothstep(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return value * value * (3.0 - 2.0 * value)


def camera_state(
    settings: PanZoomSettings,
    time_seconds: float,
    target_duration: float,
    *,
    final_frame: bool = False,
) -> CameraState:
    if target_duration <= 0 or not math.isfinite(target_duration):
        raise ValueError("target_duration must be finite and positive")
    if time_seconds < 0 or not math.isfinite(time_seconds):
        raise ValueError("time_seconds must be finite and nonnegative")
    time_seconds = min(time_seconds, target_duration)
    if not settings.enabled:
        return CameraState(1.0, 0.0, 0.0)
    return_duration = min(settings.return_duration_seconds, target_duration / 2.0)
    return_start = target_duration - return_duration
    if settings.return_to_origin and (time_seconds >= return_start or final_frame):
        origin = _cycle_state(settings, return_start)
        progress = 1.0 if final_frame else (time_seconds - return_start) / return_duration
        remaining = 1.0 - smoothstep(progress)
        return CameraState(
            1.0 + (origin.zoom - 1.0) * remaining,
            origin.x * remaining,
            origin.y * remaining,
        )
    return _cycle_state(settings, time_seconds)


def camera_filter(
    settings: PanZoomSettings,
    target_duration: float,
    *,
    start_time_seconds: float = 0.0,
    preview: bool = False,
    frames_per_input: int = 1,
) -> str | None:
    """Return the deterministic zoompan filter for the approved 1080p30 profile."""
    if not settings.enabled:
        return None
    if start_time_seconds < 0 or not math.isfinite(start_time_seconds):
        raise ValueError("start_time_seconds must be finite and nonnegative")
    if start_time_seconds >= target_duration:
        raise ValueError("start_time_seconds must be before the target end")
    if type(frames_per_input) is not int or frames_per_input < 1:
        raise ValueError("frames_per_input must be a positive integer")
    frame_count = max(1, math.ceil(target_duration * FRAME_RATE))
    last_frame = frame_count - 1
    time_expr = f"on/{FRAME_RATE}"
    if start_time_seconds:
        time_expr = f"({time_expr}+{_number(start_time_seconds)})"
    base_ease = _ffmpeg_cycle_ease(time_expr, settings.cycle_seconds)
    base_zoom = f"1+{_number(settings.max_zoom - 1.0)}*({base_ease})"
    base_x, base_y = _ffmpeg_position(settings.path, base_ease)
    zoom = base_zoom
    x = base_x
    y = base_y
    if settings.return_to_origin:
        return_duration = min(settings.return_duration_seconds, target_duration / 2.0)
        return_start = target_duration - return_duration
        start = camera_state(settings, return_start, target_duration)
        progress = f"clip(({time_expr}-{_number(return_start)})/{_number(return_duration)},0,1)"
        eased = f"({progress})*({progress})*(3-2*({progress}))"
        remaining = f"1-({eased})"
        in_return = f"gte({time_expr},{_number(return_start)})"
        return_zoom = f"if({in_return},1+{_number(start.zoom - 1.0)}*({remaining}),{base_zoom})"
        return_x = f"if({in_return},{_number(start.x)}*({remaining}),{base_x})"
        return_y = f"if({in_return},{_number(start.y)}*({remaining}),{base_y})"
        if preview:
            zoom, x, y = return_zoom, return_x, return_y
        else:
            zoom = f"if(gte(on,{last_frame}),1,{return_zoom})"
            x = f"if(gte(on,{last_frame}),0,{return_x})"
            y = f"if(gte(on,{last_frame}),0,{return_y})"
    return (
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames_per_input}:"
        f"s={CANVAS_WIDTH}x{CANVAS_HEIGHT}:fps={FRAME_RATE}"
    )


def _cycle_state(settings: PanZoomSettings, time_seconds: float) -> CameraState:
    phase = (time_seconds % settings.cycle_seconds) / settings.cycle_seconds
    triangular = 2.0 * phase if phase <= 0.5 else 2.0 * (1.0 - phase)
    eased = smoothstep(triangular)
    zoom = 1.0 + (settings.max_zoom - 1.0) * eased
    safe_x = CANVAS_WIDTH - CANVAS_WIDTH / zoom
    safe_y = CANVAS_HEIGHT - CANVAS_HEIGHT / zoom
    center_x = safe_x / 2.0
    center_y = safe_y / 2.0
    x_factor, y_factor = _path_factors(settings.path, eased)
    return CameraState(zoom, center_x * x_factor, center_y * y_factor)


def _path_factors(path: str, eased: float) -> tuple[float, float]:
    x = 1.0
    y = 1.0
    if path in {"horizontal", "diagonal_down_right", "diagonal_up_right"}:
        x += eased
    if path in {"vertical", "diagonal_down_right"}:
        y += eased
    elif path == "diagonal_up_right":
        y -= eased
    return x, y


def _ffmpeg_cycle_ease(time_expr: str, cycle_seconds: float) -> str:
    phase = f"mod({time_expr},{_number(cycle_seconds)})/{_number(cycle_seconds)}"
    triangular = f"if(lte({phase},0.5),2*({phase}),2*(1-({phase})))"
    return f"({triangular})*({triangular})*(3-2*({triangular}))"


def _ffmpeg_position(path: str, eased: str) -> tuple[str, str]:
    center_x = "(iw-iw/zoom)/2"
    center_y = "(ih-ih/zoom)/2"
    if path in {"horizontal", "diagonal_down_right", "diagonal_up_right"}:
        x = f"({center_x})*(1+({eased}))"
    else:
        x = center_x
    if path in {"vertical", "diagonal_down_right"}:
        y = f"({center_y})*(1+({eased}))"
    elif path == "diagonal_up_right":
        y = f"({center_y})*(1-({eased}))"
    else:
        y = center_y
    return x, y


def _number(value: float) -> str:
    return format(float(value), ".12g")
