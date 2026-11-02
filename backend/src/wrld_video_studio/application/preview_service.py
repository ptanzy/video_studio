from __future__ import annotations

import math
import re
import threading
from pathlib import Path
from typing import Any

from wrld_video_studio.application.ports.artwork_sources import (
    ArtworkSourceError,
    ArtworkSourceLease,
    ArtworkSourceResolver,
)
from wrld_video_studio.application.ports.preview_cache import (
    PreviewArtifactLease,
    PreviewCacheError,
    PreviewCacheStagingLease,
    PreviewCacheStore,
)
from wrld_video_studio.application.ports.render_coordination import (
    PreviewCoordinationError,
    PreviewFlightCoordinator,
    PreviewFlightOperation,
)
from wrld_video_studio.application.ports.still_images import (
    STILL_RENDER_RESULT_VERSION,
    PreviewRenderBackend,
    PreviewRenderError,
    StillRenderResult,
)
from wrld_video_studio.domain.color_resolution import (
    INPUT_CONTRACT_VERSION,
    ColorResolution,
    resolve_color_treatment,
)
from wrld_video_studio.domain.preview_cache import (
    PREVIEW_ERROR_CODES,
    PreviewCacheIdentity,
    PreviewContractError,
    PreviewRequest,
    PreviewResult,
    PreviewToolchainIdentity,
    build_preview_cache_identity,
    validate_color_resolution,
)


class PreviewServiceError(RuntimeError):
    """Path-safe failure from the authoritative preview application service."""

    def __init__(self, code: str, message: str) -> None:
        if code not in PREVIEW_ERROR_CODES:
            raise ValueError("Preview service errors must use an approved preview error code.")
        self.code = code
        self.message = message
        super().__init__(message)


class PreparedPreview:
    """Trusted result paired with one caller-owned pinned artifact lease."""

    def __init__(self, result: PreviewResult, artifact: PreviewArtifactLease) -> None:
        if not isinstance(result, PreviewResult):
            raise TypeError("A trusted PreviewResult is required.")
        self._result = result
        self._artifact: PreviewArtifactLease | None = artifact
        self._guard = threading.Lock()

    @property
    def result(self) -> PreviewResult:
        return self._result

    @property
    def artifact(self) -> PreviewArtifactLease:
        with self._guard:
            if self._artifact is None:
                raise PreviewServiceError(
                    "PREVIEW_INTERNAL_ERROR", "The prepared preview is closed."
                )
            return self._artifact

    def close(self) -> None:
        with self._guard:
            artifact = self._artifact
            self._artifact = None
        if artifact is not None:
            artifact.close()

    def __enter__(self) -> PreparedPreview:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class AuthoritativePreviewService:
    """Resolve, identify, coordinate, render, and pin authoritative previews."""

    def __init__(
        self,
        *,
        source_resolver: ArtworkSourceResolver,
        cache_store: PreviewCacheStore,
        flight_coordinator: PreviewFlightCoordinator,
        render_backend: PreviewRenderBackend,
    ) -> None:
        self._source_resolver = source_resolver
        self._cache_store = cache_store
        self._flight_coordinator = flight_coordinator
        self._render_backend = render_backend

    def execute(
        self,
        request: PreviewRequest,
        resolution: ColorResolution,
        cancel_event: Any = None,
    ) -> PreparedPreview:
        try:
            validated_resolution = _validate_request_resolution(request, resolution)
        except PreviewContractError as error:
            failure = PreviewServiceError(
                "PREVIEW_INVALID_REQUEST", "The preview request is invalid."
            )
            failure.__cause__ = error
            raise failure

        artifact: PreviewArtifactLease | None = None
        source: ArtworkSourceLease | None = None
        try:
            _raise_cancelled(cancel_event)
            source = self._source_resolver.acquire(
                request.target.album_id,
                request.target.artwork_asset_id,
                cancel_event=cancel_event,
            )
            source.verify_snapshot(cancel_event)
            source.revalidate_source(cancel_event)
            toolchain = self._render_backend.identify(cancel_event)
            identity = build_preview_cache_identity(
                source_sha256=source.snapshot.source_sha256,
                resolution=validated_resolution,
                toolchain=toolchain,
            )

            recovery_used = False
            try:
                artifact = self._cache_store.lookup(identity, cancel_event)
            except PreviewCacheError as error:
                if error.code != "PREVIEW_CACHE_CORRUPT":
                    raise
                self._discard_corrupt(identity)
                recovery_used = True

            if artifact is not None:
                source.verify_snapshot(cancel_event)
                source.revalidate_source(cancel_event)
                _require_toolchain(
                    self._render_backend.identify(cancel_event), identity.descriptor.toolchain
                )
                result = _result(identity, artifact, "hit")
                source.close()
                source = None
                prepared = PreparedPreview(result, artifact)
                artifact = None
                return prepared

            source.close()
            source = None
            while True:
                operation = _PreviewRenderOperation(
                    source_resolver=self._source_resolver,
                    cache_store=self._cache_store,
                    render_backend=self._render_backend,
                    identity=identity,
                    request=request,
                )
                try:
                    self._flight_coordinator.coordinate(
                        identity, operation, cancel_event=cancel_event
                    )
                except PreviewCoordinationError as error:
                    if error.code == "PREVIEW_CACHE_CORRUPT" and not recovery_used:
                        self._discard_corrupt(identity)
                        recovery_used = True
                        continue
                    raise

                source = self._source_resolver.acquire(
                    request.target.album_id,
                    request.target.artwork_asset_id,
                    cancel_event=cancel_event,
                )
                source.verify_snapshot(cancel_event)
                _require_source_digest(source, identity)
                source.revalidate_source(cancel_event)
                _require_toolchain(
                    self._render_backend.identify(cancel_event), identity.descriptor.toolchain
                )
                try:
                    artifact = self._cache_store.lookup(identity, cancel_event)
                except PreviewCacheError as error:
                    if error.code != "PREVIEW_CACHE_CORRUPT" or recovery_used:
                        raise
                    source.close()
                    source = None
                    self._discard_corrupt(identity)
                    recovery_used = True
                    continue
                if artifact is None:
                    raise PreviewServiceError(
                        "PREVIEW_INTERNAL_ERROR",
                        "The completed preview artifact is unavailable.",
                    )
                source.verify_snapshot(cancel_event)
                _require_source_digest(source, identity)
                source.revalidate_source(cancel_event)
                _require_toolchain(
                    self._render_backend.identify(cancel_event), identity.descriptor.toolchain
                )
                result = _result(identity, artifact, "miss")
                source.close()
                source = None
                prepared = PreparedPreview(result, artifact)
                artifact = None
                return prepared
        except PreviewServiceError:
            raise
        except (
            ArtworkSourceError,
            PreviewCacheError,
            PreviewCoordinationError,
            PreviewRenderError,
        ) as error:
            failure = PreviewServiceError(error.code, error.message)
            failure.__cause__ = error
            raise failure
        except PreviewContractError as error:
            failure = PreviewServiceError(
                "PREVIEW_INTERNAL_ERROR", "Preview processing violated a trusted contract."
            )
            failure.__cause__ = error
            raise failure
        except Exception as error:
            failure = PreviewServiceError(
                "PREVIEW_INTERNAL_ERROR", "The preview could not be prepared safely."
            )
            failure.__cause__ = error
            raise failure
        finally:
            if source is not None:
                try:
                    source.close()
                except Exception as error:
                    if artifact is not None:
                        artifact.close()
                        artifact = None
                    failure = PreviewServiceError(
                        "PREVIEW_INTERNAL_ERROR", "Preview source cleanup failed."
                    )
                    failure.__cause__ = error
                    raise failure
            if artifact is not None:
                try:
                    artifact.close()
                except Exception as error:
                    failure = PreviewServiceError(
                        "PREVIEW_INTERNAL_ERROR", "Preview artifact cleanup failed."
                    )
                    failure.__cause__ = error
                    raise failure

    def _discard_corrupt(self, identity: PreviewCacheIdentity) -> None:
        try:
            self._cache_store.discard_corrupt(identity)
        except PreviewCacheError:
            raise
        except Exception as error:
            failure = PreviewCacheError(
                "PREVIEW_INTERNAL_ERROR", "The corrupt preview entry could not be invalidated."
            )
            failure.__cause__ = error
            raise failure


class _PreviewRenderOperation(PreviewFlightOperation):
    """Lightweight until adopted; then owns all render-time leases."""

    def __init__(
        self,
        *,
        source_resolver: ArtworkSourceResolver,
        cache_store: PreviewCacheStore,
        render_backend: PreviewRenderBackend,
        identity: PreviewCacheIdentity,
        request: PreviewRequest,
    ) -> None:
        self._source_resolver = source_resolver
        self._cache_store = cache_store
        self._render_backend = render_backend
        self._identity = identity
        self._request = request
        self._source: ArtworkSourceLease | None = None
        self._staging: PreviewCacheStagingLease | None = None
        self._closed = False
        self._guard = threading.Lock()

    def run(self, cancel_event: Any = None) -> None:
        try:
            self._run(cancel_event)
        except PreviewCoordinationError:
            raise
        except (
            ArtworkSourceError,
            PreviewCacheError,
            PreviewRenderError,
        ) as error:
            failure = PreviewCoordinationError(error.code, error.message)
            failure.__cause__ = error
            raise failure
        except PreviewContractError as error:
            failure = PreviewCoordinationError(
                "PREVIEW_INTERNAL_ERROR", "Preview rendering violated a trusted contract."
            )
            failure.__cause__ = error
            raise failure

    def _run(self, cancel_event: Any) -> None:
        _raise_cancelled(cancel_event)
        _require_toolchain(
            self._render_backend.identify(cancel_event), self._identity.descriptor.toolchain
        )
        cached = self._cache_store.lookup(self._identity, cancel_event)
        if cached is not None:
            cached.close()
            return

        self._source = self._source_resolver.acquire(
            self._request.target.album_id,
            self._request.target.artwork_asset_id,
            cancel_event=cancel_event,
        )
        self._source.verify_snapshot(cancel_event)
        if self._source.snapshot.source_sha256 != self._identity.descriptor.source_sha256:
            raise PreviewCoordinationError(
                "SOURCE_CHANGED", "The registered artwork source changed during preview rendering."
            )
        self._source.revalidate_source(cancel_event)
        self._staging = self._cache_store.begin_write(self._identity)
        output_path = self._staging.output_path
        rendered = self._render_backend.render(
            source_path=self._source.snapshot.snapshot_path,
            output_path=output_path,
            resolution=self._identity.resolution,
            expected_toolchain=self._identity.descriptor.toolchain,
            cancel_event=cancel_event,
        )
        _validate_rendered(rendered, output_path, self._identity)
        self._source.verify_snapshot(cancel_event)
        self._source.revalidate_source(cancel_event)
        _require_toolchain(
            self._render_backend.identify(cancel_event), self._identity.descriptor.toolchain
        )
        _raise_cancelled(cancel_event)
        published = self._staging.publish(
            width=rendered.width,
            height=rendered.height,
            cancel_event=cancel_event,
        )
        self._staging = None
        published.close()

    def close(self) -> None:
        with self._guard:
            if self._closed:
                return
            self._closed = True
            staging = self._staging
            source = self._source
            self._staging = None
            self._source = None
        failure: BaseException | None = None
        if staging is not None:
            try:
                staging.close()
            except BaseException as error:
                failure = error
        if source is not None:
            try:
                source.close()
            except BaseException as error:
                if failure is None:
                    failure = error
        if failure is not None:
            raise failure


def _validate_request_resolution(
    request: PreviewRequest, resolution: ColorResolution
) -> ColorResolution:
    if not isinstance(request, PreviewRequest):
        raise PreviewContractError(
            "PREVIEW_INVALID_REQUEST", "A validated preview request is required."
        )
    validated = validate_color_resolution(resolution)
    selection = request.treatment
    if validated.mode != selection.mode:
        raise PreviewContractError(
            "PREVIEW_INVALID_REQUEST", "Resolved treatment does not match the preview request."
        )
    if selection.mode in {"custom", "preset"}:
        expected = resolve_color_treatment(
            {
                "contract_version": INPUT_CONTRACT_VERSION,
                "treatment": selection.to_dict(),
            }
        )
        if validated != expected:
            raise PreviewContractError(
                "PREVIEW_INVALID_REQUEST", "Resolved treatment does not match the preview request."
            )
    elif validated.resolved_hex is not None and validated.intensity != selection.intensity:
        raise PreviewContractError(
            "PREVIEW_INVALID_REQUEST", "Resolved treatment intensity does not match the preview request."
        )
    return validated


def _result(
    identity: PreviewCacheIdentity,
    artifact: PreviewArtifactLease,
    cache_status: str,
) -> PreviewResult:
    metadata = artifact.artifact
    if metadata.preview_id != identity.preview_id or metadata.media_type != "image/png":
        raise PreviewServiceError(
            "PREVIEW_INTERNAL_ERROR", "The cached preview metadata is inconsistent."
        )
    return PreviewResult.create(
        identity=identity,
        cache_status=cache_status,
        width=metadata.width,
        height=metadata.height,
        artifact_sha256=metadata.artifact_sha256,
    )


def _require_toolchain(
    actual: PreviewToolchainIdentity, expected: PreviewToolchainIdentity
) -> None:
    if not isinstance(actual, PreviewToolchainIdentity) or actual != expected:
        raise PreviewRenderError(
            "PREVIEW_INTERNAL_ERROR", "The preview rendering toolchain changed."
        )


def _require_source_digest(
    source: ArtworkSourceLease, identity: PreviewCacheIdentity
) -> None:
    actual = source.snapshot.source_sha256
    if type(actual) is not str or re.fullmatch(r"[a-f0-9]{64}", actual) is None:
        raise PreviewContractError(
            "PREVIEW_INTERNAL_ERROR", "Trusted preview source identity is invalid."
        )
    if actual != identity.descriptor.source_sha256:
        raise ArtworkSourceError(
            "SOURCE_CHANGED", "The registered artwork source changed during preview preparation."
        )


def _validate_rendered(
    result: StillRenderResult,
    expected_output: Path,
    identity: PreviewCacheIdentity,
) -> None:
    policy = identity.descriptor.render_policy
    valid = (
        isinstance(result, StillRenderResult)
        and result.contract_version == STILL_RENDER_RESULT_VERSION
        and result.artifact_path.resolve(strict=False) == expected_output.resolve(strict=False)
        and result.source_sha256 == identity.descriptor.source_sha256
        and result.treatment == identity.resolution
        and result.output_format == policy.output_format
        and result.output_pixel_format == policy.output_pixel_format
        and result.renderer_version == policy.renderer_version
        and result.transform_version == policy.transform_version
        and type(result.width) is int
        and type(result.height) is int
        and 1 <= result.width <= policy.max_longest_side
        and 1 <= result.height <= policy.max_longest_side
        and math.isfinite(float(result.width))
        and math.isfinite(float(result.height))
    )
    if not valid:
        raise PreviewCoordinationError(
            "PREVIEW_INTERNAL_ERROR", "Preview rendering produced inconsistent metadata."
        )


def _raise_cancelled(cancel_event: Any) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise PreviewCoordinationError("PREVIEW_CANCELLED", "Preview request was cancelled.")
