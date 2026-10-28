import pytest

from wrld_video_studio.domain.camera_motion import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    camera_filter,
    camera_state,
)
from wrld_video_studio.domain.video_effects import PanZoomSettings


def test_disabled_camera_is_static_and_has_no_filter():
    settings = PanZoomSettings(enabled=False)

    assert camera_state(settings, 37, 120) == camera_state(settings, 0, 120)
    assert camera_state(settings, 37, 120).zoom == 1.0
    assert camera_filter(settings, 120) is None


def test_diagonal_down_right_reaches_approved_maximum_at_half_cycle():
    settings = PanZoomSettings(
        enabled=True,
        max_zoom=1.05,
        path="diagonal_down_right",
        cycle_seconds=180,
        return_to_origin=False,
    )

    state = camera_state(settings, 90, 300)
    safe_x = CANVAS_WIDTH - CANVAS_WIDTH / state.zoom
    safe_y = CANVAS_HEIGHT - CANVAS_HEIGHT / state.zoom

    assert state.zoom == pytest.approx(1.05)
    assert state.x == pytest.approx(safe_x)
    assert state.y == pytest.approx(safe_y)


@pytest.mark.parametrize(
    "path", ["center", "horizontal", "vertical", "diagonal_down_right", "diagonal_up_right"]
)
def test_camera_never_leaves_the_crop_safe_rectangle(path):
    settings = PanZoomSettings(
        enabled=True,
        max_zoom=1.05,
        path=path,
        cycle_seconds=15,
        return_to_origin=True,
        return_duration_seconds=3,
    )

    for frame in range(0, 601):
        state = camera_state(settings, frame / 30, 20, final_frame=frame == 600)
        safe_x = CANVAS_WIDTH - CANVAS_WIDTH / state.zoom
        safe_y = CANVAS_HEIGHT - CANVAS_HEIGHT / state.zoom
        assert 1.0 <= state.zoom <= 1.05
        assert -1e-9 <= state.x <= safe_x + 1e-9
        assert -1e-9 <= state.y <= safe_y + 1e-9


def test_cycle_duration_changes_the_deterministic_camera_state():
    fast = PanZoomSettings(enabled=True, cycle_seconds=60, return_to_origin=False)
    slow = PanZoomSettings(enabled=True, cycle_seconds=180, return_to_origin=False)

    assert camera_state(fast, 30, 300).zoom == pytest.approx(1.04)
    assert camera_state(slow, 30, 300).zoom < 1.04


def test_absolute_camera_time_is_continuous_across_track_boundary():
    settings = PanZoomSettings(enabled=True, return_to_origin=False)
    before = camera_state(settings, 12 - 1 / 30, 40)
    at_boundary = camera_state(settings, 12, 40)
    after = camera_state(settings, 12 + 1 / 30, 40)

    assert before.zoom < at_boundary.zoom < after.zoom
    assert abs(after.x - before.x) < 1
    assert abs(after.y - before.y) < 1


def test_return_to_origin_is_continuous_and_finishes_exactly_at_origin():
    settings = PanZoomSettings(
        enabled=True,
        cycle_seconds=60,
        return_to_origin=True,
        return_duration_seconds=5,
    )
    start = camera_state(settings, 15, 20)
    just_after = camera_state(settings, 15 + 1e-6, 20)
    middle = camera_state(settings, 17.5, 20)
    final = camera_state(settings, 20 - 1 / 30, 20, final_frame=True)

    assert just_after.zoom == pytest.approx(start.zoom, abs=1e-10)
    assert 1 < middle.zoom < start.zoom
    assert final.zoom == 1.0
    assert final.x == 0.0
    assert final.y == 0.0


def test_short_video_uses_half_duration_return_window():
    settings = PanZoomSettings(
        enabled=True,
        cycle_seconds=15,
        return_to_origin=True,
        return_duration_seconds=5,
    )

    before_return = camera_state(settings, 1.999, 4)
    returning = camera_state(settings, 3, 4)
    final = camera_state(settings, 4, 4, final_frame=True)

    assert returning.zoom < before_return.zoom
    assert final == camera_state(PanZoomSettings(enabled=False), 0, 4)


def test_disabled_return_ends_at_the_cycle_state_without_forced_reset():
    settings = PanZoomSettings(
        enabled=True,
        cycle_seconds=60,
        return_to_origin=False,
    )

    final = camera_state(settings, 20 - 1 / 30, 20, final_frame=True)

    assert final.zoom > 1.0
    assert final.x > 0.0


def test_filter_is_deterministic_uses_absolute_frame_time_and_forces_final_origin():
    settings = PanZoomSettings(enabled=True, cycle_seconds=180)

    first = camera_filter(settings, 10)
    second = camera_filter(settings, 10)

    assert first == second
    assert "zoompan=" in first
    assert "on/30" in first
    assert "mod(on/30,180)" in first
    assert "gte(on,299)" in first
    assert ":d=1:s=1920x1080:fps=30" in first


def test_preview_filter_uses_absolute_time_without_forcing_preview_end_to_origin():
    settings = PanZoomSettings(enabled=True, return_to_origin=True)
    value = camera_filter(
        settings,
        300.0,
        start_time_seconds=120.0,
        preview=True,
    )
    assert value is not None
    assert "on/30+120" in value
    assert "gte(on," not in value

