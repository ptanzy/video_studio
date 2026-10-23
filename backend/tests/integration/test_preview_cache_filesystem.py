import hashlib
import json
import os
import struct
import subprocess
import threading
import zlib
from pathlib import Path

import pytest

from wrld_video_studio.application.ports.preview_cache import PreviewCacheError
from wrld_video_studio.domain.canonical_json import canonical_json_bytes
from wrld_video_studio.domain.color_resolution import INPUT_CONTRACT_VERSION, resolve_color_treatment
from wrld_video_studio.domain.preview_cache import PreviewToolchainIdentity, build_preview_cache_identity
from wrld_video_studio.infrastructure.preview_cache import SecureFilesystemPreviewCache
from wrld_video_studio.infrastructure import preview_cache as cache_adapter


def _identity(source="3" * 64, ffmpeg="5" * 64):
    resolution = resolve_color_treatment(
        {
            "contract_version": INPUT_CONTRACT_VERSION,
            "treatment": {"mode": "custom", "hex": "#ABCDEF", "intensity": 0.3},
        }
    )
    return build_preview_cache_identity(
        source_sha256=source,
        resolution=resolution,
        toolchain=PreviewToolchainIdentity.create(
            ffmpeg_sha256=ffmpeg,
            ffprobe_sha256="6" * 64,
        ),
    )


def _chunk(name: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)


def _png(width=3, height=2, rgb=(17, 42, 99)) -> bytes:
    rows = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(rows))
        + _chunk(b"IEND", b"")
    )


def _publish(cache, identity, value=None, *, width=3, height=2):
    staging = cache.begin_write(identity)
    staging.output_path.write_bytes(value or _png(width, height))
    return staging.publish(width=width, height=height)


def _entry(root: Path, preview_id: str) -> Path:
    return root / "entries" / preview_id[:2] / preview_id


def _rewrite_manifest(path: Path, change):
    manifest = json.loads(path.read_text(encoding="utf-8"))
    change(manifest)
    path.write_bytes(canonical_json_bytes(manifest))


def test_valid_publication_lookup_and_explicit_pinned_lease(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    identity = _identity()
    with SecureFilesystemPreviewCache(root) as cache:
        with _publish(cache, identity) as published:
            assert published.artifact.preview_id == identity.preview_id
            assert published.artifact.artifact_sha256 == hashlib.sha256(_png()).hexdigest()
            assert published.read() == _png()
            published.seek(0)
            assert published.read(8) == b"\x89PNG\r\n\x1a\n"
        with cache.lookup(identity) as hit:
            assert hit.artifact.width == 3
            assert hit.artifact.height == 2
            assert hit.read() == _png()


def test_cancellation_during_publication_validation_prevents_atomic_publish(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    entered = threading.Event()
    release = threading.Event()

    def hook(stage):
        if stage == "before_publish":
            entered.set()
            assert release.wait(timeout=5)

    identity = _identity()
    cache = SecureFilesystemPreviewCache(root, _event_hook=hook)
    staging = cache.begin_write(identity)
    staging.output_path.write_bytes(_png())
    cancel = threading.Event()
    failure = []

    def publish():
        try:
            staging.publish(width=3, height=2, cancel_event=cancel)
        except BaseException as error:
            failure.append(error)

    worker = threading.Thread(target=publish)
    worker.start()
    assert entered.wait(timeout=5)
    cancel.set()
    release.set()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert len(failure) == 1
    assert isinstance(failure[0], PreviewCacheError)
    assert failure[0].code == "PREVIEW_CANCELLED"
    assert cache.lookup(identity) is None
    staging.close()
    cache.close()


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.update(contract_version="unknown"),
        lambda value: value["descriptor"].update(source_sha256="4" * 64),
        lambda value: value["descriptor"]["toolchain"].update(ffmpeg_sha256="7" * 64),
        lambda value: value["artifact"].update(sha256="8" * 64),
        lambda value: value["artifact"].update(byte_size=value["artifact"]["byte_size"] + 1),
        lambda value: value["artifact"].update(width=value["artifact"]["width"] + 1),
    ],
    ids=["version", "source", "renderer-fingerprint", "hash", "size", "dimensions"],
)
def test_manifest_tampering_is_cache_corruption(tmp_path, change):
    root = tmp_path / "cache"
    root.mkdir()
    identity = _identity()
    cache = SecureFilesystemPreviewCache(root)
    with _publish(cache, identity):
        pass
    _rewrite_manifest(_entry(root, identity.preview_id) / "entry.json", change)
    with pytest.raises(PreviewCacheError, match="integrity") as raised:
        cache.lookup(identity)
    assert raised.value.code == "PREVIEW_CACHE_CORRUPT"
    assert str(root) not in raised.value.message
    cache.close()


def test_corrupt_persisted_entry_can_be_reopened_discarded_and_regenerated(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    unrelated = root / "unrelated.txt"
    unrelated.write_text("preserve", encoding="utf-8")
    identity = _identity()
    with SecureFilesystemPreviewCache(root) as cache:
        with _publish(cache, identity):
            pass

    artifact = _entry(root, identity.preview_id) / "preview.png"
    artifact.write_bytes(b"corrupt persisted artifact")
    with SecureFilesystemPreviewCache(root) as cache:
        with pytest.raises(PreviewCacheError) as raised:
            cache.lookup(identity)
        assert raised.value.code == "PREVIEW_CACHE_CORRUPT"
        assert cache.discard_corrupt(identity)
        with _publish(cache, identity) as regenerated:
            assert regenerated.read() == _png()
    assert unrelated.read_text(encoding="utf-8") == "preserve"


def test_corrupt_persisted_entry_remains_capacity_consuming_until_discarded(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    identity = _identity()
    with SecureFilesystemPreviewCache(root) as cache:
        with _publish(cache, identity):
            pass
    (_entry(root, identity.preview_id) / "preview.png").write_bytes(b"x" * 1024)

    with SecureFilesystemPreviewCache(root, max_bytes=64) as cache:
        with pytest.raises(PreviewCacheError) as raised:
            cache.enforce_limits()
        assert raised.value.code == "PREVIEW_CAPACITY_EXHAUSTED"
        assert cache.discard_corrupt(identity)
        cache.enforce_limits()


@pytest.mark.parametrize(
    "value",
    [
        b"\x89PNG\r\n\x1a\n",
        _png()[:-4],
        _png()[:30] + b"corrupt" + _png()[37:],
    ],
    ids=["header-only", "truncated", "malformed"],
)
def test_invalid_png_is_rejected_before_publication(tmp_path, value):
    root = tmp_path / "cache"
    root.mkdir()
    with SecureFilesystemPreviewCache(root) as cache:
        staging = cache.begin_write(_identity())
        staging.output_path.write_bytes(value)
        with pytest.raises(PreviewCacheError) as raised:
            staging.publish(width=3, height=2)
        assert raised.value.code == "PREVIEW_CACHE_CORRUPT"
        staging.close()


def test_collision_never_overwrites_and_returns_verified_existing_entry(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    identity = _identity()
    with SecureFilesystemPreviewCache(root, max_entries=1) as cache:
        first = cache.begin_write(identity)
        second = cache.begin_write(identity)
        first.output_path.write_bytes(_png(rgb=(1, 2, 3)))
        second.output_path.write_bytes(_png(rgb=(9, 8, 7)))
        with first.publish(width=3, height=2) as winner:
            winner_bytes = winner.read()
        with second.publish(width=3, height=2) as collision:
            assert collision.read() == winner_bytes
        with pytest.raises(PreviewCacheError):
            _ = second.output_path
        second.close()


def test_failures_before_and_after_atomic_publication_leave_no_partial_entry(tmp_path):
    for event in ("before_publish", "after_publish"):
        root = tmp_path / event
        root.mkdir()
        identity = _identity(source=("3" if event == "before_publish" else "4") * 64)

        def fail(observed):
            if observed == event:
                raise OSError("injected private path")

        cache = SecureFilesystemPreviewCache(root, _event_hook=fail)
        staging = cache.begin_write(identity)
        staging.output_path.write_bytes(_png())
        with pytest.raises(PreviewCacheError) as raised:
            staging.publish(width=3, height=2)
        assert raised.value.code == "PREVIEW_INTERNAL_ERROR"
        assert "injected private path" not in raised.value.message
        if event == "before_publish":
            assert cache.lookup(identity) is None
            staging.close()
        else:
            with cache.lookup(identity) as recovered:
                assert recovered.read() == _png()
            staging.close()
        cache.close()


def test_post_publication_sync_failure_is_typed_and_preserves_complete_entry(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    identity = _identity()
    cache = SecureFilesystemPreviewCache(root)
    staging = cache.begin_write(identity)
    staging.output_path.write_bytes(_png())
    original_sync = cache_adapter._fsync_directory
    calls = 0

    def fail_destination_sync(path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(f"private cache path: {root}")
        return original_sync(path)

    monkeypatch.setattr(cache_adapter, "_fsync_directory", fail_destination_sync)
    with pytest.raises(PreviewCacheError) as raised:
        staging.publish(width=3, height=2)
    assert raised.value.code == "PREVIEW_INTERNAL_ERROR"
    assert str(root) not in raised.value.message
    with cache.lookup(identity) as recovered:
        assert recovered.read() == _png()
    staging.close()
    cache.close()


def test_cancelled_publication_is_typed_and_exact_staging_cleanup_is_caller_owned(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    marker = root / "unrelated.txt"
    marker.write_text("preserve", encoding="utf-8")
    identity = _identity()
    event = threading.Event()
    event.set()
    with SecureFilesystemPreviewCache(root) as cache:
        staging = cache.begin_write(identity)
        staging.output_path.write_bytes(_png())
        owned_directory = staging.output_path.parent
        with pytest.raises(PreviewCacheError) as raised:
            staging.publish(width=3, height=2, cancel_event=event)
        assert raised.value.code == "PREVIEW_CANCELLED"
        assert owned_directory.exists()
        staging.close()
        assert not owned_directory.exists()
        assert cache.lookup(identity) is None
    assert marker.read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize("write_partial", [False, True], ids=["empty", "partial-output"])
def test_active_staging_lease_prevents_store_close_and_second_owner(tmp_path, write_partial):
    root = tmp_path / "cache"
    root.mkdir()
    cache = SecureFilesystemPreviewCache(root)
    staging = cache.begin_write(_identity())
    if write_partial:
        staging.output_path.write_bytes(b"partial")

    with pytest.raises(PreviewCacheError, match="active staging") as raised:
        cache.close()
    assert raised.value.code == "PREVIEW_INTERNAL_ERROR"
    with pytest.raises(PreviewCacheError) as second_owner:
        SecureFilesystemPreviewCache(root)
    assert second_owner.value.code == "PREVIEW_INTERNAL_ERROR"
    assert staging.output_path.parent.exists()

    staging.close()
    staging.close()
    cache.close()
    with SecureFilesystemPreviewCache(root):
        pass


def test_staging_publication_releases_store_registration_exactly_once(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    cache = SecureFilesystemPreviewCache(root)
    staging = cache.begin_write(_identity())
    staging.output_path.write_bytes(_png())
    published = staging.publish(width=3, height=2)
    published.close()
    staging.close()
    staging.close()
    cache.close()


def test_startup_removes_only_owned_abandoned_staging(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    with SecureFilesystemPreviewCache(root) as cache:
        abandoned = cache.begin_write(_identity())
        abandoned.output_path.write_bytes(_png())
        abandoned_path = abandoned.output_path.parent
        cache._release_staging(abandoned._directory_identity)
        abandoned._closed = True
        unrelated = root / ".preview-cache-staging" / "do-not-delete"
        unrelated.mkdir()
        marker = unrelated / "marker.txt"
        marker.write_text("preserve", encoding="utf-8")
    with SecureFilesystemPreviewCache(root):
        assert not abandoned_path.exists()
        assert marker.read_text(encoding="utf-8") == "preserve"


def test_pinned_entry_cannot_be_evicted_and_capacity_fails_closed(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    first = _identity(source="3" * 64)
    second = _identity(source="4" * 64)
    with SecureFilesystemPreviewCache(root, max_entries=1) as cache:
        pinned = _publish(cache, first)
        staging = cache.begin_write(second)
        staging.output_path.write_bytes(_png(rgb=(2, 3, 4)))
        with pytest.raises(PreviewCacheError) as raised:
            staging.publish(width=3, height=2)
        assert raised.value.code == "PREVIEW_CAPACITY_EXHAUSTED"
        assert pinned.read() == _png()
        pinned.close()
        staging.close()


def test_concurrent_pin_publication_and_eviction_preserve_pinned_entry(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    first = _identity(source="3" * 64)
    second = _identity(source="4" * 64)
    cache = SecureFilesystemPreviewCache(root, max_entries=1)
    with _publish(cache, first):
        pass

    pinned_barrier = threading.Barrier(2)
    release_barrier = threading.Barrier(2)
    observed = []
    failures = []

    def consume_pinned():
        try:
            with cache.lookup(first) as lease:
                pinned_barrier.wait(timeout=5)
                release_barrier.wait(timeout=5)
                observed.append(lease.read())
        except BaseException as error:
            failures.append(error)

    consumer = threading.Thread(target=consume_pinned)
    consumer.start()
    pinned_barrier.wait(timeout=5)
    blocked = cache.begin_write(second)
    blocked.output_path.write_bytes(_png(rgb=(2, 3, 4)))
    try:
        with pytest.raises(PreviewCacheError) as raised:
            blocked.publish(width=3, height=2)
        assert raised.value.code == "PREVIEW_CAPACITY_EXHAUSTED"
        with cache.lookup(first) as still_present:
            assert still_present.read() == _png()
    finally:
        blocked.close()
        release_barrier.wait(timeout=5)
        consumer.join(timeout=5)

    assert not consumer.is_alive()
    assert not failures
    assert observed == [_png()]
    with _publish(cache, second, _png(rgb=(2, 3, 4))) as replacement:
        assert replacement.read() == _png(rgb=(2, 3, 4))
    assert cache.lookup(first) is None
    cache.close()


def test_single_artifact_over_byte_capacity_is_classified_as_capacity_exhaustion(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    with SecureFilesystemPreviewCache(root, max_bytes=32) as cache:
        staging = cache.begin_write(_identity())
        staging.output_path.write_bytes(_png())
        with pytest.raises(PreviewCacheError) as raised:
            staging.publish(width=3, height=2)
        assert raised.value.code == "PREVIEW_CAPACITY_EXHAUSTED"
        staging.close()


def test_oldest_unpinned_entry_is_evicted_deterministically(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    first = _identity(source="3" * 64)
    second = _identity(source="4" * 64)
    with SecureFilesystemPreviewCache(root, max_entries=1) as cache:
        with _publish(cache, first):
            pass
        with _publish(cache, second):
            pass
        assert cache.lookup(first) is None
        with cache.lookup(second) as hit:
            assert hit.artifact.preview_id == second.preview_id


def test_corruption_discard_is_exact_and_preserves_unrelated_hardlink_target(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    identity = _identity()
    unrelated = tmp_path / "unrelated.png"
    unrelated.write_bytes(_png())
    with SecureFilesystemPreviewCache(root) as cache:
        with _publish(cache, identity):
            pass
        artifact = _entry(root, identity.preview_id) / "preview.png"
        artifact.unlink()
        try:
            os.link(unrelated, artifact)
        except OSError as error:
            pytest.skip(f"Hard links unavailable: {error}")
        with pytest.raises(PreviewCacheError) as raised:
            cache.lookup(identity)
        assert raised.value.code == "PREVIEW_CACHE_CORRUPT"
        assert cache.discard_corrupt(identity)
        assert unrelated.read_bytes() == _png()
        assert not _entry(root, identity.preview_id).exists()


def test_corrupt_entry_with_unknown_material_is_not_deleted(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    identity = _identity()
    with SecureFilesystemPreviewCache(root) as cache:
        with _publish(cache, identity):
            pass
        entry = _entry(root, identity.preview_id)
        marker = entry / "unrelated.txt"
        marker.write_text("preserve", encoding="utf-8")
        with pytest.raises(PreviewCacheError) as raised:
            cache.discard_corrupt(identity)
        assert raised.value.code == "PREVIEW_INTERNAL_ERROR"
        assert marker.read_text(encoding="utf-8") == "preserve"


def test_staging_cleanup_preserves_unknown_material_and_fails_closed(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    cache = SecureFilesystemPreviewCache(root)
    staging = cache.begin_write(_identity())
    marker = staging.output_path.parent / "unrelated.txt"
    marker.write_text("preserve", encoding="utf-8")
    with pytest.raises(PreviewCacheError) as raised:
        staging.close()
    assert raised.value.code == "PREVIEW_INTERNAL_ERROR"
    assert marker.read_text(encoding="utf-8") == "preserve"
    cache.close()


def test_cache_root_is_exclusively_owned_and_unrelated_root_files_survive(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    marker = root / "unrelated.txt"
    marker.write_text("preserve", encoding="utf-8")
    first = SecureFilesystemPreviewCache(root)
    with pytest.raises(PreviewCacheError) as raised:
        SecureFilesystemPreviewCache(root)
    assert raised.value.code == "PREVIEW_INTERNAL_ERROR"
    first.close()
    with SecureFilesystemPreviewCache(root):
        assert marker.read_text(encoding="utf-8") == "preserve"


def test_symlink_cache_root_is_rejected_where_supported(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(actual, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Directory symlink creation unavailable: {error}")
    with pytest.raises(PreviewCacheError) as raised:
        SecureFilesystemPreviewCache(link)
    assert raised.value.code == "PREVIEW_INTERNAL_ERROR"


def test_cache_root_identity_change_is_detected_before_lookup(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    cache = SecureFilesystemPreviewCache(root)
    original_inspect = cache_adapter._inspect_root

    def changed(path):
        record = original_inspect(path)
        if Path(path).absolute() == root.absolute():
            return cache_adapter._RootRecord(
                record.path,
                record.identity[:-1] + (record.identity[-1] + 1,),
                record.final_path,
            )
        return record

    with monkeypatch.context() as context:
        context.setattr(cache_adapter, "_inspect_root", changed)
        with pytest.raises(PreviewCacheError) as raised:
            cache.lookup(_identity())
        assert raised.value.code == "PREVIEW_INTERNAL_ERROR"
        assert str(root) not in raised.value.message
    cache.close()


@pytest.mark.skipif(os.name == "nt", reason="Live open-directory replacement is a POSIX verification")
def test_live_cache_root_replacement_is_detected(tmp_path):
    root = tmp_path / "cache"
    moved = tmp_path / "cache-moved"
    root.mkdir()
    cache = SecureFilesystemPreviewCache(root)
    root.rename(moved)
    root.mkdir()
    try:
        with pytest.raises(PreviewCacheError) as raised:
            cache.lookup(_identity())
        assert raised.value.code == "PREVIEW_INTERNAL_ERROR"
        assert str(root) not in raised.value.message
    finally:
        cache.close()
        root.rmdir()
        moved.rename(root)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_windows_junction_roots_and_managed_directories_are_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "marker.txt"
    marker.write_text("preserve", encoding="utf-8")
    root_junction = tmp_path / "root-junction"
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(root_junction), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"Windows junction creation is unavailable: {result.stderr or result.stdout}")
    try:
        with pytest.raises(PreviewCacheError) as root_error:
            SecureFilesystemPreviewCache(root_junction)
        assert root_error.value.code == "PREVIEW_INTERNAL_ERROR"

        cache_root = tmp_path / "cache"
        cache_root.mkdir()
        entries_junction = cache_root / "entries"
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(entries_junction), str(outside)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip(f"Windows managed-directory junction creation is unavailable: {result.stderr or result.stdout}")
        try:
            with pytest.raises(PreviewCacheError) as entries_error:
                SecureFilesystemPreviewCache(cache_root)
            assert entries_error.value.code == "PREVIEW_INTERNAL_ERROR"
        finally:
            if entries_junction.exists():
                os.rmdir(entries_junction)
        assert marker.read_text(encoding="utf-8") == "preserve"
    finally:
        if root_junction.exists():
            os.rmdir(root_junction)
