from __future__ import annotations

from typing import Any, Protocol

from wrld_video_studio.domain.preview_cache import PREVIEW_ERROR_CODES, PreviewCacheIdentity


class PreviewCoordinationError(RuntimeError):
    """Path-safe preview-facing failure raised by coordination."""

    def __init__(self, code: str, message: str) -> None:
        if code not in PREVIEW_ERROR_CODES:
            raise ValueError("Preview coordination errors must use an approved preview error code.")
        self.code = code
        self.message = message
        super().__init__(message)


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


class PreviewFlightCoordinator(Protocol):
    """Coordinate one published artifact per trusted pixel identity."""

    def coordinate(
        self,
        identity: PreviewCacheIdentity,
        operation: PreviewFlightOperation,
        cancel_event: Any = None,
    ) -> None: ...
