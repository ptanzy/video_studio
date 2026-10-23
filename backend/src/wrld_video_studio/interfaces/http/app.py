from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError

from wrld_video_studio.application.media_jobs import RenderWorker
from wrld_video_studio.application.preview_resolution import ResolvedPreviewService
from wrld_video_studio.application.preview_service import (
    AuthoritativePreviewService,
    PreparedPreview,
    PreviewServiceError,
)
from wrld_video_studio.application.render_coordination import (
    PreviewSingleFlightCoordinator,
    ProcessLocalRenderAdmission,
)
from wrld_video_studio.domain.preview_cache import (
    DEFAULT_PREVIEW_CACHE_MAX_BYTES,
    DEFAULT_PREVIEW_CACHE_MAX_ENTRIES,
    DEFAULT_PREVIEW_MAX_WAITING_REQUESTS,
)
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.infrastructure.artwork_sources import (
    ArtworkSourceRegistration,
    ImmutableArtworkRegistry,
    SecureFilesystemArtworkSourceResolver,
    TrustedArtworkRoot,
)
from wrld_video_studio.infrastructure.media_tools import MediaTool
from wrld_video_studio.infrastructure.preview_cache import SecureFilesystemPreviewCache
from wrld_video_studio.infrastructure.preview_context import (
    ImmutablePreviewContextRegistry,
    PreviewContextRegistration,
)
from wrld_video_studio.infrastructure.preview_toolchain import VerifiedFFmpegPreviewBackend
from wrld_video_studio.infrastructure.process_runner import SubprocessRunner
from wrld_video_studio.interfaces.http.preview import preview_error_response, router


LOGGER = logging.getLogger(__name__)
DEFAULT_BIND_HOST = "127.0.0.1"


@dataclass(frozen=True, slots=True)
class PreviewApplicationConfig:
    artwork_roots: tuple[TrustedArtworkRoot, ...]
    artwork_registrations: tuple[ArtworkSourceRegistration, ...]
    context_registrations: tuple[PreviewContextRegistration, ...]
    snapshot_root: Path
    cache_root: Path
    ffmpeg_path: Path
    ffprobe_path: Path
    preview_wait_timeout_seconds: float
    preview_render_timeout_seconds: float
    shutdown_timeout_seconds: float
    cache_max_bytes: int = DEFAULT_PREVIEW_CACHE_MAX_BYTES
    cache_max_entries: int = DEFAULT_PREVIEW_CACHE_MAX_ENTRIES
    max_waiting_preview_callers: int = DEFAULT_PREVIEW_MAX_WAITING_REQUESTS

    def __post_init__(self) -> None:
        if any(
            type(value) is not tuple
            for value in (
                self.artwork_roots,
                self.artwork_registrations,
                self.context_registrations,
            )
        ):
            raise ValueError("Trusted preview registrations must be immutable tuples.")
        for name in (
            "preview_wait_timeout_seconds",
            "preview_render_timeout_seconds",
            "shutdown_timeout_seconds",
        ):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite number.")
        for name in ("snapshot_root", "cache_root", "ffmpeg_path", "ffprobe_path"):
            value = getattr(self, name)
            if not isinstance(value, Path) or not value.is_absolute():
                raise ValueError(f"{name} must be an absolute Path.")
        if not self.artwork_roots or not self.artwork_registrations:
            raise ValueError("Trusted artwork roots and registrations are required.")
        if not all(isinstance(value, TrustedArtworkRoot) for value in self.artwork_roots):
            raise ValueError("Trusted artwork roots are invalid.")
        if not all(
            isinstance(value, ArtworkSourceRegistration)
            for value in self.artwork_registrations
        ):
            raise ValueError("Trusted artwork registrations are invalid.")
        if not all(
            isinstance(value, PreviewContextRegistration)
            for value in self.context_registrations
        ):
            raise ValueError("Trusted preview context registrations are invalid.")
        artwork_targets = {
            (registration.album_id, registration.artwork_asset_id)
            for registration in self.artwork_registrations
        }
        context_targets = {
            (registration.album_id, registration.artwork_asset_id)
            for registration in self.context_registrations
        }
        album_context_targets = {
            (registration.album_id, registration.artwork_asset_id)
            for registration in self.context_registrations
            if registration.track_id is None and registration.short_id is None
        }
        if not context_targets <= artwork_targets or album_context_targets != artwork_targets:
            raise ValueError(
                "Every artwork registration requires exactly one album-level Auto-color context."
            )


class _ConfiguredMediaToolchain:
    def __init__(
        self,
        runner: SubprocessRunner,
        *,
        ffmpeg_path: Path,
        ffprobe_path: Path,
    ) -> None:
        self._runner = runner
        self._paths = {"ffmpeg": ffmpeg_path, "ffprobe": ffprobe_path}

    def resolve(self, name: str) -> MediaTool:
        if name not in self._paths:
            raise ValueError("Only ffmpeg and ffprobe are supported media tools")
        path = self._paths[name]
        if not path.is_absolute() or not path.is_file():
            raise MediaInfrastructureError(
                "MEDIA_TOOL_MISSING", "The configured preview media tool is unavailable."
            )
        result = self._runner.run([str(path), "-version"], timeout_seconds=5.0)
        if result.returncode != 0 or not result.stdout.strip():
            raise MediaInfrastructureError(
                "MEDIA_TOOL_INVALID", "The configured preview media tool is invalid."
            )
        return MediaTool(path.resolve(strict=True), result.stdout.splitlines()[0].strip())


class _HTTPRequestOwnership:
    def __init__(self, runtime: PreviewApplicationRuntime) -> None:
        self._runtime = runtime
        self.cancel_event = threading.Event()
        self._guard = threading.RLock()
        self._prepared: PreparedPreview | None = None
        self._execution_active = True
        self._closed = False

    @property
    def execution_active(self) -> bool:
        with self._guard:
            return self._execution_active

    @property
    def result(self):
        with self._guard:
            if self._prepared is None or self._closed:
                raise PreviewServiceError(
                    "PREVIEW_INTERNAL_ERROR", "The preview response is unavailable."
                )
            return self._prepared.result

    def attach(self, prepared: PreparedPreview) -> None:
        if not isinstance(prepared, PreparedPreview):
            raise TypeError("A prepared preview is required.")
        with self._runtime._condition:
            with self._guard:
                if self._closed or not self._runtime._accepting:
                    prepared.close()
                    raise PreviewServiceError(
                        "PREVIEW_CANCELLED", "The preview request was cancelled."
                    )
                if self._prepared is not None:
                    prepared.close()
                    raise PreviewServiceError(
                        "PREVIEW_INTERNAL_ERROR", "Preview response ownership was duplicated."
                    )
                self._prepared = prepared

    def finish_execution(self) -> None:
        with self._runtime._condition:
            with self._guard:
                self._execution_active = False
            self._runtime._condition.notify_all()

    def read(self, amount: int) -> bytes:
        if type(amount) is not int or amount < 1:
            raise ValueError("Multipart reads require a positive bounded size.")
        with self._guard:
            if self._prepared is None or self._closed:
                return b""
            return self._prepared.artifact.read(amount)

    def close(self) -> None:
        with self._guard:
            if self._closed:
                return
            self._closed = True
            prepared = self._prepared
            self._prepared = None
        try:
            if prepared is not None:
                prepared.close()
        finally:
            self._runtime._release_request(self)


class PreviewApplicationRuntime:
    """Own all process-local WU3 resources and the shared WU2/WU3 admission."""

    def __init__(self, config: PreviewApplicationConfig) -> None:
        if not isinstance(config, PreviewApplicationConfig):
            raise TypeError("Trusted preview application configuration is required.")
        self.config = config
        self.render_admission = ProcessLocalRenderAdmission()
        self._condition = threading.Condition()
        self._requests: set[_HTTPRequestOwnership] = set()
        self._accepting = False
        self._closed = False
        self.cache: SecureFilesystemPreviewCache | None = None
        self.coordinator: PreviewSingleFlightCoordinator | None = None
        try:
            registry = ImmutableArtworkRegistry(
                config.artwork_roots, config.artwork_registrations
            )
            self.source_resolver = SecureFilesystemArtworkSourceResolver(
                registry, config.snapshot_root
            )
            for registration in config.artwork_registrations:
                with self.source_resolver.acquire(
                    registration.album_id, registration.artwork_asset_id
                ) as source:
                    source.verify_snapshot()
                    source.revalidate_source()
            self.cache = SecureFilesystemPreviewCache(
                config.cache_root,
                max_bytes=config.cache_max_bytes,
                max_entries=config.cache_max_entries,
            )
            self.context_provider = ImmutablePreviewContextRegistry(
                config.context_registrations
            )
            runner = SubprocessRunner()
            toolchain = _ConfiguredMediaToolchain(
                runner,
                ffmpeg_path=config.ffmpeg_path,
                ffprobe_path=config.ffprobe_path,
            )
            self.render_backend = VerifiedFFmpegPreviewBackend(
                toolchain,
                runner,
                render_timeout_seconds=config.preview_render_timeout_seconds,
            )
            self.render_backend.identify()
            self.coordinator = PreviewSingleFlightCoordinator(
                self.render_admission,
                wait_timeout_seconds=config.preview_wait_timeout_seconds,
                max_waiting_callers=config.max_waiting_preview_callers,
            )
            authoritative = AuthoritativePreviewService(
                source_resolver=self.source_resolver,
                cache_store=self.cache,
                flight_coordinator=self.coordinator,
                render_backend=self.render_backend,
            )
            self.preview_service = ResolvedPreviewService(
                context_provider=self.context_provider,
                preview_service=authoritative,
            )
            self._accepting = True
        except BaseException:
            self._release_partial_startup()
            raise

    def begin_request(self) -> _HTTPRequestOwnership:
        with self._condition:
            if not self._accepting or self._closed:
                raise PreviewServiceError(
                    "PREVIEW_CANCELLED", "Preview processing is shutting down."
                )
            ownership = _HTTPRequestOwnership(self)
            self._requests.add(ownership)
            return ownership

    def build_render_worker(self, *args: Any, **kwargs: Any) -> RenderWorker:
        if "admission" in kwargs:
            raise TypeError("WU2 admission is owned by the application runtime.")
        return RenderWorker(*args, admission=self.render_admission, **kwargs)

    def close(self) -> None:
        deadline = time.monotonic() + float(self.config.shutdown_timeout_seconds)
        with self._condition:
            if self._closed:
                return
            self._accepting = False
            requests = tuple(self._requests)
            for ownership in requests:
                ownership.cancel_event.set()

        coordinator = self.coordinator
        if coordinator is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PreviewServiceError(
                    "PREVIEW_TIMEOUT", "Preview shutdown timed out."
                )
            coordinator.close(timeout_seconds=remaining)

        with self._condition:
            while any(item.execution_active for item in self._requests):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PreviewServiceError(
                        "PREVIEW_TIMEOUT", "Preview shutdown timed out."
                    )
                self._condition.wait(timeout=remaining)
            requests = tuple(self._requests)

        cleanup_failure: Exception | None = None
        for ownership in requests:
            try:
                ownership.close()
            except Exception as error:
                if cleanup_failure is None:
                    cleanup_failure = error

        if self.cache is not None:
            try:
                self.cache.close()
            except Exception as error:
                if cleanup_failure is None:
                    cleanup_failure = error
        if cleanup_failure is not None:
            failure = PreviewServiceError(
                "PREVIEW_INTERNAL_ERROR", "Preview shutdown cleanup failed."
            )
            failure.__cause__ = cleanup_failure
            raise failure
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def _release_request(self, ownership: _HTTPRequestOwnership) -> None:
        with self._condition:
            self._requests.discard(ownership)
            self._condition.notify_all()

    def _release_partial_startup(self) -> None:
        if self.coordinator is not None:
            try:
                self.coordinator.close(timeout_seconds=float(self.config.shutdown_timeout_seconds))
            except BaseException:
                LOGGER.exception("Preview coordinator cleanup failed during startup rollback")
        if self.cache is not None:
            try:
                self.cache.close()
            except BaseException:
                LOGGER.exception("Preview cache cleanup failed during startup rollback")


def create_app(
    config: PreviewApplicationConfig,
    *,
    runtime_factory: Callable[[PreviewApplicationConfig], PreviewApplicationRuntime] = PreviewApplicationRuntime,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        initialization = asyncio.create_task(asyncio.to_thread(runtime_factory, config))
        try:
            runtime = await asyncio.shield(initialization)
        except asyncio.CancelledError as cancellation:
            await _reconcile_cancelled_initialization(initialization, cancellation)
            raise AssertionError("Cancelled preview initialization unexpectedly returned.")
        try:
            app.state.preview_runtime = runtime
            yield
        finally:
            await _close_runtime_owned(runtime)

    app = FastAPI(
        title="WRLD Video Studio",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(router)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        _request: Request, _error: RequestValidationError
    ):
        return preview_error_response(
            "PREVIEW_INVALID_REQUEST", "The preview request is invalid."
        )

    @app.exception_handler(PreviewServiceError)
    async def preview_service_error(_request: Request, error: PreviewServiceError):
        return preview_error_response(error.code, error.message)

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, _error: Exception):
        LOGGER.error(
            "Unexpected HTTP application failure",
            exc_info=(type(_error), _error, _error.__traceback__),
        )
        return preview_error_response(
            "PREVIEW_INTERNAL_ERROR", "The preview request could not be completed."
        )

    return app


async def _wait_for_owned_task(
    task: asyncio.Task[Any],
) -> asyncio.CancelledError | None:
    """Wait for owned thread work without allowing repeated cancellation to detach it."""
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            if cancellation is None:
                cancellation = error
        except BaseException:
            break
    return cancellation


async def _close_runtime_owned(runtime: PreviewApplicationRuntime) -> None:
    closure = asyncio.create_task(asyncio.to_thread(runtime.close))
    cancellation = await _wait_for_owned_task(closure)
    result = closure.result()
    if cancellation is not None:
        raise cancellation
    return result


async def _reconcile_cancelled_initialization(
    initialization: asyncio.Task[PreviewApplicationRuntime],
    cancellation: asyncio.CancelledError,
) -> None:
    await _wait_for_owned_task(initialization)
    try:
        runtime = initialization.result()
    except (Exception, asyncio.CancelledError):
        raise cancellation
    try:
        await _close_runtime_owned(runtime)
    except asyncio.CancelledError:
        raise cancellation
    except BaseException as error:
        failure = RuntimeError(
            "Preview runtime ownership could not be released after cancelled startup."
        )
        failure.__cause__ = error
        raise failure
    raise cancellation


def serve(config: PreviewApplicationConfig, *, port: int) -> None:
    """Run the approved local adapter on loopback only."""
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("The local HTTP port must be an integer in [1, 65535].")
    import uvicorn

    uvicorn.run(create_app(config), host=DEFAULT_BIND_HOST, port=port)
