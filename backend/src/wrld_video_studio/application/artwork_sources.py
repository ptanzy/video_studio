from __future__ import annotations

from typing import Any

from wrld_video_studio.application.ports.artwork_sources import (
    ArtworkSourceLease,
    ArtworkSourceResolver,
)
from wrld_video_studio.domain.preview_cache import PreviewTarget


class AcquireArtworkSource:
    """Resolve a validated opaque target through the trusted source port."""

    def __init__(self, resolver: ArtworkSourceResolver) -> None:
        self._resolver = resolver

    def execute(self, target: PreviewTarget, cancel_event: Any = None) -> ArtworkSourceLease:
        if not isinstance(target, PreviewTarget):
            raise TypeError("A validated PreviewTarget is required.")
        return self._resolver.acquire(
            target.album_id,
            target.artwork_asset_id,
            cancel_event=cancel_event,
        )
