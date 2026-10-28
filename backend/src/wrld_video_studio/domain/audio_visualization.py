from __future__ import annotations

import math

from wrld_video_studio.domain.video_export import SAMPLE_RATE, TimelineEntry


FRAME_RATE = 30
SAMPLES_PER_FRAME = SAMPLE_RATE // FRAME_RATE
BAR_ZONE_WIDTH = 640
BAR_ZONE_HEIGHT = 180
BAR_GAP = 4
SAFE_MARGIN = 64
OUTPUT_WIDTH = 1920
OUTPUT_HEIGHT = 1080
PROGRESS_WIDTH = OUTPUT_WIDTH - 2 * SAFE_MARGIN


def output_frame_count(total_samples: int) -> int:
    if type(total_samples) is not int or total_samples <= 0:
        raise ValueError("total_samples must be a positive integer")
    return (total_samples + SAMPLES_PER_FRAME - 1) // SAMPLES_PER_FRAME


def track_index_for_sample(
    timeline: tuple[TimelineEntry, ...], presentation_sample: int
) -> int:
    if not timeline or presentation_sample < 0:
        raise ValueError("timeline and presentation sample are invalid")
    selected = 0
    for index, entry in enumerate(timeline[1:], start=1):
        if presentation_sample < entry.start_sample:
            break
        selected = index
    return selected


def track_progress(entry: TimelineEntry, presentation_sample: int) -> float:
    return min(
        1.0,
        max(0.0, (presentation_sample - entry.start_sample) / entry.sample_count),
    )


def rms_to_amplitude(rms: float) -> float:
    if not math.isfinite(rms) or rms < 0:
        raise ValueError("rms must be finite and nonnegative")
    if rms == 0:
        return 0.0
    dbfs = 20.0 * math.log10(rms / 32768.0)
    return min(1.0, max(0.0, (dbfs + 60.0) / 60.0))


def smoothing_alpha(milliseconds: float) -> float:
    if not math.isfinite(milliseconds) or milliseconds < 0:
        raise ValueError("time constant must be finite and nonnegative")
    if milliseconds == 0:
        return 1.0
    seconds = milliseconds / 1000.0
    return 1.0 - math.exp(-(1.0 / FRAME_RATE) / seconds)


def smooth_amplitude(
    previous: float,
    raw: float,
    *,
    attack_ms: float,
    release_ms: float,
) -> float:
    if not all(math.isfinite(value) for value in (previous, raw)):
        raise ValueError("amplitudes must be finite")
    alpha = smoothing_alpha(attack_ms if raw >= previous else release_ms)
    return previous + alpha * (raw - previous)


def bar_heights(amplitude: float, bar_count: int) -> tuple[int, ...]:
    if not math.isfinite(amplitude) or not 0.0 <= amplitude <= 1.0:
        raise ValueError("amplitude must be between zero and one")
    if type(bar_count) is not int or bar_count <= 0:
        raise ValueError("bar_count must be positive")
    values = []
    for index in range(bar_count):
        multiplier = 0.25 + 0.75 * math.sin(math.pi * (index + 0.5) / bar_count) ** 2
        height = math.floor(BAR_ZONE_HEIGHT * amplitude * multiplier + 0.5)
        values.append(max(2, min(BAR_ZONE_HEIGHT, height)))
    return tuple(values)


def bar_layout(bar_count: int, placement: str) -> tuple[int, int, int]:
    if type(bar_count) is not int or bar_count <= 0:
        raise ValueError("bar_count must be positive")
    bar_width = (BAR_ZONE_WIDTH - BAR_GAP * (bar_count - 1)) // bar_count
    if bar_width <= 0:
        raise ValueError("bar geometry is invalid")
    occupied = bar_width * bar_count + BAR_GAP * (bar_count - 1)
    zone_x = {
        "bottom_left": SAFE_MARGIN,
        "bottom_center": (OUTPUT_WIDTH - BAR_ZONE_WIDTH) // 2,
        "bottom_right": OUTPUT_WIDTH - SAFE_MARGIN - BAR_ZONE_WIDTH,
    }.get(placement)
    if zone_x is None:
        raise ValueError("bar placement is unsupported")
    return zone_x + (BAR_ZONE_WIDTH - occupied) // 2, bar_width, occupied


def progress_pixels(progress: float) -> int:
    if not math.isfinite(progress):
        raise ValueError("progress must be finite")
    return min(PROGRESS_WIDTH, max(0, math.floor(progress * PROGRESS_WIDTH)))


def filled_segments(progress: float, segment_count: int) -> int:
    if not math.isfinite(progress):
        raise ValueError("progress must be finite")
    if type(segment_count) is not int or segment_count <= 0:
        raise ValueError("segment_count must be positive")
    return min(segment_count, max(0, math.floor(progress * segment_count)))
