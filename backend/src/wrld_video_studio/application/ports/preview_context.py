from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from wrld_video_studio.domain.preview_cache import PREVIEW_ERROR_CODES, PreviewTarget


class PreviewContextError(RuntimeError):
    """Path-safe failure at the trusted automatic-color context boundary."""

    def __init__(self, code: str, message: str) -> None:
        if code not in PREVIEW_ERROR_CODES:
            raise ValueError("Preview context errors must use an approved preview error code.")
        self.code = code
        self.message = message
        super().__init__(message)


class PreviewContextProvider(Protocol):
    """Return server-owned color-resolution context for one exact target."""

    def context_for(self, target: PreviewTarget) -> Mapping[str, Any]: ...
