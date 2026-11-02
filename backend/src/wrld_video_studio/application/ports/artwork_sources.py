from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from wrld_video_studio.domain.preview_cache import PREVIEW_ERROR_CODES


@dataclass(frozen=True, slots=True)
class ArtworkSourceSnapshot:
    """Read-only, request-owned source material acquired by a trusted adapter."""

    album_id: str
    artwork_asset_id: str
    snapshot_path: Path
    source_sha256: str
    byte_size: int


class ArtworkSourceError(RuntimeError):
    """Path-safe preview-facing failure raised by the source boundary."""

    def __init__(self, code: str, message: str) -> None:
        if code not in PREVIEW_ERROR_CODES:
            raise ValueError("Artwork source errors must use an approved preview error code.")
        self.code = code
        self.message = message
        super().__init__(message)


class ArtworkSourceLease(Protocol):
    @property
    def snapshot(self) -> ArtworkSourceSnapshot: ...

    def verify_snapshot(self, cancel_event: Any = None) -> None: ...

    def revalidate_source(self, cancel_event: Any = None) -> None: ...

    def close(self) -> None: ...

    def __enter__(self) -> ArtworkSourceLease: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...


class ArtworkSourceResolver(Protocol):
    def acquire(
        self,
        album_id: str,
        artwork_asset_id: str,
        cancel_event: Any = None,
    ) -> ArtworkSourceLease: ...
