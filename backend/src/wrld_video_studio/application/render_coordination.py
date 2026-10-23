from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from wrld_video_studio.application.ports.render_coordination import (
    PreviewCoordinationError,
    PreviewFlightOperation,
    RenderAdmissionCancelled,
    RenderAdmissionCoordinator,
    RenderAdmissionLease,
)
from wrld_video_studio.domain.preview_cache import (
    DEFAULT_PREVIEW_MAX_WAITING_REQUESTS,
    PreviewCacheIdentity,
)


_WAIT_POLL_SECONDS = 0.05


@dataclass(slots=True)
class _AdmissionWaiter:
    token: object = field(default_factory=object)


class _AdmissionLease(RenderAdmissionLease):
    def __init__(self, owner: ProcessLocalRenderAdmission, token: object) -> None:
        self._owner = owner
        self._token = token
        self._guard = threading.Lock()
        self._closed = False

    def close(self) -> None:
        with self._guard:
            if self._closed:
                return
            self._closed = True
        self._owner._release(self._token)

    def __enter__(self) -> _AdmissionLease:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class ProcessLocalRenderAdmission(RenderAdmissionCoordinator):
    """One non-preemptive render slot with strict FIFO WU2 priority."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active_token: object | None = None
        self._active_kind: str | None = None
        self._wu2_waiters: deque[_AdmissionWaiter] = deque()
        self._preview_waiters: deque[_AdmissionWaiter] = deque()

    def acquire_wu2(self, cancel_event: Any = None) -> RenderAdmissionLease:
        return self._acquire(self._wu2_waiters, True, cancel_event)

    def acquire_preview(self, cancel_event: Any = None) -> RenderAdmissionLease:
        return self._acquire(self._preview_waiters, False, cancel_event)

    @property
    def active_kind(self) -> str | None:
        with self._condition:
            return self._active_kind

    @property
    def waiting_counts(self) -> tuple[int, int]:
        with self._condition:
            return len(self._wu2_waiters), len(self._preview_waiters)

    def _acquire(
        self,
        queue: deque[_AdmissionWaiter],
        is_wu2: bool,
        cancel_event: Any,
    ) -> _AdmissionLease:
        waiter = _AdmissionWaiter()
        with self._condition:
            queue.append(waiter)
            self._condition.notify_all()
        while True:
            cancelled = cancel_event is not None and cancel_event.is_set()
            with self._condition:
                if cancelled:
                    try:
                        queue.remove(waiter)
                    except ValueError:
                        pass
                    self._condition.notify_all()
                    raise RenderAdmissionCancelled("Render admission was cancelled.")
                eligible = (
                    self._active_token is None
                    and queue
                    and queue[0] is waiter
                    and (is_wu2 or not self._wu2_waiters)
                )
                if eligible:
                    queue.popleft()
                    self._active_token = waiter.token
                    self._active_kind = "wu2" if is_wu2 else "preview"
                    return _AdmissionLease(self, waiter.token)
                self._condition.wait(timeout=_WAIT_POLL_SECONDS)

    def _release(self, token: object) -> None:
        with self._condition:
            if self._active_token is not token:
                raise RuntimeError("Render admission lease is not active.")
            self._active_token = None
            self._active_kind = None
            self._condition.notify_all()


@dataclass(slots=True)
class _FlightFailure:
    code: str
    message: str
    cause: BaseException | None = None


@dataclass(slots=True)
class _FlightCaller:
    sequence: int
    counted_waiting: bool = True
    attached: bool = True
    completed: bool = False
    failure: _FlightFailure | None = None


class _FlightCancellation:
    """Event-compatible cancellation that also becomes set at the fixed deadline."""

    def __init__(self, deadline: float) -> None:
        self._deadline = deadline
        self._event = threading.Event()

    def is_set(self) -> bool:
        return self._event.is_set() or time.monotonic() >= self._deadline

    def set(self) -> None:
        self._event.set()

    def wait(self, timeout: float | None = None) -> bool:
        caller_deadline = (
            None if timeout is None else time.monotonic() + max(0.0, timeout)
        )
        while True:
            if self._event.is_set():
                return True
            now = time.monotonic()
            if now >= self._deadline:
                return True
            if caller_deadline is not None and now >= caller_deadline:
                return False
            remaining = self._deadline - now
            if caller_deadline is not None:
                remaining = min(remaining, caller_deadline - now)
            self._event.wait(timeout=max(0.0, remaining))


@dataclass(slots=True)
class _PreviewFlight:
    key: str
    operation: PreviewFlightOperation
    deadline: float
    sequence: int
    cancel_event: _FlightCancellation
    callers: deque[_FlightCaller] = field(default_factory=deque)
    sponsor: _FlightCaller | None = None
    state: str = "queued"
    operation_close_claimed: bool = False
    detached_cleanup_completed_at: float | None = None


class PreviewSingleFlightCoordinator:
    """Bounded same-key preview coordination independent of caller lifetime."""

    def __init__(
        self,
        admission: RenderAdmissionCoordinator,
        *,
        wait_timeout_seconds: float,
        max_waiting_callers: int = DEFAULT_PREVIEW_MAX_WAITING_REQUESTS,
    ) -> None:
        self._wait_timeout_seconds = _positive_finite(
            wait_timeout_seconds, "Preview wait timeout"
        )
        if (
            type(max_waiting_callers) is not int
            or max_waiting_callers < 1
            or max_waiting_callers > DEFAULT_PREVIEW_MAX_WAITING_REQUESTS
        ):
            raise ValueError("Preview waiting capacity must be between one and four callers.")
        self._admission = admission
        self._max_waiting_callers = max_waiting_callers
        self._condition = threading.Condition()
        self._queue: deque[_PreviewFlight] = deque()
        self._flights: dict[str, _PreviewFlight] = {}
        self._waiting_callers = 0
        self._next_sequence = 0
        self._accepting = True
        self._worker_finished = False
        self._worker_finished_at: float | None = None
        self._shutdown_failure: _FlightFailure | None = None
        self._detached_cleanups: dict[int, _PreviewFlight] = {}
        self._thread = threading.Thread(
            target=self._worker_main,
            name="wrld-preview-single-flight",
            daemon=False,
        )
        self._thread.start()

    def coordinate(
        self,
        identity: PreviewCacheIdentity,
        operation: PreviewFlightOperation,
        cancel_event: Any = None,
    ) -> None:
        if not isinstance(identity, PreviewCacheIdentity):
            _close_rejected_operation(operation)
            raise TypeError("A trusted PreviewCacheIdentity is required.")
        if cancel_event is not None and cancel_event.is_set():
            _close_rejected_operation(operation)
            raise PreviewCoordinationError("PREVIEW_CANCELLED", "Preview request was cancelled.")

        now = time.monotonic()
        adopted = False
        close_owned: PreviewFlightOperation | None = None
        caller: _FlightCaller | None = None
        flight: _PreviewFlight | None = None
        rejection: PreviewCoordinationError | None = None
        with self._condition:
            if not self._accepting:
                rejection = PreviewCoordinationError(
                    "PREVIEW_INTERNAL_ERROR", "Preview coordination is shutting down."
                )
            elif self._waiting_callers >= self._max_waiting_callers:
                rejection = PreviewCoordinationError(
                    "PREVIEW_CAPACITY_EXHAUSTED", "Preview waiting capacity is exhausted."
                )
            else:
                flight = self._flights.get(identity.preview_id)
                self._next_sequence += 1
                caller = _FlightCaller(sequence=self._next_sequence)
                self._waiting_callers += 1
                if flight is None:
                    adopted = True
                    deadline = now + self._wait_timeout_seconds
                    flight = _PreviewFlight(
                        key=identity.preview_id,
                        operation=operation,
                        deadline=deadline,
                        sequence=self._next_sequence,
                        cancel_event=_FlightCancellation(deadline),
                    )
                    flight.callers.append(caller)
                    self._flights[flight.key] = flight
                    self._queue.append(flight)
                else:
                    flight.callers.append(caller)
                self._condition.notify_all()

        if rejection is not None:
            close_failure = _close_operation(operation)
            if close_failure is not None:
                raise close_failure
            raise rejection
        assert caller is not None and flight is not None
        if not adopted:
            close_failure = _close_operation(operation)
            if close_failure is not None:
                self._detach_caller(flight, caller)
                raise close_failure

        while True:
            cancelled = cancel_event is not None and cancel_event.is_set()
            now = time.monotonic()
            with self._condition:
                if caller.completed:
                    failure = caller.failure
                    break
                if cancelled:
                    close_owned = self._detach_caller_locked(
                        flight,
                        caller,
                        _FlightFailure("PREVIEW_CANCELLED", "Preview request was cancelled."),
                    )
                    failure = caller.failure
                    self._condition.notify_all()
                    break
                if now >= flight.deadline:
                    close_owned = self._detach_caller_locked(
                        flight,
                        caller,
                        _FlightFailure("PREVIEW_TIMEOUT", "Preview request timed out."),
                    )
                    failure = caller.failure
                    self._condition.notify_all()
                    break
                remaining = max(0.0, flight.deadline - now)
                self._condition.wait(timeout=min(_WAIT_POLL_SECONDS, remaining))
                continue

        if close_owned is not None:
            close_failure = _close_operation(close_owned)
            self._finish_detached_cleanup(flight, close_failure)
            if close_failure is not None and failure is None:
                failure = _FlightFailure(close_failure.code, close_failure.message, close_failure)
        if failure is not None:
            error = PreviewCoordinationError(failure.code, failure.message)
            if failure.cause is not None:
                error.__cause__ = failure.cause
            raise error

    def close(self, *, timeout_seconds: float) -> None:
        timeout = _positive_finite(timeout_seconds, "Preview shutdown timeout")
        deadline = time.monotonic() + timeout
        events: list[threading.Event] = []
        already_finished = False
        detached_cleanups: tuple[_PreviewFlight, ...]
        with self._condition:
            if self._worker_finished:
                self._accepting = False
                already_finished = True
            else:
                self._accepting = False
                for flight in tuple(self._flights.values()):
                    events.append(flight.cancel_event)
                    self._complete_callers_locked(
                        flight,
                        _FlightFailure(
                            "PREVIEW_CANCELLED", "Preview coordination is shutting down."
                        ),
                    )
                    if self._flights.get(flight.key) is flight:
                        self._flights.pop(flight.key, None)
                self._condition.notify_all()
            detached_cleanups = tuple(self._detached_cleanups.values())
        if not already_finished:
            for event in events:
                event.set()
            remaining = max(0.0, deadline - time.monotonic())
            self._thread.join(timeout=remaining)
            if self._thread.is_alive():
                raise PreviewCoordinationError(
                    "PREVIEW_TIMEOUT", "Preview coordination shutdown exceeded its time limit."
                )
            with self._condition:
                worker_finished_at = self._worker_finished_at
            if worker_finished_at is None or worker_finished_at >= deadline:
                raise PreviewCoordinationError(
                    "PREVIEW_TIMEOUT", "Preview coordination shutdown exceeded its time limit."
                )
        with self._condition:
            while self._detached_cleanups:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PreviewCoordinationError(
                        "PREVIEW_TIMEOUT",
                        "Preview coordination shutdown exceeded its time limit.",
                    )
                self._condition.wait(timeout=remaining)
            if any(
                flight.detached_cleanup_completed_at is None
                or flight.detached_cleanup_completed_at >= deadline
                for flight in detached_cleanups
            ):
                raise PreviewCoordinationError(
                    "PREVIEW_TIMEOUT", "Preview coordination shutdown exceeded its time limit."
                )
        self._raise_shutdown_failure()

    def _worker_main(self) -> None:
        try:
            while True:
                with self._condition:
                    while not self._queue:
                        if not self._accepting:
                            return
                        self._condition.wait()
                    flight = self._queue.popleft()
                    if flight.state != "queued" or flight.operation_close_claimed:
                        continue
                    flight.state = "waiting_admission"
                self._run_flight(flight)
        finally:
            finished_at = time.monotonic()
            with self._condition:
                self._worker_finished = True
                self._worker_finished_at = finished_at
                self._condition.notify_all()

    def _run_flight(self, flight: _PreviewFlight) -> None:
        failure: _FlightFailure | None = None
        operation_completed_at: float | None = None
        operation = flight.operation
        try:
            with self._admission.acquire_preview(flight.cancel_event):
                with self._condition:
                    if not self._attached_callers_locked(flight):
                        return
                    flight.state = "active"
                    self._promote_sponsor_locked(flight)
                    self._condition.notify_all()
                operation.run(flight.cancel_event)
                operation_completed_at = time.monotonic()
        except RenderAdmissionCancelled as error:
            if self._attached_callers(flight):
                if time.monotonic() >= flight.deadline:
                    failure = _FlightFailure("PREVIEW_TIMEOUT", "Preview request timed out.", error)
                else:
                    failure = _FlightFailure("PREVIEW_CANCELLED", "Preview rendering was cancelled.", error)
        except PreviewCoordinationError as error:
            if error.code == "PREVIEW_CANCELLED" and time.monotonic() >= flight.deadline:
                failure = _FlightFailure("PREVIEW_TIMEOUT", "Preview request timed out.", error)
            else:
                failure = _FlightFailure(error.code, error.message, error)
        except Exception as error:
            failure = _FlightFailure(
                "PREVIEW_INTERNAL_ERROR", "Preview rendering failed unexpectedly.", error
            )
        finally:
            close_failure = self._close_flight_operation(flight)
            if failure is None and close_failure is not None:
                failure = _FlightFailure(close_failure.code, close_failure.message, close_failure)
            with self._condition:
                # Operation return is the flight-completion instant. A return at
                # the fixed deadline is late even if a waiting caller has not yet
                # been scheduled to establish its own timeout. Caller cancellation
                # and completion otherwise linearize at their first transition
                # while holding this condition.
                if (
                    failure is None
                    and operation_completed_at is not None
                    and operation_completed_at >= flight.deadline
                ):
                    failure = _FlightFailure(
                        "PREVIEW_TIMEOUT", "Preview request timed out."
                    )
                if (
                    close_failure is not None
                    and not self._accepting
                    and self._shutdown_failure is None
                ):
                    self._shutdown_failure = _FlightFailure(
                        close_failure.code,
                        close_failure.message,
                        close_failure,
                    )
                self._complete_callers_locked(flight, failure)
                flight.state = "finished"
                if self._flights.get(flight.key) is flight:
                    self._flights.pop(flight.key, None)
                self._condition.notify_all()

    def _detach_caller(self, flight: _PreviewFlight, caller: _FlightCaller) -> None:
        operation: PreviewFlightOperation | None
        with self._condition:
            operation = self._detach_caller_locked(
                flight,
                caller,
                _FlightFailure("PREVIEW_INTERNAL_ERROR", "Preview request setup failed."),
            )
            self._condition.notify_all()
        if operation is not None:
            failure = _close_operation(operation)
            self._finish_detached_cleanup(flight, failure)

    def _detach_caller_locked(
        self,
        flight: _PreviewFlight,
        caller: _FlightCaller,
        failure: _FlightFailure,
    ) -> PreviewFlightOperation | None:
        if not caller.attached:
            return None
        caller.attached = False
        caller.completed = True
        caller.failure = failure
        if caller.counted_waiting:
            caller.counted_waiting = False
            self._waiting_callers -= 1
        elif flight.sponsor is caller:
            flight.sponsor = None
            self._promote_sponsor_locked(flight)
        if self._attached_callers_locked(flight):
            return None
        flight.cancel_event.set()
        if self._flights.get(flight.key) is flight:
            self._flights.pop(flight.key, None)
        if flight.state == "queued":
            flight.state = "abandoned"
            operation = self._claim_operation_close_locked(flight)
            if operation is not None:
                self._detached_cleanups[flight.sequence] = flight
            return operation
        return None

    def _finish_detached_cleanup(
        self,
        flight: _PreviewFlight,
        failure: PreviewCoordinationError | None,
    ) -> None:
        completed_at = time.monotonic()
        with self._condition:
            owned = self._detached_cleanups.pop(flight.sequence, None)
            if owned is not flight:
                raise RuntimeError("Detached preview cleanup ownership was lost.")
            flight.state = "finished"
            flight.detached_cleanup_completed_at = completed_at
            if failure is not None and self._shutdown_failure is None:
                self._shutdown_failure = _FlightFailure(
                    failure.code,
                    failure.message,
                    failure,
                )
            self._condition.notify_all()

    def _promote_sponsor_locked(self, flight: _PreviewFlight) -> None:
        if flight.sponsor is not None and flight.sponsor.attached:
            return
        for caller in flight.callers:
            if not caller.attached:
                continue
            flight.sponsor = caller
            if caller.counted_waiting:
                caller.counted_waiting = False
                self._waiting_callers -= 1
            return

    def _complete_callers_locked(
        self,
        flight: _PreviewFlight,
        failure: _FlightFailure | None,
    ) -> None:
        for caller in flight.callers:
            if not caller.attached:
                continue
            caller.attached = False
            caller.completed = True
            caller.failure = failure
            if caller.counted_waiting:
                caller.counted_waiting = False
                self._waiting_callers -= 1
        flight.sponsor = None

    def _attached_callers(self, flight: _PreviewFlight) -> bool:
        with self._condition:
            return self._attached_callers_locked(flight)

    @staticmethod
    def _attached_callers_locked(flight: _PreviewFlight) -> bool:
        return any(caller.attached for caller in flight.callers)

    def _close_flight_operation(
        self, flight: _PreviewFlight
    ) -> PreviewCoordinationError | None:
        with self._condition:
            operation = self._claim_operation_close_locked(flight)
        return None if operation is None else _close_operation(operation)

    def _raise_shutdown_failure(self) -> None:
        with self._condition:
            failure = self._shutdown_failure
        if failure is None:
            return
        error = PreviewCoordinationError(failure.code, failure.message)
        if failure.cause is not None:
            error.__cause__ = failure.cause
        raise error

    @staticmethod
    def _claim_operation_close_locked(
        flight: _PreviewFlight,
    ) -> PreviewFlightOperation | None:
        if flight.operation_close_claimed:
            return None
        flight.operation_close_claimed = True
        return flight.operation


def _positive_finite(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be a positive finite number.")
    return float(value)


def _close_rejected_operation(operation: PreviewFlightOperation) -> None:
    failure = _close_operation(operation)
    if failure is not None:
        raise failure


def _close_operation(operation: PreviewFlightOperation) -> PreviewCoordinationError | None:
    try:
        operation.close()
    except Exception as error:
        failure = PreviewCoordinationError(
            "PREVIEW_INTERNAL_ERROR", "Preview operation cleanup failed."
        )
        failure.__cause__ = error
        return failure
    return None
