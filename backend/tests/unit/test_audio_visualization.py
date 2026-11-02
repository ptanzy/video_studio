import math

import pytest

from wrld_video_studio.domain.audio_visualization import (
    BAR_ZONE_HEIGHT,
    SAMPLES_PER_FRAME,
    bar_heights,
    filled_segments,
    output_frame_count,
    progress_pixels,
    rms_to_amplitude,
    smooth_amplitude,
    smoothing_alpha,
    track_index_for_sample,
    track_progress,
)
from wrld_video_studio.domain.video_export import TimelineEntry


def _timeline():
    return (
        TimelineEntry("one", 1, "One", 0, 48_001),
        TimelineEntry("two", 2, "Two", 48_001, 47_999),
    )


def test_frame_mapping_uses_sample_timeline_and_non_aligned_boundary():
    timeline = _timeline()
    assert SAMPLES_PER_FRAME == 1600
    assert track_index_for_sample(timeline, 48_000) == 0
    assert track_index_for_sample(timeline, 49_600) == 1
    assert track_progress(timeline[1], 49_600) == pytest.approx(1599 / 47_999)
    assert output_frame_count(96_000) == 60
    assert output_frame_count(96_001) == 61


def test_rms_dbfs_mapping_has_fixed_silence_and_clamped_bounds():
    assert rms_to_amplitude(0) == 0
    assert rms_to_amplitude(32768 * 10 ** (-60 / 20)) == pytest.approx(0, abs=1e-12)
    assert rms_to_amplitude(32768 * 10 ** (-30 / 20)) == pytest.approx(0.5)
    assert rms_to_amplitude(32768) == pytest.approx(1)
    assert rms_to_amplitude(65536) == 1


def test_attack_release_uses_approved_one_pole_equation():
    attack = smoothing_alpha(60)
    release = smoothing_alpha(240)
    assert attack == pytest.approx(1 - math.exp(-(1 / 30) / 0.060))
    assert release == pytest.approx(1 - math.exp(-(1 / 30) / 0.240))
    risen = smooth_amplitude(0, 1, attack_ms=60, release_ms=240)
    fallen = smooth_amplitude(1, 0, attack_ms=60, release_ms=240)
    assert risen == pytest.approx(attack)
    assert fallen == pytest.approx(1 - release)
    assert smooth_amplitude(0.25, 1, attack_ms=0, release_ms=240) == 1
    assert smooth_amplitude(0.75, 0, attack_ms=60, release_ms=0) == 0


def test_bar_shape_is_symmetric_and_silence_is_two_pixels():
    assert bar_heights(0, 24) == (2,) * 24
    values = bar_heights(1, 24)
    assert values == tuple(reversed(values))
    assert max(values) <= BAR_ZONE_HEIGHT
    assert values[len(values) // 2] > values[0]


def test_progress_geometry_is_clamped_and_segmented_discretely():
    assert progress_pixels(0) == 0
    assert progress_pixels(0.5) == 896
    assert progress_pixels(1) == 1792
    assert filled_segments(0.499, 20) == 9
    assert filled_segments(0.5, 20) == 10
    assert filled_segments(1, 20) == 20

