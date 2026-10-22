from __future__ import annotations

from typing import Any, Protocol


class RenderAdmissionCancelled(RuntimeError):
    """A caller cancelled before acquiring process-local render admission."""


class RenderAdmissionLease(Protocol):
    def close(self) -> None: ...

    def __enter__(self) -> RenderAdmissionLease: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...


class RenderAdmissionCoordinator(Protocol):
    """Shared process-local admission for WU2 and authoritative previews."""

    def acquire_wu2(self, cancel_event: Any = None) -> RenderAdmissionLease: ...

    def acquire_preview(self, cancel_event: Any = None) -> RenderAdmissionLease: ...


class PreviewFlightOperation(Protocol):
    """One flight-owned operation that publishes, but never returns, a cache artifact."""

    def run(self, cancel_event: Any = None) -> None: ...

    def close(self) -> None: ...
