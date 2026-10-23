import threading
import time

import pytest

from wrld_video_studio.application.render_coordination import (
    PreviewCoordinationError,
    PreviewSingleFlightCoordinator,
    ProcessLocalRenderAdmission,
    _FlightCancellation,
)
from wrld_video_studio.domain.color_resolution import (
    INPUT_CONTRACT_VERSION,
    resolve_color_treatment,
)
from wrld_video_studio.domain.preview_cache import (
    PreviewToolchainIdentity,
    build_preview_cache_identity,
)


def _identity(source="a", *, treatment=None, context=None):
    payload = {
        "contract_version": INPUT_CONTRACT_VERSION,
        "treatment": treatment or {"mode": "preset", "preset": "warm", "intensity": 0.3},
    }
    if context is not None:
        payload["context"] = context
    resolution = resolve_color_treatment(payload)
    return build_preview_cache_identity(
        source_sha256=source * 64,
        resolution=resolution,
        toolchain=PreviewToolchainIdentity.create(
            ffmpeg_sha256="b" * 64,
            ffprobe_sha256="c" * 64,
        ),
    )


class FakeOperation:
    def __init__(
        self,
        *,
        release=None,
        wait_for_cancel=False,
        failure=None,
        close_failure=None,
        active=None,
    ):
        self.release = release
        self.wait_for_cancel = wait_for_cancel
        self.failure = failure
        self.close_failure = close_failure
        self.active = active
        self.started = threading.Event()
        self.cancelled = threading.Event()
        self.closed = threading.Event()
        self.run_count = 0
        self.close_count = 0
        self._guard = threading.Lock()

    def run(self, cancel_event=None):
        with self._guard:
            self.run_count += 1
        if self.active is not None:
            self.active.enter()
        self.started.set()
        try:
            if self.wait_for_cancel:
                assert cancel_event is not None
                assert cancel_event.wait(timeout=5)
                self.cancelled.set()
            elif self.release is not None:
                assert self.release.wait(timeout=5)
            if self.failure is not None:
                raise self.failure
        finally:
            if self.active is not None:
                self.active.exit()

    def close(self):
        with self._guard:
            self.close_count += 1
        self.closed.set()
        if self.close_failure is not None:
            raise self.close_failure


class GatedCancelSignal:
    """Hold a caller between external cancellation polling and coordinator locking."""

    def __init__(self):
        self._cancelled = threading.Event()
        self._guard = threading.Lock()
        self._poll_count = 0
        self.poll_blocked = threading.Event()
        self.release_poll = threading.Event()

    def is_set(self):
        with self._guard:
            self._poll_count += 1
            should_block = self._poll_count == 2
        if should_block:
            self.poll_blocked.set()
            assert self.release_poll.wait(timeout=5)
        return self._cancelled.is_set()

    def set(self):
        self._cancelled.set()


class ControlledEarlyWakeEvent:
    """Return early once, then expose when the corrected wait blocks again."""

    def __init__(self):
        self._event = threading.Event()
        self._guard = threading.Lock()
        self.wait_calls = 0
        self.first_wait_returned = threading.Event()
        self.blocking_wait_entered = threading.Event()

    def is_set(self):
        return self._event.is_set()

    def set(self):
        self._event.set()

    def wait(self, timeout=None):
        with self._guard:
            self.wait_calls += 1
            first = self.wait_calls == 1
        if first:
            self.first_wait_returned.set()
            return False
        self.blocking_wait_entered.set()
        return self._event.wait(timeout)


class BlockingCloseOperation(FakeOperation):
    def __init__(self):
        super().__init__()
        self.close_started = threading.Event()
        self.close_release = threading.Event()

    def close(self):
        with self._guard:
            self.close_count += 1
        self.close_started.set()
        assert self.close_release.wait(timeout=5)
        self.closed.set()


class ActiveCounter:
    def __init__(self):
        self._guard = threading.Lock()
        self.current = 0
        self.maximum = 0

    def enter(self):
        with self._guard:
            self.current += 1
            self.maximum = max(self.maximum, self.current)

    def exit(self):
        with self._guard:
            self.current -= 1


class Call:
    def __init__(self, coordinator, identity, operation, cancel_event=None):
        self.error = None
        self.done = threading.Event()

        def invoke():
            try:
                coordinator.coordinate(identity, operation, cancel_event)
            except BaseException as error:
                self.error = error
            finally:
                self.done.set()

        self.thread = threading.Thread(target=invoke)
        self.thread.start()

    def join(self):
        assert self.done.wait(timeout=5)
        self.thread.join(timeout=5)
        assert not self.thread.is_alive()
        return self.error


def _wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.01)
    raise AssertionError("condition was not reached")


def test_flight_cancellation_wait_ignores_early_wakeup_until_explicit_set():
    signal = _FlightCancellation(time.monotonic() + 5)
    event = ControlledEarlyWakeEvent()
    signal._event = event
    results = []

    waiter = threading.Thread(target=lambda: results.append(signal.wait()))
    waiter.start()
    assert event.first_wait_returned.wait(timeout=5)
    assert event.blocking_wait_entered.wait(timeout=5)
    assert waiter.is_alive()

    signal.set()
    waiter.join(timeout=5)

    assert not waiter.is_alive()
    assert results == [True]
    assert event.wait_calls >= 2


def test_flight_cancellation_wait_ignores_early_wakeup_until_caller_timeout():
    signal = _FlightCancellation(time.monotonic() + 5)
    event = ControlledEarlyWakeEvent()
    signal._event = event

    assert signal.wait(timeout=0.05) is False
    assert event.first_wait_returned.is_set()
    assert event.wait_calls >= 2


@pytest.mark.parametrize("timeout", [None, 1.0])
def test_flight_cancellation_wait_reaches_deadline_without_explicit_set(timeout):
    signal = _FlightCancellation(time.monotonic() + 0.05)
    event = ControlledEarlyWakeEvent()
    signal._event = event

    assert signal.wait(timeout=timeout) is True
    assert event.first_wait_returned.is_set()
    assert event.wait_calls >= 2
    assert event.is_set() is False


def test_flight_cancellation_zero_and_negative_timeouts_are_immediate_polls():
    signal = _FlightCancellation(time.monotonic() + 5)
    event = ControlledEarlyWakeEvent()
    signal._event = event

    assert signal.wait(timeout=0) is False
    assert signal.wait(timeout=-1) is False
    assert event.wait_calls == 0

    signal.set()
    assert signal.wait(timeout=0) is True
    expired = _FlightCancellation(time.monotonic() - 1)
    assert expired.wait(timeout=0) is True


def test_flight_cancellation_explicit_set_wakes_multiple_waiters():
    signal = _FlightCancellation(time.monotonic() + 5)
    results = []
    waiters = [
        threading.Thread(target=lambda: results.append(signal.wait())) for _ in range(4)
    ]
    for waiter in waiters:
        waiter.start()
    _wait_until(lambda: all(waiter.is_alive() for waiter in waiters))

    signal.set()
    for waiter in waiters:
        waiter.join(timeout=5)

    assert all(not waiter.is_alive() for waiter in waiters)
    assert results == [True] * 4


def test_same_key_shares_one_operation_and_closes_unused_operation_once():
    admission = ProcessLocalRenderAdmission()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=5)
    release = threading.Event()
    selected = FakeOperation(release=release)
    unused = FakeOperation()
    first = Call(coordinator, _identity(), selected)
    assert selected.started.wait(timeout=5)
    second = Call(coordinator, _identity(), unused)
    assert unused.closed.wait(timeout=5)
    release.set()
    assert first.join() is None
    assert second.join() is None
    assert selected.run_count == 1 and selected.close_count == 1
    assert unused.run_count == 0 and unused.close_count == 1
    coordinator.close(timeout_seconds=2)


def test_distinct_keys_do_not_coalesce_and_never_run_concurrently():
    admission = ProcessLocalRenderAdmission()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=5)
    active = ActiveCounter()
    first_release = threading.Event()
    second_release = threading.Event()
    first_op = FakeOperation(release=first_release, active=active)
    second_op = FakeOperation(release=second_release, active=active)
    first = Call(coordinator, _identity("a"), first_op)
    assert first_op.started.wait(timeout=5)
    second = Call(coordinator, _identity("d"), second_op)
    assert not second_op.started.is_set()
    first_release.set()
    assert second_op.started.wait(timeout=5)
    second_release.set()
    assert first.join() is None and second.join() is None
    assert first_op.run_count == second_op.run_count == 1
    assert active.maximum == 1
    coordinator.close(timeout_seconds=2)


def test_preview_flights_run_fifo():
    admission = ProcessLocalRenderAdmission()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=5)
    order = []
    releases = [threading.Event() for _ in range(3)]

    class OrderedOperation(FakeOperation):
        def __init__(self, index):
            super().__init__(release=releases[index])
            self.index = index

        def run(self, cancel_event=None):
            order.append(self.index)
            super().run(cancel_event)

    operations = [OrderedOperation(index) for index in range(3)]
    calls = []
    for index, operation in enumerate(operations):
        calls.append(Call(coordinator, _identity(chr(ord("a") + index)), operation))
        _wait_until(lambda expected=index + 1: len(coordinator._flights) == expected)
    assert operations[0].started.wait(timeout=5)
    releases[0].set()
    assert operations[1].started.wait(timeout=5)
    releases[1].set()
    assert operations[2].started.wait(timeout=5)
    releases[2].set()
    assert all(call.join() is None for call in calls)
    assert order == [0, 1, 2]
    coordinator.close(timeout_seconds=2)


def test_preview_waits_for_wu2_and_shared_admission_prevents_overlap():
    admission = ProcessLocalRenderAdmission()
    wu2 = admission.acquire_wu2()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=5)
    operation = FakeOperation()
    call = Call(coordinator, _identity(), operation)
    _wait_until(lambda: admission.waiting_counts == (0, 1))
    assert admission.active_kind == "wu2"
    assert not operation.started.is_set()
    wu2.close()
    assert operation.started.wait(timeout=5)
    assert call.join() is None
    assert admission.active_kind is None
    coordinator.close(timeout_seconds=2)


def test_request_provenance_does_not_change_pixel_flight_identity():
    custom = _identity(
        treatment={"mode": "custom", "hex": "#123456", "intensity": 0.3}
    )
    automatic = _identity(
        treatment={"mode": "auto", "intensity": 0.3},
        context={"album_palette": [{"hex": "#123456", "name": "same pixels"}]},
    )
    assert custom.preview_id == automatic.preview_id
    assert custom.resolution != automatic.resolution
    admission = ProcessLocalRenderAdmission()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=5)
    release = threading.Event()
    selected = FakeOperation(release=release)
    unused = FakeOperation()
    first = Call(coordinator, custom, selected)
    assert selected.started.wait(timeout=5)
    second = Call(coordinator, automatic, unused)
    assert unused.closed.wait(timeout=5)
    release.set()
    assert first.join() is None and second.join() is None
    assert selected.run_count == 1 and unused.run_count == 0
    coordinator.close(timeout_seconds=2)


def test_admission_is_nonpreemptive_and_strictly_prioritizes_fifo_wu2():
    admission = ProcessLocalRenderAdmission()
    active_preview = admission.acquire_preview()
    order = []
    wu2_release = threading.Event()

    def preview_waiter():
        with admission.acquire_preview():
            order.append("preview")

    def wu2_waiter():
        with admission.acquire_wu2():
            order.append("wu2")
            assert wu2_release.wait(timeout=5)

    preview_thread = threading.Thread(target=preview_waiter)
    wu2_thread = threading.Thread(target=wu2_waiter)
    preview_thread.start()
    wu2_thread.start()
    _wait_until(lambda: admission.waiting_counts == (1, 1))
    assert admission.active_kind == "preview"
    active_preview.close()
    _wait_until(lambda: order == ["wu2"])
    assert admission.active_kind == "wu2"
    wu2_release.set()
    preview_thread.join(timeout=5)
    wu2_thread.join(timeout=5)
    assert order == ["wu2", "preview"]
    assert admission.active_kind is None


def test_admission_preserves_fifo_within_each_class_and_lease_close_is_idempotent():
    admission = ProcessLocalRenderAdmission()
    active = admission.acquire_preview()
    order = []
    releases = [threading.Event(), threading.Event()]

    def wait_wu2(index):
        with admission.acquire_wu2():
            order.append(index)
            assert releases[index].wait(timeout=5)

    threads = [threading.Thread(target=wait_wu2, args=(index,)) for index in range(2)]
    threads[0].start()
    _wait_until(lambda: admission.waiting_counts[0] == 1)
    threads[1].start()
    _wait_until(lambda: admission.waiting_counts[0] == 2)
    active.close()
    active.close()
    _wait_until(lambda: order == [0])
    releases[0].set()
    _wait_until(lambda: order == [0, 1])
    releases[1].set()
    for thread in threads:
        thread.join(timeout=5)
    assert order == [0, 1]


def test_four_waiters_are_allowed_and_fifth_is_rejected_for_active_flight():
    admission = ProcessLocalRenderAdmission()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=5)
    release = threading.Event()
    selected = FakeOperation(release=release)
    sponsor = Call(coordinator, _identity(), selected)
    assert selected.started.wait(timeout=5)
    followers = []
    for _ in range(4):
        operation = FakeOperation()
        call = Call(coordinator, _identity(), operation)
        assert operation.closed.wait(timeout=5)
        followers.append(call)
    _wait_until(lambda: coordinator._waiting_callers == 4)
    rejected = FakeOperation()
    with pytest.raises(PreviewCoordinationError) as caught:
        coordinator.coordinate(_identity(), rejected)
    assert caught.value.code == "PREVIEW_CAPACITY_EXHAUSTED"
    assert rejected.close_count == 1
    release.set()
    assert sponsor.join() is None
    assert all(call.join() is None for call in followers)
    coordinator.close(timeout_seconds=2)


def test_queued_first_caller_counts_and_abandoned_queued_flight_never_runs():
    admission = ProcessLocalRenderAdmission()
    wu2 = admission.acquire_wu2()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=5)
    cancel = threading.Event()
    operation = FakeOperation()
    call = Call(coordinator, _identity(), operation, cancel)
    _wait_until(lambda: coordinator._waiting_callers == 1)
    cancel.set()
    error = call.join()
    assert isinstance(error, PreviewCoordinationError)
    assert error.code == "PREVIEW_CANCELLED"
    assert operation.closed.wait(timeout=5)
    assert operation.run_count == 0 and operation.close_count == 1
    wu2.close()
    coordinator.close(timeout_seconds=2)


def test_follower_cancellation_does_not_cancel_shared_work():
    admission = ProcessLocalRenderAdmission()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=5)
    release = threading.Event()
    selected = FakeOperation(release=release)
    sponsor = Call(coordinator, _identity(), selected)
    assert selected.started.wait(timeout=5)
    follower_cancel = threading.Event()
    follower = Call(coordinator, _identity(), FakeOperation(), follower_cancel)
    _wait_until(lambda: coordinator._waiting_callers == 1)
    follower_cancel.set()
    error = follower.join()
    assert isinstance(error, PreviewCoordinationError) and error.code == "PREVIEW_CANCELLED"
    assert not selected.cancelled.is_set()
    release.set()
    assert sponsor.join() is None
    coordinator.close(timeout_seconds=2)


def test_sponsor_cancellation_promotes_oldest_follower():
    admission = ProcessLocalRenderAdmission()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=5)
    release = threading.Event()
    selected = FakeOperation(release=release)
    sponsor_cancel = threading.Event()
    sponsor = Call(coordinator, _identity(), selected, sponsor_cancel)
    assert selected.started.wait(timeout=5)
    follower = Call(coordinator, _identity(), FakeOperation())
    _wait_until(lambda: coordinator._waiting_callers == 1)
    sponsor_cancel.set()
    error = sponsor.join()
    assert isinstance(error, PreviewCoordinationError) and error.code == "PREVIEW_CANCELLED"
    _wait_until(lambda: coordinator._waiting_callers == 0)
    assert not selected.cancelled.is_set()
    release.set()
    assert follower.join() is None
    coordinator.close(timeout_seconds=2)


def test_last_active_caller_cancels_shared_operation_and_key_can_retry():
    admission = ProcessLocalRenderAdmission()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=5)
    cancel = threading.Event()
    cancelled_operation = FakeOperation(wait_for_cancel=True)
    first = Call(coordinator, _identity(), cancelled_operation, cancel)
    assert cancelled_operation.started.wait(timeout=5)
    cancel.set()
    error = first.join()
    assert isinstance(error, PreviewCoordinationError) and error.code == "PREVIEW_CANCELLED"
    assert cancelled_operation.cancelled.wait(timeout=5)
    assert cancelled_operation.closed.wait(timeout=5)
    _wait_until(lambda: not coordinator._flights)
    retry_operation = FakeOperation()
    retry = Call(coordinator, _identity(), retry_operation)
    assert retry.join() is None
    assert retry_operation.run_count == 1 and retry_operation.close_count == 1
    coordinator.close(timeout_seconds=2)


def test_fixed_deadline_is_not_extended_by_late_follower_and_times_out_path_safely():
    admission = ProcessLocalRenderAdmission()
    wu2 = admission.acquire_wu2()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=0.25)
    first = Call(coordinator, _identity(), FakeOperation())
    _wait_until(lambda: bool(coordinator._flights))
    original_deadline = next(iter(coordinator._flights.values())).deadline
    follower = Call(coordinator, _identity(), FakeOperation())
    assert next(iter(coordinator._flights.values())).deadline == original_deadline
    first_error = first.join()
    follower_error = follower.join()
    assert first_error.code == follower_error.code == "PREVIEW_TIMEOUT"
    wu2.close()
    coordinator.close(timeout_seconds=2)


def test_active_flight_deadline_cancels_and_reaps_owned_operation():
    admission = ProcessLocalRenderAdmission()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=0.1)
    operation = FakeOperation(wait_for_cancel=True)
    call = Call(coordinator, _identity(), operation)
    assert operation.started.wait(timeout=5)
    error = call.join()
    assert isinstance(error, PreviewCoordinationError)
    assert error.code == "PREVIEW_TIMEOUT"
    assert operation.cancelled.wait(timeout=5)
    assert operation.closed.wait(timeout=5)
    coordinator.close(timeout_seconds=2)


def test_completion_before_fixed_deadline_publishes_success_atomically():
    admission = ProcessLocalRenderAdmission()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=5)
    release = threading.Event()
    caller_signal = GatedCancelSignal()
    operation = FakeOperation(release=release)
    call = Call(coordinator, _identity(), operation, caller_signal)
    assert operation.started.wait(timeout=5)
    assert caller_signal.poll_blocked.wait(timeout=5)
    with coordinator._condition:
        flight = next(iter(coordinator._flights.values()))
        flight.deadline = time.monotonic() + 60
    release.set()
    _wait_until(lambda: not coordinator._flights)
    caller_signal.release_poll.set()
    assert call.join() is None
    assert operation.close_count == 1
    coordinator.close(timeout_seconds=2)


def test_late_completion_times_out_all_callers_without_capacity_or_key_leaks():
    admission = ProcessLocalRenderAdmission()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=5)
    release = threading.Event()
    first_signal = GatedCancelSignal()
    second_signal = GatedCancelSignal()
    selected = FakeOperation(release=release)
    unused = FakeOperation()
    first = Call(coordinator, _identity(), selected, first_signal)
    assert selected.started.wait(timeout=5)
    assert first_signal.poll_blocked.wait(timeout=5)
    second = Call(coordinator, _identity(), unused, second_signal)
    assert unused.closed.wait(timeout=5)
    assert second_signal.poll_blocked.wait(timeout=5)
    with coordinator._condition:
        flight = next(iter(coordinator._flights.values()))
        flight.deadline = time.monotonic() - 1
    release.set()
    _wait_until(lambda: not coordinator._flights)
    first_signal.release_poll.set()
    second_signal.release_poll.set()
    for call in (first, second):
        error = call.join()
        assert isinstance(error, PreviewCoordinationError)
        assert error.code == "PREVIEW_TIMEOUT"
    assert coordinator._waiting_callers == 0
    assert selected.close_count == 1
    assert unused.close_count == 1
    retry = FakeOperation()
    assert Call(coordinator, _identity(), retry).join() is None
    coordinator.close(timeout_seconds=2)


def test_published_completion_wins_over_cancellation_not_yet_established_under_lock():
    admission = ProcessLocalRenderAdmission()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=5)
    release = threading.Event()
    caller_signal = GatedCancelSignal()
    operation = FakeOperation(release=release)
    call = Call(coordinator, _identity(), operation, caller_signal)
    assert operation.started.wait(timeout=5)
    assert caller_signal.poll_blocked.wait(timeout=5)
    caller_signal.set()
    release.set()
    _wait_until(lambda: not coordinator._flights)
    caller_signal.release_poll.set()
    assert call.join() is None
    coordinator.close(timeout_seconds=2)


def test_established_caller_cancellation_wins_before_flight_completion():
    admission = ProcessLocalRenderAdmission()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=5)
    release = threading.Event()
    cancel = threading.Event()
    operation = FakeOperation(release=release)
    call = Call(coordinator, _identity(), operation, cancel)
    assert operation.started.wait(timeout=5)
    cancel.set()
    error = call.join()
    assert isinstance(error, PreviewCoordinationError)
    assert error.code == "PREVIEW_CANCELLED"
    release.set()
    assert operation.closed.wait(timeout=5)
    coordinator.close(timeout_seconds=2)


def test_flight_failure_wakes_all_callers_closes_once_and_allows_retry():
    admission = ProcessLocalRenderAdmission()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=5)
    release = threading.Event()
    failed = FakeOperation(
        release=release,
        failure=PreviewCoordinationError("PREVIEW_RENDER_FAILED", "Preview rendering failed."),
    )
    first = Call(coordinator, _identity(), failed)
    assert failed.started.wait(timeout=5)
    second = Call(coordinator, _identity(), FakeOperation())
    release.set()
    for call in (first, second):
        error = call.join()
        assert isinstance(error, PreviewCoordinationError)
        assert error.code == "PREVIEW_RENDER_FAILED"
    assert failed.close_count == 1
    retry = FakeOperation()
    assert Call(coordinator, _identity(), retry).join() is None
    assert retry.run_count == 1
    coordinator.close(timeout_seconds=2)


def test_shutdown_cancels_active_work_wakes_callers_and_closes_operation():
    admission = ProcessLocalRenderAdmission()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=5)
    operation = FakeOperation(wait_for_cancel=True)
    call = Call(coordinator, _identity(), operation)
    assert operation.started.wait(timeout=5)
    coordinator.close(timeout_seconds=2)
    error = call.join()
    assert isinstance(error, PreviewCoordinationError) and error.code == "PREVIEW_CANCELLED"
    assert operation.cancelled.is_set()
    assert operation.close_count == 1
    assert admission.active_kind is None
    rejected = FakeOperation()
    with pytest.raises(PreviewCoordinationError) as caught:
        coordinator.coordinate(_identity(), rejected)
    assert caught.value.code == "PREVIEW_INTERNAL_ERROR"
    assert rejected.close_count == 1


def test_shutdown_closes_queued_operations_once_without_waiting_for_admission():
    admission = ProcessLocalRenderAdmission()
    wu2 = admission.acquire_wu2()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=5)
    operations = [FakeOperation(), FakeOperation()]
    calls = [
        Call(coordinator, _identity("a"), operations[0]),
        Call(coordinator, _identity("d"), operations[1]),
    ]
    _wait_until(lambda: len(coordinator._flights) == 2)
    coordinator.close(timeout_seconds=2)
    for call, operation in zip(calls, operations, strict=True):
        error = call.join()
        assert isinstance(error, PreviewCoordinationError)
        assert error.code == "PREVIEW_CANCELLED"
        assert operation.run_count == 0 and operation.close_count == 1
    assert admission.active_kind == "wu2"
    wu2.close()


def test_shutdown_timeout_retains_admission_until_work_actually_terminates():
    admission = ProcessLocalRenderAdmission()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=5)
    release = threading.Event()
    operation = FakeOperation(release=release)
    call = Call(coordinator, _identity(), operation)
    assert operation.started.wait(timeout=5)
    with pytest.raises(PreviewCoordinationError) as caught:
        coordinator.close(timeout_seconds=0.05)
    assert caught.value.code == "PREVIEW_TIMEOUT"
    assert admission.active_kind == "preview"
    assert operation.close_count == 0
    error = call.join()
    assert isinstance(error, PreviewCoordinationError) and error.code == "PREVIEW_CANCELLED"
    release.set()
    assert operation.closed.wait(timeout=5)
    coordinator.close(timeout_seconds=2)
    assert admission.active_kind is None


def test_shutdown_times_out_while_cancelled_queued_flight_cleanup_is_blocked():
    admission = ProcessLocalRenderAdmission()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=5)
    active = FakeOperation(wait_for_cancel=True)
    active_call = Call(coordinator, _identity("a"), active)
    assert active.started.wait(timeout=5)
    queued = BlockingCloseOperation()
    queued_cancel = threading.Event()
    queued_call = Call(coordinator, _identity("d"), queued, queued_cancel)
    _wait_until(lambda: len(coordinator._flights) == 2)
    queued_cancel.set()
    assert queued.close_started.wait(timeout=5)
    with pytest.raises(PreviewCoordinationError) as caught:
        coordinator.close(timeout_seconds=0.1)
    assert caught.value.code == "PREVIEW_TIMEOUT"
    assert queued.close_count == 1
    assert not queued.closed.is_set()
    assert coordinator._detached_cleanups
    queued.close_release.set()
    queued_error = queued_call.join()
    assert isinstance(queued_error, PreviewCoordinationError)
    assert queued_error.code == "PREVIEW_CANCELLED"
    _wait_until(lambda: not coordinator._detached_cleanups)
    active_error = active_call.join()
    assert isinstance(active_error, PreviewCoordinationError)
    assert active_error.code == "PREVIEW_CANCELLED"
    coordinator.close(timeout_seconds=2)
    assert queued.close_count == 1


def test_shutdown_waits_for_cancelled_queued_flight_cleanup_and_closes_once():
    admission = ProcessLocalRenderAdmission()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=5)
    active = FakeOperation(wait_for_cancel=True)
    active_call = Call(coordinator, _identity("a"), active)
    assert active.started.wait(timeout=5)
    queued = BlockingCloseOperation()
    queued_cancel = threading.Event()
    queued_call = Call(coordinator, _identity("d"), queued, queued_cancel)
    _wait_until(lambda: len(coordinator._flights) == 2)
    queued_cancel.set()
    assert queued.close_started.wait(timeout=5)
    shutdown_done = threading.Event()
    shutdown_errors = []

    def shutdown():
        try:
            coordinator.close(timeout_seconds=2)
        except BaseException as error:
            shutdown_errors.append(error)
        finally:
            shutdown_done.set()

    shutdown_thread = threading.Thread(target=shutdown)
    shutdown_thread.start()
    _wait_until(lambda: not coordinator._accepting)
    assert not shutdown_done.is_set()
    queued.close_release.set()
    assert shutdown_done.wait(timeout=5)
    shutdown_thread.join(timeout=5)
    assert not shutdown_errors
    assert queued.close_count == 1
    queued_error = queued_call.join()
    active_error = active_call.join()
    assert queued_error.code == active_error.code == "PREVIEW_CANCELLED"
    assert not coordinator._detached_cleanups


def test_shutdown_reports_operation_cleanup_failure_path_safely():
    admission = ProcessLocalRenderAdmission()
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=5)
    operation = FakeOperation(
        wait_for_cancel=True,
        close_failure=OSError(r"private C:\cache\flight path"),
    )
    call = Call(coordinator, _identity(), operation)
    assert operation.started.wait(timeout=5)
    with pytest.raises(PreviewCoordinationError) as caught:
        coordinator.close(timeout_seconds=2)
    assert caught.value.code == "PREVIEW_INTERNAL_ERROR"
    assert "cache" not in caught.value.message.lower()
    assert operation.close_count == 1
    caller_error = call.join()
    assert isinstance(caller_error, PreviewCoordinationError)
    assert caller_error.code == "PREVIEW_CANCELLED"


@pytest.mark.parametrize("value", [None, 0, -1, float("inf"), float("nan"), True])
def test_wait_and_shutdown_timeouts_must_be_positive_finite(value):
    admission = ProcessLocalRenderAdmission()
    with pytest.raises(ValueError):
        PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=value)
    coordinator = PreviewSingleFlightCoordinator(admission, wait_timeout_seconds=1)
    with pytest.raises(ValueError):
        coordinator.close(timeout_seconds=value)
    coordinator.close(timeout_seconds=2)
