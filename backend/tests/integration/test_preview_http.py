from __future__ import annotations

import asyncio
import json
import re
import socket
import threading
import time
from email import policy
from email.parser import BytesParser
from pathlib import Path
from types import SimpleNamespace

import pytest
import httpx
import uvicorn
from fastapi.testclient import TestClient

from wrld_video_studio.application.preview_service import PreparedPreview, PreviewServiceError
from wrld_video_studio.domain.color_resolution import (
    INPUT_CONTRACT_VERSION,
    resolve_color_treatment,
)
from wrld_video_studio.domain.preview_cache import (
    PreviewResult,
    PreviewToolchainIdentity,
    build_preview_cache_identity,
)
from wrld_video_studio.application.ports.preview_cache import CachedPreviewArtifact
from wrld_video_studio.interfaces.http.app import (
    DEFAULT_BIND_HOST,
    PreviewApplicationConfig,
    PreviewApplicationRuntime,
    _HTTPRequestOwnership,
    create_app,
    serve,
)
from wrld_video_studio.interfaces.http import preview as preview_module


PNG = b"\x89PNG\r\n\x1a\npreview-bytes"


def _request():
    return {
        "contract_version": "preview-request-v1",
        "target": {"album_id": "album-1", "artwork_asset_id": "artwork-1"},
        "treatment": {"mode": "custom", "hex": "#123456", "intensity": 0.3},
        "variant": "authoritative_still",
    }


class _ArtifactLease:
    def __init__(self, data=PNG, *, fail_read=False):
        self.data = data
        self.position = 0
        self.close_count = 0
        self.fail_read = fail_read
        self._artifact = CachedPreviewArtifact(
            preview_id="unused",
            artifact_sha256="d" * 64,
            byte_size=len(data),
            width=2,
            height=1,
        )

    @property
    def artifact(self):
        return self._artifact

    def read(self, amount=-1):
        if self.fail_read:
            raise RuntimeError("injected read failure")
        if amount < 0:
            amount = len(self.data) - self.position
        chunk = self.data[self.position : self.position + amount]
        self.position += len(chunk)
        return chunk

    def seek(self, offset, whence=0):
        if whence == 0:
            self.position = offset
        elif whence == 1:
            self.position += offset
        else:
            self.position = len(self.data) + offset
        return self.position

    def close(self):
        self.close_count += 1


def _prepared(lease=None):
    lease = lease or _ArtifactLease()
    resolution = resolve_color_treatment(
        {
            "contract_version": INPUT_CONTRACT_VERSION,
            "treatment": {"mode": "custom", "hex": "#123456", "intensity": 0.3},
        }
    )
    identity = build_preview_cache_identity(
        source_sha256="c" * 64,
        resolution=resolution,
        toolchain=PreviewToolchainIdentity("a" * 64, "b" * 64),
    )
    lease._artifact = CachedPreviewArtifact(
        preview_id=identity.preview_id,
        artifact_sha256="d" * 64,
        byte_size=len(lease.data),
        width=2,
        height=1,
    )
    result = PreviewResult.create(
        identity=identity,
        cache_status="miss",
        width=2,
        height=1,
        artifact_sha256="d" * 64,
    )
    return PreparedPreview(result, lease), lease


class _Service:
    def __init__(self, *, failure=None, prepared=None):
        self.failure = failure
        self.prepared = prepared
        self.calls = []

    def execute(self, request, cancel_event=None):
        self.calls.append((request, cancel_event))
        if self.failure is not None:
            raise self.failure
        return self.prepared


class _Runtime:
    def __init__(self, service):
        self.preview_service = service
        self._condition = threading.Condition()
        self._requests = set()
        self.release_count = 0
        self._accepting = True
        self.closed = False

    def begin_request(self):
        ownership = _HTTPRequestOwnership(self)
        with self._condition:
            self._requests.add(ownership)
        return ownership

    def _release_request(self, ownership):
        with self._condition:
            self.release_count += 1
            self._requests.discard(ownership)
            self._condition.notify_all()

    def close(self):
        self._accepting = False
        for request in tuple(self._requests):
            request.cancel_event.set()
            request.close()
        self.closed = True


def _app(runtime):
    return create_app(object(), runtime_factory=lambda _config: runtime)


def _multipart(response):
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {response.headers['content-type']}\r\nMIME-Version: 1.0\r\n\r\n".encode()
        + response.content
    )
    return list(message.iter_parts())


def test_http_success_is_exact_result_json_plus_streamed_png_and_closes_pin_once():
    prepared, lease = _prepared()
    service = _Service(prepared=prepared)
    runtime = _Runtime(service)

    with TestClient(_app(runtime)) as client:
        response = client.post("/api/v1/previews/still", json=_request())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("multipart/related;")
    parts = _multipart(response)
    assert [part.get_content_type() for part in parts] == ["application/json", "image/png"]
    assert json.loads(parts[0].get_payload(decode=True)) == prepared.result.to_dict()
    assert parts[1].get_payload(decode=True) == PNG
    assert lease.close_count == 1
    assert runtime.closed


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("PREVIEW_INVALID_REQUEST", 422),
        ("PREVIEW_SOURCE_UNAVAILABLE", 404),
        ("SOURCE_CHANGED", 409),
        ("PREVIEW_IMAGE_UNSUPPORTED", 422),
        ("PREVIEW_CANCELLED", 408),
        ("PREVIEW_TIMEOUT", 504),
        ("PREVIEW_CAPACITY_EXHAUSTED", 503),
        ("PREVIEW_RENDER_FAILED", 500),
        ("PREVIEW_CACHE_CORRUPT", 500),
        ("PREVIEW_INTERNAL_ERROR", 500),
    ],
)
def test_every_typed_preview_error_has_approved_http_mapping(code, status):
    runtime = _Runtime(_Service(failure=PreviewServiceError(code, "Safe preview failure.")))
    with TestClient(_app(runtime)) as client:
        response = client.post("/api/v1/previews/still", json=_request())

    assert response.status_code == status
    payload = response.json()
    assert payload["contract_version"] == "preview-error-v1"
    assert payload["error"]["code"] == code
    assert payload["error"]["message"] == "Safe preview failure."
    assert payload["error"]["details"] == {}
    assert re.fullmatch(r"preview-[a-f0-9]{32}", payload["error"]["correlation_id"])


def test_validation_errors_use_typed_envelope_and_server_correlation_ids():
    runtime = _Runtime(_Service())
    invalid = _request()
    invalid["source_path"] = "C:/private/source.png"
    with TestClient(_app(runtime)) as client:
        first = client.post("/api/v1/previews/still", json=invalid)
        second = client.post("/api/v1/previews/still", json=invalid)

    assert first.status_code == 422
    assert first.json()["error"]["code"] == "PREVIEW_INVALID_REQUEST"
    assert "source_path" not in first.text
    assert first.json()["error"]["correlation_id"] != second.json()["error"]["correlation_id"]


def test_openapi_documents_strict_body_multipart_success_and_all_statuses():
    operation = _app(_Runtime(_Service())).openapi()["paths"]["/api/v1/previews/still"]["post"]

    assert "application/json" in operation["requestBody"]["content"]
    assert "multipart/related" in operation["responses"]["200"]["content"]
    assert set(operation["responses"]) >= {"200", "404", "408", "409", "422", "500", "503", "504"}
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert "$ref" in request_schema


def test_early_stream_termination_closes_pin_exactly_once():
    async def exercise():
        prepared, lease = _prepared()
        runtime = _Runtime(_Service())
        ownership = runtime.begin_request()
        ownership.attach(prepared)
        ownership.finish_execution()
        watcher = asyncio.create_task(asyncio.sleep(60))
        stream = preview_module._multipart_stream(ownership, watcher, "boundary")
        await anext(stream)
        await stream.aclose()
        return lease, runtime

    lease, runtime = asyncio.run(exercise())

    assert lease.close_count == 1
    assert not runtime._requests


def test_stream_iterator_failure_closes_pin_exactly_once():
    async def exercise():
        prepared, lease = _prepared(_ArtifactLease(fail_read=True))
        runtime = _Runtime(_Service())
        ownership = runtime.begin_request()
        ownership.attach(prepared)
        ownership.finish_execution()
        watcher = asyncio.create_task(asyncio.sleep(60))
        stream = preview_module._multipart_stream(ownership, watcher, "boundary")
        with pytest.raises(RuntimeError, match="injected read failure"):
            async for _chunk in stream:
                pass
        return lease, runtime

    lease, runtime = asyncio.run(exercise())

    assert lease.close_count == 1
    assert not runtime._requests


def test_response_construction_failure_closes_prepared_preview(monkeypatch):
    async def exercise():
        prepared, lease = _prepared()
        runtime = _Runtime(_Service(prepared=prepared))
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(preview_runtime=runtime)))

        async def connected():
            return False

        request.is_disconnected = connected

        def fail_response(*_args, **_kwargs):
            raise RuntimeError("injected construction failure")

        monkeypatch.setattr(preview_module, "StreamingResponse", fail_response)
        response = await preview_module.create_still_preview(
            preview_module.PreviewRequestModel.model_validate(_request()), request
        )
        return response, lease, runtime

    response, lease, runtime = asyncio.run(exercise())

    assert response.status_code == 500
    assert lease.close_count == 1
    assert not runtime._requests


class _Coordinator:
    def __init__(self):
        self.closed = 0

    def close(self, *, timeout_seconds):
        assert timeout_seconds > 0
        self.closed += 1


class _Cache:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


def _bare_runtime(tmp_path, shutdown=0.2):
    from wrld_video_studio.infrastructure.artwork_sources import (
        ArtworkSourceRegistration,
        TrustedArtworkRoot,
    )
    from wrld_video_studio.infrastructure.preview_context import PreviewContextRegistration

    runtime = PreviewApplicationRuntime.__new__(PreviewApplicationRuntime)
    runtime.config = PreviewApplicationConfig(
        artwork_roots=(TrustedArtworkRoot("main", tmp_path),),
        artwork_registrations=(
            ArtworkSourceRegistration("album", "artwork", "main", "cover.png"),
        ),
        context_registrations=(
            PreviewContextRegistration("album", "artwork", {}),
        ),
        snapshot_root=tmp_path / "snapshots",
        cache_root=tmp_path / "cache",
        ffmpeg_path=tmp_path / "ffmpeg",
        ffprobe_path=tmp_path / "ffprobe",
        preview_wait_timeout_seconds=1.0,
        preview_render_timeout_seconds=1.0,
        shutdown_timeout_seconds=shutdown,
    )
    runtime._condition = threading.Condition()
    runtime._requests = set()
    runtime._accepting = True
    runtime._closed = False
    runtime.coordinator = _Coordinator()
    runtime.cache = _Cache()
    return runtime


def test_shutdown_cancels_stream_closes_pin_then_cache(tmp_path):
    runtime = _bare_runtime(tmp_path)
    prepared, lease = _prepared()
    ownership = runtime.begin_request()
    ownership.attach(prepared)
    ownership.finish_execution()

    runtime.close()

    assert ownership.cancel_event.is_set()
    assert lease.close_count == 1
    assert runtime.coordinator.closed == 1
    assert runtime.cache.closed == 1
    assert not runtime._requests


def test_shutdown_is_bounded_and_does_not_close_cache_while_execution_is_live(tmp_path):
    runtime = _bare_runtime(tmp_path, shutdown=0.02)
    ownership = runtime.begin_request()

    with pytest.raises(PreviewServiceError) as raised:
        runtime.close()

    assert raised.value.code == "PREVIEW_TIMEOUT"
    assert ownership.cancel_event.is_set()
    assert runtime.cache.closed == 0
    ownership.finish_execution()
    ownership.close()


def test_wu2_worker_factory_uses_the_exact_shared_admission(tmp_path):
    runtime = _bare_runtime(tmp_path)
    runtime.render_admission = object()

    worker = runtime.build_render_worker(
        object(), object(), object(), object(), object(), tmp_path
    )

    assert worker.admission is runtime.render_admission


def test_live_loopback_uvicorn_smoke_uses_approved_endpoint():
    prepared, lease = _prepared()
    runtime = _Runtime(_Service(prepared=prepared))
    app = _app(runtime)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    host, port = listener.getsockname()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="on")
    )
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    try:
        assert server.started
        assert host == "127.0.0.1"
        response = httpx.post(
            f"http://127.0.0.1:{port}/api/v1/previews/still",
            json=_request(),
            timeout=5,
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("multipart/related;")
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
    assert not thread.is_alive()
    assert lease.close_count == 1


def test_direct_asgi_disconnect_sets_only_the_request_cancellation_event():
    class DisconnectService:
        def __init__(self):
            self.event = None

        def execute(self, _request, cancel_event=None):
            self.event = cancel_event
            assert cancel_event.wait(timeout=2)
            raise PreviewServiceError("PREVIEW_CANCELLED", "The preview request was cancelled.")

    async def exercise():
        service = DisconnectService()
        runtime = _Runtime(service)
        app = _app(runtime)
        app.state.preview_runtime = runtime
        request_messages = [
            {
                "type": "http.request",
                "body": json.dumps(_request()).encode(),
                "more_body": False,
            },
            {"type": "http.disconnect"},
        ]
        sent = []

        async def receive():
            if request_messages:
                return request_messages.pop(0)
            await asyncio.sleep(60)

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/previews/still",
            "raw_path": b"/api/v1/previews/still",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 8000),
            "root_path": "",
        }
        await app(scope, receive, send)
        return service, runtime, sent

    service, runtime, sent = asyncio.run(exercise())
    assert service.event is not None and service.event.is_set()
    assert not runtime._requests
    assert any(message["type"] == "http.response.start" for message in sent)


def test_asgi_task_cancellation_waits_for_cooperative_service_cleanup():
    class CancelledService:
        def __init__(self):
            self.started = threading.Event()
            self.finished = threading.Event()

        def execute(self, _request, cancel_event=None):
            self.started.set()
            assert cancel_event.wait(timeout=2)
            self.finished.set()
            raise PreviewServiceError("PREVIEW_CANCELLED", "The preview request was cancelled.")

    async def exercise():
        service = CancelledService()
        runtime = _Runtime(service)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(preview_runtime=runtime)))

        async def connected():
            return False

        request.is_disconnected = connected
        task = asyncio.create_task(
            preview_module.create_still_preview(
                preview_module.PreviewRequestModel.model_validate(_request()), request
            )
        )
        await asyncio.to_thread(service.started.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return service, runtime

    service, runtime = asyncio.run(exercise())
    assert service.finished.is_set()
    assert not runtime._requests


@pytest.mark.parametrize("cancel_before_return", [True, False])
def test_asgi_task_cancellation_closes_late_success_result_once(cancel_before_return):
    class LateSuccessService:
        def __init__(self, prepared):
            self.prepared = prepared
            self.started = threading.Event()
            self.release = threading.Event()
            self.returned = threading.Event()

        def execute(self, _request, cancel_event=None):
            self.started.set()
            if cancel_before_return:
                assert cancel_event.wait(timeout=2)
            else:
                assert self.release.wait(timeout=2)
            self.returned.set()
            return self.prepared

    async def exercise():
        prepared, lease = _prepared()
        service = LateSuccessService(prepared)
        runtime = _Runtime(service)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(preview_runtime=runtime)))

        async def connected():
            return False

        request.is_disconnected = connected
        task = asyncio.create_task(
            preview_module.create_still_preview(
                preview_module.PreviewRequestModel.model_validate(_request()), request
            )
        )
        assert await asyncio.to_thread(service.started.wait, 2)
        if cancel_before_return:
            task.cancel()
        else:
            service.release.set()
            assert service.returned.wait(timeout=2)
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        pending = [
            item
            for item in asyncio.all_tasks()
            if item is not asyncio.current_task() and not item.done()
        ]
        return lease, runtime, pending

    lease, runtime, pending = asyncio.run(exercise())
    assert lease.close_count == 1
    assert runtime.release_count == 1
    assert not runtime._requests
    assert pending == []


def test_failed_disconnect_watcher_before_response_delivery_cannot_bypass_cleanup(caplog):
    class WatcherFailureService:
        def __init__(self, prepared):
            self.prepared = prepared

        def execute(self, _request, cancel_event=None):
            assert cancel_event.wait(timeout=2)
            return self.prepared

    async def exercise():
        prepared, lease = _prepared()
        runtime = _Runtime(WatcherFailureService(prepared))
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(preview_runtime=runtime)))

        async def failed_receive():
            raise OSError("private injected ASGI receive failure")

        request.is_disconnected = failed_receive

        response = await preview_module.create_still_preview(
            preview_module.PreviewRequestModel.model_validate(_request()), request
        )
        pending = [
            item
            for item in asyncio.all_tasks()
            if item is not asyncio.current_task() and not item.done()
        ]
        return response, lease, runtime, pending

    caplog.set_level("ERROR")
    response, lease, runtime, pending = asyncio.run(exercise())
    assert response.status_code == 408
    assert json.loads(response.body)["error"]["code"] == "PREVIEW_CANCELLED"
    assert b"private injected ASGI receive failure" not in response.body
    assert lease.close_count == 1
    assert runtime.release_count == 1
    assert not runtime._requests
    assert pending == []
    assert "Preview disconnect watcher failed" in caplog.text


def test_failed_disconnect_watcher_during_streaming_closes_pin_exactly_once(caplog):
    async def failed_watcher():
        raise OSError("private injected ASGI receive failure")

    async def exercise():
        prepared, lease = _prepared()
        runtime = _Runtime(_Service())
        ownership = runtime.begin_request()
        ownership.attach(prepared)
        ownership.finish_execution()
        watcher = asyncio.create_task(failed_watcher())
        await asyncio.sleep(0)
        stream = preview_module._multipart_stream(ownership, watcher, "boundary")
        await anext(stream)
        await stream.aclose()
        pending = [
            item
            for item in asyncio.all_tasks()
            if item is not asyncio.current_task() and not item.done()
        ]
        return lease, runtime, pending

    caplog.set_level("ERROR")
    lease, runtime, pending = asyncio.run(exercise())
    assert lease.close_count == 1
    assert runtime.release_count == 1
    assert not runtime._requests
    assert pending == []
    assert "Preview disconnect watcher failed" in caplog.text


def test_watcher_failure_does_not_mask_primary_stream_failure(caplog):
    async def failed_watcher():
        raise OSError("private injected ASGI receive failure")

    async def exercise():
        prepared, lease = _prepared(_ArtifactLease(fail_read=True))
        runtime = _Runtime(_Service())
        ownership = runtime.begin_request()
        ownership.attach(prepared)
        ownership.finish_execution()
        watcher = asyncio.create_task(failed_watcher())
        await asyncio.sleep(0)
        stream = preview_module._multipart_stream(ownership, watcher, "boundary")
        with pytest.raises(RuntimeError, match="injected read failure"):
            async for _chunk in stream:
                pass
        return lease, runtime

    caplog.set_level("ERROR")
    lease, runtime = asyncio.run(exercise())
    assert lease.close_count == 1
    assert runtime.release_count == 1
    assert not runtime._requests
    assert "Preview disconnect watcher failed" in caplog.text


def test_watcher_failure_concurrent_with_repeated_request_cancellation_cleans_everything(
    caplog,
):
    class ConcurrentFailureService:
        def __init__(self, prepared):
            self.prepared = prepared
            self.started = threading.Event()
            self.release = threading.Event()

        def execute(self, _request, cancel_event=None):
            self.started.set()
            assert cancel_event.wait(timeout=2)
            assert self.release.wait(timeout=2)
            return self.prepared

    async def exercise():
        prepared, lease = _prepared()
        service = ConcurrentFailureService(prepared)
        runtime = _Runtime(service)
        watcher_failed = asyncio.Event()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(preview_runtime=runtime)))

        async def failed_receive():
            watcher_failed.set()
            raise OSError("private injected ASGI receive failure")

        request.is_disconnected = failed_receive
        task = asyncio.create_task(
            preview_module.create_still_preview(
                preview_module.PreviewRequestModel.model_validate(_request()), request
            )
        )
        assert await asyncio.to_thread(service.started.wait, 2)
        await asyncio.wait_for(watcher_failed.wait(), timeout=2)
        task.cancel()
        task.cancel()
        service.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        pending = [
            item
            for item in asyncio.all_tasks()
            if item is not asyncio.current_task() and not item.done()
        ]
        return lease, runtime, pending

    caplog.set_level("ERROR")
    lease, runtime, pending = asyncio.run(exercise())
    assert lease.close_count == 1
    assert runtime.release_count == 1
    assert not runtime._requests
    assert pending == []
    assert "Preview disconnect watcher failed" in caplog.text


def test_provided_server_entrypoint_is_fixed_to_loopback(monkeypatch, tmp_path):
    config = _bare_runtime(tmp_path).config
    called = {}

    def fake_run(app, *, host, port):
        called.update(app=app, host=host, port=port)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    serve(config, port=8765)

    assert called["host"] == DEFAULT_BIND_HOST == "127.0.0.1"
    assert called["port"] == 8765


class _LifecycleRuntime:
    def __init__(self, *, block_close=False, close_failure=None):
        self.close_count = 0
        self.close_started = threading.Event()
        self.close_release = threading.Event()
        self.close_failure = close_failure
        if not block_close:
            self.close_release.set()

    def close(self):
        self.close_count += 1
        self.close_started.set()
        assert self.close_release.wait(timeout=2)
        if self.close_failure is not None:
            raise self.close_failure


@pytest.mark.parametrize("cancel_before_factory_return", [True, False])
def test_cancelled_lifespan_startup_closes_unpublished_runtime_once(
    cancel_before_factory_return,
):
    async def exercise():
        runtime = _LifecycleRuntime()
        factory_started = threading.Event()
        factory_release = threading.Event()
        factory_returned = threading.Event()

        def factory(_config):
            factory_started.set()
            assert factory_release.wait(timeout=2)
            factory_returned.set()
            return runtime

        app = create_app(object(), runtime_factory=factory)
        context = app.router.lifespan_context(app)
        startup = asyncio.create_task(context.__aenter__())
        assert await asyncio.to_thread(factory_started.wait, 2)
        if cancel_before_factory_return:
            startup.cancel()
            factory_release.set()
        else:
            factory_release.set()
            assert factory_returned.wait(timeout=2)
            startup.cancel()
        with pytest.raises(asyncio.CancelledError):
            await startup
        pending = [
            item
            for item in asyncio.all_tasks()
            if item is not asyncio.current_task() and not item.done()
        ]
        return runtime, app, pending

    runtime, app, pending = asyncio.run(exercise())
    assert runtime.close_count == 1
    assert not hasattr(app.state, "preview_runtime")
    assert pending == []


def test_repeated_cancellation_during_startup_reconciliation_waits_for_runtime_close():
    async def exercise():
        runtime = _LifecycleRuntime(block_close=True)
        factory_started = threading.Event()
        factory_release = threading.Event()

        def factory(_config):
            factory_started.set()
            assert factory_release.wait(timeout=2)
            return runtime

        app = create_app(object(), runtime_factory=factory)
        context = app.router.lifespan_context(app)
        startup = asyncio.create_task(context.__aenter__())
        assert await asyncio.to_thread(factory_started.wait, 2)
        startup.cancel()
        factory_release.set()
        assert await asyncio.to_thread(runtime.close_started.wait, 2)
        for _ in range(3):
            startup.cancel()
            await asyncio.sleep(0)
        assert not startup.done()
        runtime.close_release.set()
        with pytest.raises(asyncio.CancelledError):
            await startup
        pending = [
            item
            for item in asyncio.all_tasks()
            if item is not asyncio.current_task() and not item.done()
        ]
        return runtime, app, pending

    runtime, app, pending = asyncio.run(exercise())
    assert runtime.close_count == 1
    assert not hasattr(app.state, "preview_runtime")
    assert pending == []


def test_lifespan_factory_failure_propagates_without_publishing_runtime():
    async def exercise():
        def factory(_config):
            raise RuntimeError("injected factory failure")

        app = create_app(object(), runtime_factory=factory)
        context = app.router.lifespan_context(app)
        with pytest.raises(RuntimeError, match="injected factory failure"):
            await context.__aenter__()
        return app

    app = asyncio.run(exercise())
    assert not hasattr(app.state, "preview_runtime")


def test_lifespan_publication_failure_closes_constructed_runtime_once():
    class FailingState:
        def __setattr__(self, _name, _value):
            raise RuntimeError("injected publication failure")

    async def exercise():
        runtime = _LifecycleRuntime()
        app = create_app(object(), runtime_factory=lambda _config: runtime)
        context = app.router.lifespan_context(SimpleNamespace(state=FailingState()))
        with pytest.raises(RuntimeError, match="injected publication failure"):
            await context.__aenter__()
        return runtime

    runtime = asyncio.run(exercise())
    assert runtime.close_count == 1


def test_cancelled_startup_reports_runtime_cleanup_failure_explicitly():
    async def exercise():
        runtime = _LifecycleRuntime(close_failure=OSError("private cleanup failure"))
        factory_started = threading.Event()
        factory_release = threading.Event()

        def factory(_config):
            factory_started.set()
            assert factory_release.wait(timeout=2)
            return runtime

        app = create_app(object(), runtime_factory=factory)
        context = app.router.lifespan_context(app)
        startup = asyncio.create_task(context.__aenter__())
        assert await asyncio.to_thread(factory_started.wait, 2)
        startup.cancel()
        factory_release.set()
        with pytest.raises(RuntimeError, match="ownership could not be released") as raised:
            await startup
        return runtime, app, raised.value

    runtime, app, failure = asyncio.run(exercise())
    assert runtime.close_count == 1
    assert isinstance(failure.__cause__, OSError)
    assert not hasattr(app.state, "preview_runtime")


def test_configuration_requires_album_context_for_every_registered_artwork(tmp_path):
    from wrld_video_studio.infrastructure.artwork_sources import (
        ArtworkSourceRegistration,
        TrustedArtworkRoot,
    )

    with pytest.raises(ValueError, match="Auto-color context"):
        PreviewApplicationConfig(
            artwork_roots=(TrustedArtworkRoot("main", tmp_path),),
            artwork_registrations=(
                ArtworkSourceRegistration("album", "artwork", "main", "cover.png"),
            ),
            context_registrations=(),
            snapshot_root=tmp_path / "snapshots",
            cache_root=tmp_path / "cache",
            ffmpeg_path=tmp_path / "ffmpeg",
            ffprobe_path=tmp_path / "ffprobe",
            preview_wait_timeout_seconds=1.0,
            preview_render_timeout_seconds=1.0,
            shutdown_timeout_seconds=1.0,
        )


@pytest.mark.parametrize("failure", ["context", "toolchain"])
def test_partial_startup_failure_releases_claimed_cache_root(tmp_path, failure):
    from wrld_video_studio.infrastructure.artwork_sources import (
        ArtworkSourceRegistration,
        TrustedArtworkRoot,
    )
    from wrld_video_studio.infrastructure.preview_cache import SecureFilesystemPreviewCache
    from wrld_video_studio.infrastructure.preview_context import PreviewContextRegistration

    source_root = tmp_path / "sources"
    snapshot_root = tmp_path / "snapshots"
    cache_root = tmp_path / "cache"
    for directory in (source_root, snapshot_root, cache_root):
        directory.mkdir()
    (source_root / "cover.png").write_bytes(PNG)
    context = {"unsupported": True} if failure == "context" else {}
    config = PreviewApplicationConfig(
        artwork_roots=(TrustedArtworkRoot("main", source_root),),
        artwork_registrations=(
            ArtworkSourceRegistration("album", "artwork", "main", "cover.png"),
        ),
        context_registrations=(
            PreviewContextRegistration("album", "artwork", context),
        ),
        snapshot_root=snapshot_root,
        cache_root=cache_root,
        ffmpeg_path=tmp_path / "missing-ffmpeg",
        ffprobe_path=tmp_path / "missing-ffprobe",
        preview_wait_timeout_seconds=1.0,
        preview_render_timeout_seconds=1.0,
        shutdown_timeout_seconds=1.0,
    )

    with pytest.raises(Exception):
        PreviewApplicationRuntime(config)

    reopened = SecureFilesystemPreviewCache(cache_root)
    reopened.close()
