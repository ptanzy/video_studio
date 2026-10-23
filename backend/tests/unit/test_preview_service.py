from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from wrld_video_studio.application.ports.artwork_sources import (
    ArtworkSourceError,
    ArtworkSourceSnapshot,
)
from wrld_video_studio.application.ports.preview_cache import (
    CachedPreviewArtifact,
    PreviewCacheError,
)
from wrld_video_studio.application.ports.still_images import (
    STILL_RENDER_RESULT_VERSION,
    STILL_RENDERER_VERSION,
    PreviewRenderError,
    StillRenderResult,
)
from wrld_video_studio.application.preview_service import (
    AuthoritativePreviewService,
    PreviewServiceError,
)
from wrld_video_studio.application import preview_service as preview_service_module
from wrld_video_studio.application.render_coordination import (
    PreviewSingleFlightCoordinator,
    ProcessLocalRenderAdmission,
)
from wrld_video_studio.domain.color_resolution import (
    INPUT_CONTRACT_VERSION,
    resolve_color_treatment,
)
from wrld_video_studio.domain.color_transform import TRANSFORM_VERSION
from wrld_video_studio.domain.preview_cache import (
    PREVIEW_REQUEST_VERSION,
    PREVIEW_VARIANT,
    PreviewContractError,
    PreviewRequest,
    PreviewTarget,
    PreviewToolchainIdentity,
    PreviewTreatmentSelection,
)
from wrld_video_studio.infrastructure.media_tools import MediaTool
from wrld_video_studio.infrastructure import preview_toolchain as preview_toolchain_module
from wrld_video_studio.infrastructure.preview_toolchain import VerifiedFFmpegPreviewBackend
from wrld_video_studio.infrastructure.preview_cache import SecureFilesystemPreviewCache
from wrld_video_studio.infrastructure.still_image_renderer import (
    REQUIRED_FFMPEG_ENCODERS,
    REQUIRED_FFMPEG_FILTERS,
)


SOURCE_DIGEST = hashlib.sha256(b"source").hexdigest()
TOOLCHAIN = PreviewToolchainIdentity.create(
    ffmpeg_sha256="b" * 64,
    ffprobe_sha256="c" * 64,
)


def _request(
    *,
    mode="custom",
    value="#123456",
    intensity=0.3,
    album_id="Album",
    artwork_asset_id="cover",
):
    treatment = (
        PreviewTreatmentSelection(mode="preset", preset=value, intensity=intensity)
        if mode == "preset"
        else PreviewTreatmentSelection(mode=mode, hex=value if mode == "custom" else None, intensity=intensity)
    )
    return PreviewRequest(
        contract_version=PREVIEW_REQUEST_VERSION,
        target=PreviewTarget(album_id, artwork_asset_id),
        treatment=treatment,
        variant=PREVIEW_VARIANT,
    )


def _resolution(*, mode="custom", value="#123456", intensity=0.3, context=None):
    treatment = {"mode": mode, "intensity": intensity}
    if mode == "custom":
        treatment["hex"] = value
    elif mode == "preset":
        treatment["preset"] = value
    payload = {"contract_version": INPUT_CONTRACT_VERSION, "treatment": treatment}
    if context is not None:
        payload["context"] = context
    return resolve_color_treatment(payload)


class FakeSourceLease:
    def __init__(self, path: Path, digest=SOURCE_DIGEST):
        self._snapshot = ArtworkSourceSnapshot("Album", "cover", path, digest, 6)
        self.verify_count = 0
        self.revalidate_count = 0
        self.close_count = 0

    @property
    def snapshot(self):
        return self._snapshot

    def verify_snapshot(self, cancel_event=None):
        self.verify_count += 1

    def revalidate_source(self, cancel_event=None):
        self.revalidate_count += 1

    def close(self):
        self.close_count += 1


class FakeResolver:
    def __init__(self, path: Path, digests=None):
        self.path = path
        self.digests = list(digests or [SOURCE_DIGEST])
        self.leases = []

    def acquire(self, album_id, artwork_asset_id, cancel_event=None):
        digest = self.digests[min(len(self.leases), len(self.digests) - 1)]
        lease = FakeSourceLease(self.path, digest)
        self.leases.append(lease)
        return lease


class MutableTargetSourceLease:
    def __init__(self, resolver, album_id, artwork_asset_id, path, digest):
        self._resolver = resolver
        self._key = (album_id, artwork_asset_id)
        self._snapshot = ArtworkSourceSnapshot(
            album_id, artwork_asset_id, path, digest, 6
        )
        self.verify_count = 0
        self.revalidate_count = 0
        self.close_count = 0

    @property
    def snapshot(self):
        return self._snapshot

    def verify_snapshot(self, cancel_event=None):
        self.verify_count += 1

    def revalidate_source(self, cancel_event=None):
        self.revalidate_count += 1
        current = self._resolver.current(self._key)
        if current is None:
            raise ArtworkSourceError(
                "PREVIEW_SOURCE_UNAVAILABLE", "The registered artwork source is unavailable."
            )
        if current != self._snapshot.source_sha256:
            raise ArtworkSourceError(
                "SOURCE_CHANGED", "The registered artwork source changed."
            )

    def close(self):
        self.close_count += 1


class MutableTargetResolver:
    def __init__(self, path: Path, entries):
        self.path = path
        self._entries = dict(entries)
        self._guard = threading.Lock()
        self.leases = []

    def current(self, key):
        with self._guard:
            return self._entries.get(key)

    def set_digest(self, album_id, artwork_asset_id, digest):
        with self._guard:
            self._entries[(album_id, artwork_asset_id)] = digest

    def remove(self, album_id, artwork_asset_id):
        with self._guard:
            self._entries.pop((album_id, artwork_asset_id), None)

    def acquire(self, album_id, artwork_asset_id, cancel_event=None):
        key = (album_id, artwork_asset_id)
        digest = self.current(key)
        if digest is None:
            raise ArtworkSourceError(
                "PREVIEW_SOURCE_UNAVAILABLE", "The registered artwork source is unavailable."
            )
        lease = MutableTargetSourceLease(
            self, album_id, artwork_asset_id, self.path, digest
        )
        with self._guard:
            self.leases.append(lease)
        return lease


class FakeArtifactLease:
    def __init__(self, metadata):
        self._artifact = metadata
        self.close_count = 0

    @property
    def artifact(self):
        if self.close_count:
            raise RuntimeError("closed")
        return self._artifact

    def read(self, amount=-1):
        return b"png"

    def seek(self, offset, whence=0):
        return 0

    def close(self):
        self.close_count += 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


class FakeStaging:
    def __init__(self, cache, identity, path):
        self.cache = cache
        self.identity = identity
        self._path = path
        self.close_count = 0

    @property
    def output_path(self):
        return self._path

    def publish(self, *, width, height, cancel_event=None):
        metadata = CachedPreviewArtifact(
            self.identity.preview_id,
            "d" * 64,
            3,
            width,
            height,
        )
        if not self.cache.drop_publication:
            self.cache.entries[self.identity.preview_id] = metadata
        self.cache.publication_count += 1
        self.close_count += 1
        return FakeArtifactLease(metadata)

    def close(self):
        self.close_count += 1


class FakeCache:
    def __init__(self, root: Path):
        self.root = root
        self.entries = {}
        self.lookup_count = 0
        self.begin_count = 0
        self.publication_count = 0
        self.discard_count = 0
        self.corrupt_lookups = 0
        self.drop_publication = False
        self.leases = []
        self.stagings = []
        self._guard = threading.Lock()

    def lookup(self, identity, cancel_event=None):
        with self._guard:
            self.lookup_count += 1
            if self.corrupt_lookups:
                self.corrupt_lookups -= 1
                raise PreviewCacheError("PREVIEW_CACHE_CORRUPT", "Cached preview is corrupt.")
            metadata = self.entries.get(identity.preview_id)
            if metadata is None:
                return None
            lease = FakeArtifactLease(metadata)
            self.leases.append(lease)
            return lease

    def begin_write(self, identity):
        with self._guard:
            self.begin_count += 1
            directory = self.root / f"stage-{self.begin_count}"
            directory.mkdir()
            staging = FakeStaging(self, identity, directory / "artifact.png")
            self.stagings.append(staging)
            return staging

    def discard_corrupt(self, identity):
        self.discard_count += 1
        self.entries.pop(identity.preview_id, None)
        return True

    def enforce_limits(self):
        return None

    def close(self):
        return None


class FakeBackend:
    def __init__(self, toolchain=TOOLCHAIN):
        self.toolchain = toolchain
        self.identify_count = 0
        self.render_count = 0
        self.started = threading.Event()
        self.release = None
        self.failure = None

    def identify(self, cancel_event=None):
        self.identify_count += 1
        return self.toolchain

    def render(
        self, *, source_path, output_path, resolution, expected_toolchain, cancel_event=None
    ):
        self.render_count += 1
        self.started.set()
        if self.release is not None:
            assert self.release.wait(timeout=5)
        if self.failure is not None:
            raise self.failure
        output_path.write_bytes(b"png")
        return StillRenderResult(
            contract_version=STILL_RENDER_RESULT_VERSION,
            artifact_path=output_path,
            source_sha256=SOURCE_DIGEST,
            treatment=resolution,
            width=2,
            height=1,
            output_format="png",
            renderer_version=STILL_RENDERER_VERSION,
            transform_version=TRANSFORM_VERSION,
            ffmpeg_version="ffmpeg fixture",
            input_pixel_format="rgba",
            output_pixel_format="rgba",
            orientation="normalized",
            sanitized_command=("<tool:ffmpeg>",),
        )


class ImmediateCoordinator:
    def __init__(self):
        self.coordinate_count = 0
        self.operations = []

    def coordinate(self, identity, operation, cancel_event=None):
        self.coordinate_count += 1
        self.operations.append(operation)
        try:
            operation.run(cancel_event)
        finally:
            operation.close()


class AdmittedCachePublishingCoordinator:
    def __init__(self, cache, before_recheck):
        self.cache = cache
        self.before_recheck = before_recheck

    def coordinate(self, identity, operation, cancel_event=None):
        self.cache.entries[identity.preview_id] = CachedPreviewArtifact(
            identity.preview_id, "d" * 64, 3, 2, 1
        )
        self.before_recheck()
        try:
            operation.run(cancel_event)
        finally:
            operation.close()


def _wait_for_flight_callers(coordinator, expected):
    with coordinator._condition:
        joined = coordinator._condition.wait_for(
            lambda: bool(coordinator._flights)
            and len(next(iter(coordinator._flights.values())).callers) >= expected,
            timeout=5,
        )
    assert joined


def _service(tmp_path, *, cache=None, resolver=None, backend=None, coordinator=None):
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    return (
        AuthoritativePreviewService(
            source_resolver=resolver or FakeResolver(source),
            cache_store=cache or FakeCache(tmp_path),
            flight_coordinator=coordinator or ImmediateCoordinator(),
            render_backend=backend or FakeBackend(),
        ),
        source,
    )


def _seed(cache, service, request, resolution, tmp_path):
    resolver = service._source_resolver
    identity_tool = service._render_backend.toolchain
    from wrld_video_studio.domain.preview_cache import build_preview_cache_identity

    identity = build_preview_cache_identity(
        source_sha256=SOURCE_DIGEST,
        resolution=resolution,
        toolchain=identity_tool,
    )
    cache.entries[identity.preview_id] = CachedPreviewArtifact(
        identity.preview_id, "d" * 64, 3, 2, 1
    )
    return identity


def test_initial_hit_bypasses_coordination_and_owns_independent_pin(tmp_path):
    cache = FakeCache(tmp_path)
    coordinator = ImmediateCoordinator()
    backend = FakeBackend()
    service, _ = _service(tmp_path, cache=cache, backend=backend, coordinator=coordinator)
    request = _request()
    resolution = _resolution()
    _seed(cache, service, request, resolution, tmp_path)

    prepared = service.execute(request, resolution)

    assert prepared.result.cache_status == "hit"
    assert coordinator.coordinate_count == backend.render_count == 0
    lease = prepared.artifact
    prepared.close()
    prepared.close()
    assert lease.close_count == 1
    with pytest.raises(PreviewServiceError):
        prepared.artifact


def test_miss_renders_publishes_and_returns_fresh_pin(tmp_path):
    cache = FakeCache(tmp_path)
    coordinator = ImmediateCoordinator()
    backend = FakeBackend()
    service, _ = _service(tmp_path, cache=cache, backend=backend, coordinator=coordinator)

    prepared = service.execute(_request(), _resolution())

    assert prepared.result.cache_status == "miss"
    assert coordinator.coordinate_count == backend.render_count == cache.publication_count == 1
    assert len(cache.leases) == 1
    prepared.close()


def test_direct_request_resolution_mismatch_is_rejected_before_io(tmp_path):
    resolver = FakeResolver(tmp_path / "unused")
    service, _ = _service(tmp_path, resolver=resolver)
    with pytest.raises(PreviewServiceError) as caught:
        service.execute(_request(value="#123456"), _resolution(value="#654321"))
    assert caught.value.code == "PREVIEW_INVALID_REQUEST"
    assert resolver.leases == []


def test_malformed_trusted_source_digest_is_internal_and_closes_source(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    resolver = FakeResolver(source, ["not-a-sha256"])
    service, _ = _service(tmp_path, resolver=resolver)

    with pytest.raises(PreviewServiceError) as caught:
        service.execute(_request(), _resolution())

    assert caught.value.code == "PREVIEW_INTERNAL_ERROR"
    assert str(source) not in caught.value.message
    assert len(resolver.leases) == 1
    assert resolver.leases[0].close_count == 1


def test_invalid_trusted_cache_dimensions_are_internal_and_close_all_leases(tmp_path):
    cache = FakeCache(tmp_path)
    service, source = _service(tmp_path, cache=cache)
    identity = _seed(cache, service, _request(), _resolution(), tmp_path)
    cache.entries[identity.preview_id] = CachedPreviewArtifact(
        identity.preview_id, "d" * 64, 3, 0, 1
    )

    with pytest.raises(PreviewServiceError) as caught:
        service.execute(_request(), _resolution())

    assert caught.value.code == "PREVIEW_INTERNAL_ERROR"
    assert str(source) not in caught.value.message
    assert cache.leases[-1].close_count == 1
    assert service._source_resolver.leases[-1].close_count == 1


def test_trusted_result_construction_failure_is_internal_and_cleans_up(
    tmp_path, monkeypatch
):
    cache = FakeCache(tmp_path)
    service, source = _service(tmp_path, cache=cache)
    _seed(cache, service, _request(), _resolution(), tmp_path)

    def fail_result(*args, **kwargs):
        raise PreviewContractError(
            "PREVIEW_INVALID_REQUEST", "forged trusted result failure"
        )

    monkeypatch.setattr(preview_service_module.PreviewResult, "create", fail_result)
    with pytest.raises(PreviewServiceError) as caught:
        service.execute(_request(), _resolution())

    assert caught.value.code == "PREVIEW_INTERNAL_ERROR"
    assert "forged" not in caught.value.message
    assert str(source) not in caught.value.message
    assert cache.leases[-1].close_count == 1
    assert service._source_resolver.leases[-1].close_count == 1


def test_equivalent_pixel_provenance_shares_flight_but_results_remain_distinct(tmp_path):
    cache = FakeCache(tmp_path)
    backend = FakeBackend()
    backend.release = threading.Event()
    coordinator = PreviewSingleFlightCoordinator(
        ProcessLocalRenderAdmission(), wait_timeout_seconds=5
    )
    source = tmp_path / "source.png"
    resolver = MutableTargetResolver(
        source,
        {
            ("Album", "cover-a"): SOURCE_DIGEST,
            ("Album", "cover-b"): SOURCE_DIGEST,
        },
    )
    service, _ = _service(
        tmp_path,
        cache=cache,
        resolver=resolver,
        backend=backend,
        coordinator=coordinator,
    )
    custom_request = _request(value="#123456", artwork_asset_id="cover-a")
    custom_resolution = _resolution(value="#123456")
    auto_request = _request(mode="auto", value=None, artwork_asset_id="cover-b")
    auto_resolution = _resolution(
        mode="auto", value=None, context={"album_palette": [{"hex": "#123456"}]}
    )
    results = []
    failures = []

    def invoke(request, resolution):
        try:
            results.append(service.execute(request, resolution))
        except BaseException as error:
            failures.append(error)

    first = threading.Thread(target=invoke, args=(custom_request, custom_resolution))
    second = threading.Thread(target=invoke, args=(auto_request, auto_resolution))
    first.start()
    assert backend.started.wait(timeout=5)
    second.start()
    _wait_for_flight_callers(coordinator, 2)
    backend.release.set()
    first.join(timeout=5)
    second.join(timeout=5)
    coordinator.close(timeout_seconds=2)

    assert failures == []
    assert backend.render_count == 1
    assert len(results) == 2
    assert results[0].result.preview_id == results[1].result.preview_id
    assert results[0].result.treatment != results[1].result.treatment
    assert results[0].artifact is not results[1].artifact
    for result in results:
        result.close()
    assert all(lease.close_count == 1 for lease in cache.leases)
    assert all(lease.close_count == 1 for lease in resolver.leases)


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("change", "SOURCE_CHANGED"),
        ("remove", "PREVIEW_SOURCE_UNAVAILABLE"),
    ],
)
def test_coalesced_follower_revalidates_its_own_source_after_wait(
    tmp_path, mutation, expected_code
):
    cache = FakeCache(tmp_path)
    backend = FakeBackend()
    backend.release = threading.Event()
    coordinator = PreviewSingleFlightCoordinator(
        ProcessLocalRenderAdmission(), wait_timeout_seconds=5
    )
    source = tmp_path / "source.png"
    resolver = MutableTargetResolver(
        source,
        {
            ("Album", "cover-a"): SOURCE_DIGEST,
            ("Album", "cover-b"): SOURCE_DIGEST,
        },
    )
    service, _ = _service(
        tmp_path,
        cache=cache,
        resolver=resolver,
        backend=backend,
        coordinator=coordinator,
    )
    results = {}
    failures = {}

    def invoke(label, request):
        try:
            results[label] = service.execute(request, _resolution())
        except BaseException as error:
            failures[label] = error

    first = threading.Thread(
        target=invoke,
        args=("a", _request(artwork_asset_id="cover-a")),
    )
    second = threading.Thread(
        target=invoke,
        args=("b", _request(artwork_asset_id="cover-b")),
    )
    first.start()
    assert backend.started.wait(timeout=5)
    second.start()
    _wait_for_flight_callers(coordinator, 2)
    if mutation == "change":
        resolver.set_digest("Album", "cover-b", "e" * 64)
    else:
        resolver.remove("Album", "cover-b")
    backend.release.set()
    first.join(timeout=5)
    second.join(timeout=5)
    coordinator.close(timeout_seconds=2)

    assert not first.is_alive() and not second.is_alive()
    assert "a" in results and "a" not in failures
    assert "b" not in results
    assert isinstance(failures.get("b"), PreviewServiceError)
    assert failures["b"].code == expected_code
    assert backend.render_count == cache.publication_count == 1
    results["a"].close()
    assert all(lease.close_count == 1 for lease in cache.leases)
    assert all(lease.close_count == 1 for lease in resolver.leases)


def test_admitted_cache_recheck_cannot_bypass_caller_source_revalidation(tmp_path):
    cache = FakeCache(tmp_path)
    backend = FakeBackend()
    source = tmp_path / "source.png"
    resolver = MutableTargetResolver(
        source, {("Album", "cover"): SOURCE_DIGEST}
    )
    coordinator = AdmittedCachePublishingCoordinator(
        cache,
        lambda: resolver.set_digest("Album", "cover", "e" * 64),
    )
    service, _ = _service(
        tmp_path,
        cache=cache,
        resolver=resolver,
        backend=backend,
        coordinator=coordinator,
    )

    with pytest.raises(PreviewServiceError) as caught:
        service.execute(_request(), _resolution())

    assert caught.value.code == "SOURCE_CHANGED"
    assert backend.render_count == cache.publication_count == 0
    assert all(lease.close_count == 1 for lease in cache.leases)
    assert all(lease.close_count == 1 for lease in resolver.leases)


def test_source_change_after_preflight_fails_without_publication(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    resolver = FakeResolver(source, [SOURCE_DIGEST, "e" * 64])
    cache = FakeCache(tmp_path)
    service, _ = _service(tmp_path, resolver=resolver, cache=cache)

    with pytest.raises(PreviewServiceError) as caught:
        service.execute(_request(), _resolution())

    assert caught.value.code == "SOURCE_CHANGED"
    assert cache.publication_count == 0
    assert all(lease.close_count == 1 for lease in resolver.leases)


def test_one_corrupt_entry_is_discarded_and_repeated_corruption_fails_closed(tmp_path):
    cache = FakeCache(tmp_path)
    cache.corrupt_lookups = 2
    service, _ = _service(tmp_path, cache=cache)

    with pytest.raises(PreviewServiceError) as caught:
        service.execute(_request(), _resolution())

    assert caught.value.code == "PREVIEW_CACHE_CORRUPT"
    assert cache.discard_count == 1


def test_successful_flight_without_final_artifact_fails_closed(tmp_path):
    cache = FakeCache(tmp_path)
    cache.drop_publication = True
    service, _ = _service(tmp_path, cache=cache)

    with pytest.raises(PreviewServiceError) as caught:
        service.execute(_request(), _resolution())

    assert caught.value.code == "PREVIEW_INTERNAL_ERROR"
    assert "unavailable" in caught.value.message


def test_render_errors_are_typed_and_do_not_expose_paths(tmp_path):
    backend = FakeBackend()
    backend.failure = PreviewRenderError(
        "PREVIEW_RENDER_FAILED", "Preview rendering failed."
    )
    service, source = _service(tmp_path, backend=backend)

    with pytest.raises(PreviewServiceError) as caught:
        service.execute(_request(), _resolution())

    assert caught.value.code == "PREVIEW_RENDER_FAILED"
    assert str(source) not in caught.value.message


def test_fixed_flight_deadline_prevents_late_publication(tmp_path):
    cache = FakeCache(tmp_path)
    backend = FakeBackend()
    backend.release = threading.Event()
    coordinator = PreviewSingleFlightCoordinator(
        ProcessLocalRenderAdmission(), wait_timeout_seconds=0.1
    )
    service, _ = _service(tmp_path, cache=cache, backend=backend, coordinator=coordinator)
    failure = []

    def invoke():
        try:
            service.execute(_request(), _resolution())
        except BaseException as error:
            failure.append(error)

    caller = threading.Thread(target=invoke)
    caller.start()
    assert backend.started.wait(timeout=5)
    caller.join(timeout=0.5)
    assert not caller.is_alive()
    backend.release.set()
    caller.join(timeout=5)
    coordinator.close(timeout_seconds=2)

    assert len(failure) == 1
    assert isinstance(failure[0], PreviewServiceError)
    assert failure[0].code == "PREVIEW_TIMEOUT"
    assert cache.publication_count == 0


class FakeToolchain:
    def __init__(self, ffmpeg: Path, ffprobe: Path):
        self.paths = {"ffmpeg": ffmpeg, "ffprobe": ffprobe}

    def resolve(self, name):
        return MediaTool(self.paths[name], f"{name} ignored")


class CapabilityRunner:
    def run(self, argv, timeout_seconds, cancel_event=None, **kwargs):
        flag = argv[-1]
        if flag == "-version":
            stdout = f"{Path(argv[0]).stem} version 9.0.2\n"
        elif flag == "-filters":
            stdout = "\n".join(f" ... {name} fixture" for name in REQUIRED_FFMPEG_FILTERS)
        elif flag == "-encoders":
            stdout = "\n".join(f" V..... {name} fixture" for name in REQUIRED_FFMPEG_ENCODERS)
        elif flag == "-decoders":
            stdout = "\n".join(
                f" V..... {name} fixture" for name in {"mjpeg", "png", "webp", "webp_anim"}
            )
        else:
            raise AssertionError(argv)
        return SimpleNamespace(
            returncode=0,
            stdout=stdout,
            stderr_tail="",
            cancelled=False,
            timed_out=False,
        )

    def sanitize_diagnostic(self, text):
        return text


def test_verified_toolchain_hashes_both_binaries_and_rejects_post_identity_replacement(tmp_path):
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    ffmpeg.write_bytes(b"ffmpeg")
    ffprobe.write_bytes(b"ffprobe")
    backend = VerifiedFFmpegPreviewBackend(
        FakeToolchain(ffmpeg, ffprobe), CapabilityRunner()
    )

    first = backend.identify()
    assert first.ffmpeg_sha256 == hashlib.sha256(b"ffmpeg").hexdigest()
    assert first.ffprobe_sha256 == hashlib.sha256(b"ffprobe").hexdigest()
    ffmpeg.write_bytes(b"replacement")
    with pytest.raises(PreviewRenderError) as caught:
        backend.render(
            source_path=tmp_path / "source.png",
            output_path=tmp_path / "preview.png",
            resolution=_resolution(),
            expected_toolchain=first,
        )
    assert caught.value.code == "PREVIEW_INTERNAL_ERROR"
    assert str(ffmpeg) not in caught.value.message
    assert backend.identify() != first


@pytest.mark.parametrize("mutated_tool", ["ffmpeg", "ffprobe"])
def test_tool_replacement_during_render_prevents_cache_publication_and_cleans_up(
    tmp_path, monkeypatch, mutated_tool
):
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    ffmpeg.write_bytes(b"ffmpeg")
    ffprobe.write_bytes(b"ffprobe")
    target = {"ffmpeg": ffmpeg, "ffprobe": ffprobe}[mutated_tool]

    class MutatingRenderer:
        def __init__(self, toolchain, runner, output_root, timeout_seconds):
            self.output_root = Path(output_root)

        def render(self, request, cancel_event=None):
            output = self.output_root / request.output_relative_path
            output.write_bytes(b"rendered-before-tool-mutation")
            target.write_bytes(b"replacement-during-render")
            return StillRenderResult(
                contract_version=STILL_RENDER_RESULT_VERSION,
                artifact_path=output,
                source_sha256=SOURCE_DIGEST,
                treatment=request.resolution,
                width=2,
                height=1,
                output_format="png",
                renderer_version=STILL_RENDERER_VERSION,
                transform_version=TRANSFORM_VERSION,
                ffmpeg_version="ffmpeg fixture",
                input_pixel_format="rgba",
                output_pixel_format="rgba",
                orientation="normalized",
                sanitized_command=("<tool:ffmpeg>",),
            )

    monkeypatch.setattr(
        preview_toolchain_module, "FFmpegStillImageRenderer", MutatingRenderer
    )
    backend = VerifiedFFmpegPreviewBackend(
        FakeToolchain(ffmpeg, ffprobe), CapabilityRunner()
    )
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    cache = SecureFilesystemPreviewCache(cache_root)
    service, source = _service(tmp_path, cache=cache, backend=backend)

    try:
        with pytest.raises(PreviewServiceError) as caught:
            service.execute(_request(), _resolution())

        assert caught.value.code == "PREVIEW_INTERNAL_ERROR"
        assert str(target) not in caught.value.message
        assert str(source) not in caught.value.message
        assert list((cache_root / ".preview-cache-staging").iterdir()) == []
        assert list((cache_root / "entries").iterdir()) == []
        assert all(lease.close_count == 1 for lease in service._source_resolver.leases)
    finally:
        cache.close()
