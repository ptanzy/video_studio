from __future__ import annotations

from typing import Any

from wrld_video_studio.application.ports.preview_context import (
    PreviewContextError,
    PreviewContextProvider,
)
from wrld_video_studio.application.preview_service import (
    AuthoritativePreviewService,
    PreparedPreview,
    PreviewServiceError,
)
from wrld_video_studio.domain.color_resolution import (
    INPUT_CONTRACT_VERSION,
    ColorResolutionError,
    resolve_color_treatment,
)
from wrld_video_studio.domain.preview_cache import PreviewRequest


class ResolvedPreviewService:
    """Resolve trusted color inputs before invoking authoritative preview work."""

    def __init__(
        self,
        *,
        context_provider: PreviewContextProvider,
        preview_service: AuthoritativePreviewService,
    ) -> None:
        self._context_provider = context_provider
        self._preview_service = preview_service

    def execute(
        self,
        request: PreviewRequest,
        cancel_event: Any = None,
    ) -> PreparedPreview:
        if not isinstance(request, PreviewRequest):
            raise PreviewServiceError(
                "PREVIEW_INVALID_REQUEST", "The preview request is invalid."
            )
        payload: dict[str, object] = {
            "contract_version": INPUT_CONTRACT_VERSION,
            "treatment": request.treatment.to_dict(),
        }
        try:
            if request.treatment.mode == "auto":
                payload["context"] = dict(self._context_provider.context_for(request.target))
            resolution = resolve_color_treatment(payload)
        except PreviewContextError as error:
            failure = PreviewServiceError(error.code, error.message)
            failure.__cause__ = error
            raise failure
        except ColorResolutionError as error:
            failure = PreviewServiceError(
                "PREVIEW_INTERNAL_ERROR",
                "Trusted preview color resolution failed.",
            )
            failure.__cause__ = error
            raise failure
        return self._preview_service.execute(request, resolution, cancel_event)
