from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from wrld_video_studio.domain.preview_cache import PREVIEW_ERROR_CODES, PreviewCacheIdentity


PREVIEW_CACHE_MANIFEST_VERSION = "preview-cache-entry-v1"


@dataclass(frozen=True, slots=True)
class CachedPreviewArtifact:
    """Verified metadata for one immutable cached PNG."""

    preview_id: str
    artifact_sha256: str
    byte_size: int
    width: int
    height: int
    media_type: str = "image/png"


class PreviewCacheError(RuntimeError):
    """Path-safe preview-facing failure raised by the cache boundary."""

    def __init__(self, code: str, message: str) -> None:
        if code not in PREVIEW_ERROR_CODES:
            raise ValueError("Preview cache errors must use an approved preview error code.")
        self.code = code
        self.message = message
        super().__init__(message)


class PreviewArtifactLease(Protocol):
    """Pinned read handle. Closing it is required before the entry can be evicted."""

    @property
    def artifact(self) -> CachedPreviewArtifact: ...

    def read(self, amount: int = -1) -> bytes: ...

    def seek(self, offset: int, whence: int = 0) -> int: ...

    def close(self) -> None: ...

    def __enter__(self) -> PreviewArtifactLease: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...


class PreviewCacheStagingLease(Protocol):
    """Request-owned private staging location for an authoritative PNG writer."""

    @property
    def output_path(self) -> Path: ...

    def publish(
        self,
        *,
        width: int,
        height: int,
        cancel_event: Any = None,
    ) -> PreviewArtifactLease: ...

    def close(self) -> None: ...

    def __enter__(self) -> PreviewCacheStagingLease: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...


class PreviewCacheStore(Protocol):
    def lookup(
        self,
        identity: PreviewCacheIdentity,
        cancel_event: Any = None,
    ) -> PreviewArtifactLease | None: ...

    def begin_write(self, identity: PreviewCacheIdentity) -> PreviewCacheStagingLease: ...

    def discard_corrupt(self, identity: PreviewCacheIdentity) -> bool: ...

    def enforce_limits(self) -> None: ...

    def close(self) -> None: ...

    def __enter__(self) -> PreviewCacheStore: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...
