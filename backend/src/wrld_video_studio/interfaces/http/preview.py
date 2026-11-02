from __future__ import annotations

import asyncio
import json
import logging
import secrets
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from wrld_video_studio.application.preview_service import PreviewServiceError
from wrld_video_studio.domain.preview_cache import PreviewContractError, PreviewError
from wrld_video_studio.interfaces.http.models import (
    PreviewErrorEnvelopeModel,
    PreviewRequestModel,
)


LOGGER = logging.getLogger(__name__)
MULTIPART_CHUNK_BYTES = 64 * 1024

PREVIEW_HTTP_STATUS = {
    "PREVIEW_INVALID_REQUEST": 422,
    "PREVIEW_SOURCE_UNAVAILABLE": 404,
    "SOURCE_CHANGED": 409,
    "PREVIEW_IMAGE_UNSUPPORTED": 422,
    "PREVIEW_CANCELLED": 408,
    "PREVIEW_TIMEOUT": 504,
    "PREVIEW_CAPACITY_EXHAUSTED": 503,
    "PREVIEW_RENDER_FAILED": 500,
    "PREVIEW_CACHE_CORRUPT": 500,
    "PREVIEW_INTERNAL_ERROR": 500,
}


def _error_responses() -> dict[int, dict[str, object]]:
    return {
        status: {
            "model": PreviewErrorEnvelopeModel,
            "description": "Typed preview failure.",
        }
        for status in sorted(set(PREVIEW_HTTP_STATUS.values()))
    }


router = APIRouter(prefix="/api/v1/previews", tags=["previews"])


@router.post(
    "/still",
    response_model=None,
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Authoritative result metadata and PNG artifact.",
            "content": {
                "multipart/related": {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
        },
        **_error_responses(),
    },
    summary="Render or retrieve an authoritative still preview",
)
async def create_still_preview(
    payload: PreviewRequestModel,
    request: Request,
) -> StreamingResponse | JSONResponse:
    runtime = request.app.state.preview_runtime
    ownership = runtime.begin_request()
    watcher: asyncio.Task[None] | None = None
    work: asyncio.Task[PreparedPreview] | None = None
    transferred = False
    try:
        watcher = asyncio.create_task(_watch_disconnect(request, ownership))
        work = asyncio.create_task(
            asyncio.to_thread(
                runtime.preview_service.execute,
                payload.to_domain(),
                ownership.cancel_event,
            )
        )
        prepared = await asyncio.shield(work)
        ownership.attach(prepared)
        if ownership.cancel_event.is_set():
            raise PreviewServiceError(
                "PREVIEW_CANCELLED", "The preview request was cancelled."
            )
        ownership.finish_execution()
        boundary = f"wrld-preview-{secrets.token_hex(16)}"
        stream = _multipart_stream(ownership, watcher, boundary)
        response = StreamingResponse(
            stream,
            status_code=200,
            media_type=f'multipart/related; boundary="{boundary}"; type="application/json"',
        )
        transferred = True
        return response
    except PreviewServiceError as error:
        ownership.finish_execution()
        return preview_error_response(error.code, error.message)
    except PreviewContractError:
        ownership.finish_execution()
        return preview_error_response(
            "PREVIEW_INVALID_REQUEST", "The preview request is invalid."
        )
    except asyncio.CancelledError:
        ownership.cancel_event.set()
        if work is not None:
            await _discard_cancelled_work_result(work)
        ownership.finish_execution()
        raise
    except Exception:
        ownership.finish_execution()
        LOGGER.exception("Unexpected preview HTTP adapter failure")
        return preview_error_response(
            "PREVIEW_INTERNAL_ERROR", "The preview request could not be completed."
        )
    finally:
        if not transferred:
            try:
                await _stop_disconnect_watcher(watcher)
            finally:
                ownership.close()


async def _watch_disconnect(request: Request, ownership: object) -> None:
    cancel_event = ownership.cancel_event
    try:
        while not cancel_event.is_set():
            if await request.is_disconnected():
                cancel_event.set()
                return
            await asyncio.sleep(0.05)
    except asyncio.CancelledError:
        raise
    except Exception:
        cancel_event.set()
        raise


async def _discard_cancelled_work_result(
    work: asyncio.Task[PreparedPreview],
) -> None:
    """Wait through repeated cancellation and close any undeliverable result."""
    while not work.done():
        try:
            await asyncio.shield(work)
        except asyncio.CancelledError:
            continue
        except Exception:
            return
    try:
        prepared = work.result()
    except (Exception, asyncio.CancelledError):
        return
    try:
        prepared.close()
    except Exception:
        LOGGER.exception("Prepared preview cleanup failed after HTTP cancellation")


async def _stop_disconnect_watcher(watcher: asyncio.Task[None] | None) -> None:
    if watcher is None:
        return
    watcher.cancel()
    try:
        await watcher
    except asyncio.CancelledError:
        pass
    except Exception:
        LOGGER.exception("Preview disconnect watcher failed")


async def _multipart_stream(
    ownership: object,
    watcher: asyncio.Task[None],
    boundary: str,
) -> AsyncIterator[bytes]:
    try:
        result_json = json.dumps(
            ownership.result.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        yield (
            f"--{boundary}\r\n"
            "Content-Type: application/json\r\n"
            "Content-ID: <preview-result>\r\n\r\n"
        ).encode("ascii")
        yield result_json
        yield (
            f"\r\n--{boundary}\r\n"
            "Content-Type: image/png\r\n"
            "Content-ID: <preview-artifact>\r\n\r\n"
        ).encode("ascii")
        while not ownership.cancel_event.is_set():
            chunk = await asyncio.to_thread(ownership.read, MULTIPART_CHUNK_BYTES)
            if not chunk:
                break
            yield chunk
        if not ownership.cancel_event.is_set():
            yield f"\r\n--{boundary}--\r\n".encode("ascii")
    finally:
        try:
            await _stop_disconnect_watcher(watcher)
        finally:
            ownership.close()


def preview_error_response(code: str, message: str) -> JSONResponse:
    status = PREVIEW_HTTP_STATUS.get(code, 500)
    safe_code = code if code in PREVIEW_HTTP_STATUS else "PREVIEW_INTERNAL_ERROR"
    safe_message = (
        message
        if code in PREVIEW_HTTP_STATUS
        else "The preview request could not be completed."
    )
    correlation_id = f"preview-{secrets.token_hex(16)}"
    error = PreviewError.create(
        code=safe_code,
        message=safe_message,
        correlation_id=correlation_id,
        details={},
    )
    return JSONResponse(status_code=status, content=error.to_dict())
