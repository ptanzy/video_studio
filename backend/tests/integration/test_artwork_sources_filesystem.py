from __future__ import annotations

import hashlib
import os
import stat
import struct
import subprocess
import threading
import zlib
from pathlib import Path

import pytest

import wrld_video_studio.infrastructure.artwork_sources as artwork_sources_module

from wrld_video_studio.application.ports.artwork_sources import ArtworkSourceError
from wrld_video_studio.application.ports.still_images import (
    STILL_RENDER_REQUEST_VERSION,
    STILL_RENDERER_VERSION,
    StillRenderRequest,
)
from wrld_video_studio.domain.color_resolution import resolve_color_treatment
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.infrastructure.artwork_sources import (
    MAX_ARTWORK_SOURCE_BYTES,
    ArtworkSourceRegistration,
    ImmutableArtworkRegistry,
    SecureFilesystemArtworkSourceResolver,
    TrustedArtworkRoot,
)
from wrld_video_studio.infrastructure.media_tools import MediaToolchain
from wrld_video_studio.infrastructure.process_runner import SubprocessRunner
from wrld_video_studio.infrastructure.still_image_renderer import FFmpegStillImageRenderer
from wrld_video_studio.infrastructure.still_image_renderer import MAX_INPUT_BYTES


def _resolver(tmp_path, data=b"source-bytes", *, hook=None, relative_path="nested/cover.png"):
    source_root = tmp_path / "source-root"
    snapshot_root = tmp_path / "snapshot-root"
    source_path = source_root / Path(relative_path)
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(data)
    snapshot_root.mkdir()
    registry = ImmutableArtworkRegistry(
        [TrustedArtworkRoot("main", source_root)],
        [ArtworkSourceRegistration("Album", "cover", "main", relative_path.replace("\\", "/"))],
    )
    return (
        SecureFilesystemArtworkSourceResolver(registry, snapshot_root, _event_hook=hook),
        source_path,
        snapshot_root,
    )


def _assert_empty(directory):
    assert list(directory.iterdir()) == []


def _png_chunk(name: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + name
        + data
        + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
    )


def _valid_rgba_png_bytes() -> bytes:
    header = struct.pack(">IIBBBBB", 2, 1, 8, 6, 0, 0, 0)
    pixels = b"\x00\x10\x80\xff\xff\xe0\x20\x1a\x7f"
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(pixels, level=9))
        + _png_chunk(b"IEND", b"")
    )


def _renderer_or_skip(tmp_path):
    runner = SubprocessRunner()
    toolchain = MediaToolchain(runner)
    try:
        toolchain.resolve("ffmpeg")
        toolchain.resolve("ffprobe")
    except MediaInfrastructureError as error:
        if error.code == "MEDIA_TOOL_MISSING":
            pytest.skip(f"FFmpeg still-render tools unavailable: {error.code}: {error.message}")
        raise
    return FFmpegStillImageRenderer(toolchain, runner, tmp_path / "outputs")


def test_acquires_private_verified_snapshot_and_cleans_exact_lease(tmp_path):
    resolver, source_path, snapshot_root = _resolver(tmp_path, b"immutable-source")
    original = source_path.read_bytes()

    with resolver.acquire("Album", "cover") as lease:
        snapshot = lease.snapshot
        assert snapshot.snapshot_path.parent.parent == snapshot_root
        assert snapshot.snapshot_path.suffix == ".png"
        assert snapshot.snapshot_path.read_bytes() == original
        assert snapshot.source_sha256 == hashlib.sha256(original).hexdigest()
        assert snapshot.byte_size == len(original)
        assert not os.access(snapshot.snapshot_path, os.W_OK) or os.name == "nt"
        lease.verify_snapshot()
        lease.revalidate_source()
        owned_directory = snapshot.snapshot_path.parent

    assert source_path.read_bytes() == original
    assert not owned_directory.exists()
    _assert_empty(snapshot_root)


def test_binary_snapshot_is_physically_identical_on_windows_and_posix(tmp_path):
    binary = b"prefix\ncrlf\r\nctrl-z\x1a\x00\x80\xffsuffix"
    resolver, source_path, snapshot_root = _resolver(tmp_path, binary)

    with resolver.acquire("Album", "cover") as lease:
        assert lease.snapshot.snapshot_path.read_bytes() == binary
        assert lease.snapshot.source_sha256 == hashlib.sha256(binary).hexdigest()
        assert lease.snapshot.byte_size == len(binary)
        lease.verify_snapshot()

    assert source_path.read_bytes() == binary
    _assert_empty(snapshot_root)


@pytest.mark.integration_ffmpeg
def test_phase2_renderer_consumes_valid_acquired_png_and_matches_lease_hash(tmp_path):
    source_bytes = _valid_rgba_png_bytes()
    resolver, source_path, snapshot_root = _resolver(tmp_path, source_bytes)
    renderer = _renderer_or_skip(tmp_path)
    resolution = resolve_color_treatment(
        {"contract_version": "color-resolution-input-v1", "treatment": {"mode": "auto", "intensity": 0.0}}
    )
    with resolver.acquire("Album", "cover") as lease:
        result = renderer.render(
            StillRenderRequest(
                contract_version=STILL_RENDER_REQUEST_VERSION,
                source_path=lease.snapshot.snapshot_path,
                output_relative_path="preview.png",
                resolution=resolution,
                renderer_version=STILL_RENDERER_VERSION,
            )
        )
        assert result.artifact_path.is_file()
        assert result.source_sha256 == lease.snapshot.source_sha256
        assert lease.snapshot.snapshot_path.read_bytes() == source_bytes
        owned_directory = lease.snapshot.snapshot_path.parent

    assert source_path.read_bytes() == source_bytes
    assert not owned_directory.exists()
    _assert_empty(snapshot_root)
    assert MAX_ARTWORK_SOURCE_BYTES == MAX_INPUT_BYTES


def test_missing_unregistered_directory_and_non_regular_sources_are_path_safe(tmp_path):
    resolver, source_path, snapshot_root = _resolver(tmp_path)
    with pytest.raises(ArtworkSourceError) as missing_key:
        resolver.acquire("Album", "missing")
    assert missing_key.value.code == "PREVIEW_SOURCE_UNAVAILABLE"

    source_path.unlink()
    source_path.mkdir()
    with pytest.raises(ArtworkSourceError) as non_regular:
        resolver.acquire("Album", "cover")
    assert non_regular.value.code == "PREVIEW_SOURCE_UNAVAILABLE"
    assert str(source_path) not in str(non_regular.value)
    _assert_empty(snapshot_root)


def test_source_replacement_during_acquisition_is_detected_and_cleaned(tmp_path):
    holder = {}

    def hook(stage):
        if stage == "before_revalidate":
            path = holder["path"]
            replacement = path.with_name("replacement.png")
            replacement.write_bytes(b"replacement")
            path.unlink()
            replacement.replace(path)

    resolver, source_path, snapshot_root = _resolver(tmp_path, b"original", hook=hook)
    holder["path"] = source_path
    with pytest.raises(ArtworkSourceError) as caught:
        resolver.acquire("Album", "cover")
    assert caught.value.code == "SOURCE_CHANGED"
    _assert_empty(snapshot_root)


def test_mid_acquisition_mutation_is_detected_or_prevented_by_open_handle(tmp_path):
    state = {"path": None, "attempted": False, "blocked": False}

    def hook(stage):
        if stage == "source_chunk_copied" and not state["attempted"]:
            state["attempted"] = True
            try:
                state["path"].write_bytes(b"mutated-during-acquisition")
            except OSError:
                state["blocked"] = True

    resolver, source_path, snapshot_root = _resolver(tmp_path, b"original", hook=hook)
    state["path"] = source_path
    if os.name == "nt":
        with resolver.acquire("Album", "cover") as lease:
            assert state == {"path": source_path, "attempted": True, "blocked": True}
            assert lease.snapshot.snapshot_path.read_bytes() == b"original"
    else:
        with pytest.raises(ArtworkSourceError) as caught:
            resolver.acquire("Album", "cover")
        assert caught.value.code == "SOURCE_CHANGED"
        assert state["attempted"] and not state["blocked"]
    _assert_empty(snapshot_root)


def test_source_mutation_after_acquisition_is_detected(tmp_path):
    resolver, source_path, snapshot_root = _resolver(tmp_path, b"original")
    lease = resolver.acquire("Album", "cover")
    source_path.write_bytes(b"modified")
    with pytest.raises(ArtworkSourceError) as caught:
        lease.revalidate_source()
    assert caught.value.code == "SOURCE_CHANGED"
    lease.close()
    _assert_empty(snapshot_root)


def test_same_content_source_replacement_is_detected_by_file_identity(tmp_path):
    resolver, source_path, snapshot_root = _resolver(tmp_path, b"same-content")
    lease = resolver.acquire("Album", "cover")
    replacement = source_path.with_name("replacement.png")
    replacement.write_bytes(b"same-content")
    source_path.unlink()
    replacement.replace(source_path)
    with pytest.raises(ArtworkSourceError) as caught:
        lease.revalidate_source()
    assert caught.value.code == "SOURCE_CHANGED"
    lease.close()
    _assert_empty(snapshot_root)


def test_snapshot_tampering_is_detected_before_consumption(tmp_path):
    resolver, _, snapshot_root = _resolver(tmp_path, b"original")
    lease = resolver.acquire("Album", "cover")
    lease.snapshot.snapshot_path.chmod(stat.S_IREAD | stat.S_IWRITE)
    lease.snapshot.snapshot_path.write_bytes(b"forged")
    with pytest.raises(ArtworkSourceError) as caught:
        lease.verify_snapshot()
    assert caught.value.code == "PREVIEW_INTERNAL_ERROR"
    lease.close()
    _assert_empty(snapshot_root)


def test_cleanup_does_not_follow_substituted_symlink_to_read_only_target(tmp_path):
    resolver, _, snapshot_root = _resolver(tmp_path / "lease", b"original")
    lease = resolver.acquire("Album", "cover")
    snapshot_path = lease.snapshot.snapshot_path
    unrelated = tmp_path / "unrelated.bin"
    unrelated.write_bytes(b"unrelated")
    unrelated.chmod(stat.S_IREAD)
    before_mode = stat.S_IMODE(unrelated.stat().st_mode)
    before_attributes = getattr(unrelated.stat(), "st_file_attributes", None)

    snapshot_path.chmod(stat.S_IREAD | stat.S_IWRITE)
    snapshot_path.unlink()
    try:
        snapshot_path.symlink_to(unrelated)
    except OSError as error:
        lease.close()
        unrelated.chmod(stat.S_IREAD | stat.S_IWRITE)
        pytest.skip(f"This host does not permit unprivileged symlink creation: {error}")

    try:
        with pytest.raises(ArtworkSourceError) as caught:
            lease.close()
        assert caught.value.code == "PREVIEW_INTERNAL_ERROR"
        assert unrelated.read_bytes() == b"unrelated"
        assert stat.S_IMODE(unrelated.stat().st_mode) == before_mode
        assert getattr(unrelated.stat(), "st_file_attributes", None) == before_attributes
    finally:
        snapshot_path.unlink(missing_ok=True)
        unrelated.chmod(stat.S_IREAD | stat.S_IWRITE)
    lease.close()
    _assert_empty(snapshot_root)


def test_cleanup_rejects_hard_link_substitution_without_mutating_target(tmp_path):
    resolver, _, snapshot_root = _resolver(tmp_path / "lease", b"original")
    lease = resolver.acquire("Album", "cover")
    snapshot_path = lease.snapshot.snapshot_path
    unrelated = tmp_path / "unrelated.bin"
    unrelated.write_bytes(b"unrelated-hard-link-target")
    unrelated.chmod(stat.S_IREAD)
    before_mode = stat.S_IMODE(unrelated.stat().st_mode)
    before_attributes = getattr(unrelated.stat(), "st_file_attributes", None)

    snapshot_path.chmod(stat.S_IREAD | stat.S_IWRITE)
    snapshot_path.unlink()
    try:
        os.link(unrelated, snapshot_path)
    except OSError as error:
        lease.close()
        unrelated.chmod(stat.S_IREAD | stat.S_IWRITE)
        pytest.skip(f"This filesystem does not permit hard-link creation: {error}")

    try:
        with pytest.raises(ArtworkSourceError) as caught:
            lease.close()
        assert caught.value.code == "PREVIEW_INTERNAL_ERROR"
        assert unrelated.read_bytes() == b"unrelated-hard-link-target"
        assert stat.S_IMODE(unrelated.stat().st_mode) == before_mode
        assert getattr(unrelated.stat(), "st_file_attributes", None) == before_attributes
    finally:
        unrelated.chmod(stat.S_IREAD | stat.S_IWRITE)
        snapshot_path.unlink(missing_ok=True)
    lease.close()
    _assert_empty(snapshot_root)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_cleanup_rejects_substituted_windows_junction(tmp_path):
    resolver, _, snapshot_root = _resolver(tmp_path / "lease", b"original")
    lease = resolver.acquire("Album", "cover")
    snapshot_path = lease.snapshot.snapshot_path
    unrelated = tmp_path / "unrelated-directory"
    unrelated.mkdir()
    marker = unrelated / "marker.bin"
    marker.write_bytes(b"unchanged")

    snapshot_path.chmod(stat.S_IREAD | stat.S_IWRITE)
    snapshot_path.unlink()
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(snapshot_path), str(unrelated)],
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if result.returncode != 0:
        lease.close()
        pytest.skip(f"Windows junction creation is unavailable: {result.stderr or result.stdout}")

    try:
        with pytest.raises(ArtworkSourceError) as caught:
            lease.close()
        assert caught.value.code == "PREVIEW_INTERNAL_ERROR"
        assert marker.read_bytes() == b"unchanged"
    finally:
        os.rmdir(snapshot_path)
    lease.close()
    _assert_empty(snapshot_root)


def test_precancel_and_mid_copy_cancellation_remove_owned_state(tmp_path):
    cancelled = threading.Event()
    cancelled.set()
    resolver, _, snapshot_root = _resolver(tmp_path / "pre", b"source")
    with pytest.raises(ArtworkSourceError) as caught:
        resolver.acquire("Album", "cover", cancelled)
    assert caught.value.code == "PREVIEW_CANCELLED"
    _assert_empty(snapshot_root)

    mid_cancelled = threading.Event()

    def hook(stage):
        if stage == "source_chunk_copied":
            mid_cancelled.set()

    resolver, _, snapshot_root = _resolver(
        tmp_path / "mid", b"a" * (1024 * 1024 + 1), hook=hook
    )
    with pytest.raises(ArtworkSourceError) as caught:
        resolver.acquire("Album", "cover", mid_cancelled)
    assert caught.value.code == "PREVIEW_CANCELLED"
    _assert_empty(snapshot_root)


def test_oversized_source_is_rejected_without_snapshot_residue(tmp_path):
    resolver, source_path, snapshot_root = _resolver(tmp_path, b"x")
    with source_path.open("r+b") as stream:
        stream.truncate(MAX_ARTWORK_SOURCE_BYTES + 1)
    with pytest.raises(ArtworkSourceError) as caught:
        resolver.acquire("Album", "cover")
    assert caught.value.code == "PREVIEW_IMAGE_UNSUPPORTED"
    _assert_empty(snapshot_root)


def test_snapshot_storage_failure_is_internal_and_cleans_partial_file(monkeypatch, tmp_path):
    resolver, _, snapshot_root = _resolver(tmp_path, b"source")

    def fail_write(_descriptor, _data):
        raise OSError("simulated snapshot storage failure")

    monkeypatch.setattr(artwork_sources_module.os, "write", fail_write)
    with pytest.raises(ArtworkSourceError) as caught:
        resolver.acquire("Album", "cover")
    assert caught.value.code == "PREVIEW_INTERNAL_ERROR"
    _assert_empty(snapshot_root)


def test_each_lease_owns_and_cleans_only_its_snapshot(tmp_path):
    resolver, _, snapshot_root = _resolver(tmp_path, b"shared-source")
    first = resolver.acquire("Album", "cover")
    second = resolver.acquire("Album", "cover")
    assert first.snapshot.snapshot_path != second.snapshot.snapshot_path
    first_directory = first.snapshot.snapshot_path.parent
    first.close()
    assert not first_directory.exists()
    assert second.snapshot.snapshot_path.is_file()
    second.verify_snapshot()
    second.close()
    second.close()
    _assert_empty(snapshot_root)


def test_transient_cleanup_failure_is_reported_and_can_be_retried(monkeypatch, tmp_path):
    resolver, _, snapshot_root = _resolver(tmp_path, b"source")
    lease = resolver.acquire("Album", "cover")
    owned_directory = lease.snapshot.snapshot_path.parent
    original_rmdir = Path.rmdir
    failed_once = False

    def fail_once(path):
        nonlocal failed_once
        if path == owned_directory and not failed_once:
            failed_once = True
            raise OSError("simulated transient cleanup failure")
        return original_rmdir(path)

    monkeypatch.setattr(Path, "rmdir", fail_once)
    with pytest.raises(ArtworkSourceError) as caught:
        lease.close()
    assert caught.value.code == "PREVIEW_INTERNAL_ERROR"
    assert owned_directory.is_dir()
    lease.close()
    lease.close()
    _assert_empty(snapshot_root)


def test_separate_non_overlapping_snapshot_root_is_required(tmp_path):
    source_root = tmp_path / "root"
    source_root.mkdir()
    registry = ImmutableArtworkRegistry([TrustedArtworkRoot("main", source_root)], [])
    with pytest.raises(ValueError, match="separate"):
        SecureFilesystemArtworkSourceResolver(registry, source_root)
    nested = source_root / "snapshots"
    nested.mkdir()
    with pytest.raises(ValueError, match="overlap"):
        SecureFilesystemArtworkSourceResolver(registry, nested)


def test_snapshot_root_ordinary_replacement_and_disappearance_are_rejected(tmp_path):
    resolver, _, snapshot_root = _resolver(tmp_path / "replacement", b"source")
    original_root = snapshot_root.with_name("snapshot-root-original")
    snapshot_root.rename(original_root)
    snapshot_root.mkdir()

    with pytest.raises(ArtworkSourceError) as replaced:
        resolver.acquire("Album", "cover")
    assert replaced.value.code == "PREVIEW_INTERNAL_ERROR"
    _assert_empty(snapshot_root)
    _assert_empty(original_root)

    resolver, _, snapshot_root = _resolver(tmp_path / "missing", b"source")
    snapshot_root.rmdir()
    with pytest.raises(ArtworkSourceError) as missing:
        resolver.acquire("Album", "cover")
    assert missing.value.code == "PREVIEW_INTERNAL_ERROR"
    assert not snapshot_root.exists()


def test_snapshot_root_symlink_replacement_is_rejected_when_supported(tmp_path):
    resolver, _, snapshot_root = _resolver(tmp_path / "lease", b"source")
    original_root = snapshot_root.with_name("snapshot-root-original")
    redirected = tmp_path / "redirected"
    redirected.mkdir()
    snapshot_root.rename(original_root)
    try:
        snapshot_root.symlink_to(redirected, target_is_directory=True)
    except OSError as error:
        original_root.rename(snapshot_root)
        pytest.skip(f"This host does not permit unprivileged symlink creation: {error}")

    with pytest.raises(ArtworkSourceError) as caught:
        resolver.acquire("Album", "cover")
    assert caught.value.code == "PREVIEW_INTERNAL_ERROR"
    _assert_empty(redirected)
    _assert_empty(original_root)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_snapshot_root_junction_replacement_is_rejected(tmp_path):
    resolver, _, snapshot_root = _resolver(tmp_path / "lease", b"source")
    original_root = snapshot_root.with_name("snapshot-root-original")
    redirected = tmp_path / "redirected"
    redirected.mkdir()
    snapshot_root.rename(original_root)
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(snapshot_root), str(redirected)],
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if result.returncode != 0:
        original_root.rename(snapshot_root)
        pytest.skip(f"Windows junction creation is unavailable: {result.stderr or result.stdout}")
    try:
        with pytest.raises(ArtworkSourceError) as caught:
            resolver.acquire("Album", "cover")
        assert caught.value.code == "PREVIEW_INTERNAL_ERROR"
        _assert_empty(redirected)
        _assert_empty(original_root)
    finally:
        os.rmdir(snapshot_root)


def test_snapshot_root_locality_change_fails_closed(monkeypatch, tmp_path):
    resolver, _, snapshot_root = _resolver(tmp_path, b"source")
    original_inspect = artwork_sources_module._inspect_root

    def changed_locality(path):
        if Path(path) == snapshot_root:
            raise ValueError("Trusted artwork roots must use a local filesystem.")
        return original_inspect(path)

    monkeypatch.setattr(artwork_sources_module, "_inspect_root", changed_locality)
    with pytest.raises(ArtworkSourceError) as caught:
        resolver.acquire("Album", "cover")
    assert caught.value.code == "PREVIEW_INTERNAL_ERROR"
    _assert_empty(snapshot_root)


def test_snapshot_root_oserror_before_creation_is_internal_and_path_safe(monkeypatch, tmp_path):
    resolver, _, snapshot_root = _resolver(tmp_path, b"source")
    unrelated = tmp_path / "unrelated.bin"
    unrelated.write_bytes(b"unchanged")
    original_inspect = artwork_sources_module._inspect_root

    def unavailable_root(path):
        if Path(path) == snapshot_root:
            raise OSError(f"simulated private path failure: {snapshot_root}")
        return original_inspect(path)

    monkeypatch.setattr(artwork_sources_module, "_inspect_root", unavailable_root)
    with pytest.raises(ArtworkSourceError) as caught:
        resolver.acquire("Album", "cover")
    assert caught.value.code == "PREVIEW_INTERNAL_ERROR"
    assert str(snapshot_root) not in str(caught.value)
    assert unrelated.read_bytes() == b"unchanged"
    _assert_empty(snapshot_root)


def test_snapshot_root_is_rechecked_after_request_directory_creation(monkeypatch, tmp_path):
    resolver, _, snapshot_root = _resolver(tmp_path, b"source")
    original_inspect = artwork_sources_module._inspect_root
    inspections = 0

    def fail_second_inspection(path):
        nonlocal inspections
        if Path(path) == snapshot_root:
            inspections += 1
            if inspections == 2:
                raise ValueError("simulated post-creation root replacement")
        return original_inspect(path)

    monkeypatch.setattr(artwork_sources_module, "_inspect_root", fail_second_inspection)
    with pytest.raises(ArtworkSourceError) as caught:
        resolver.acquire("Album", "cover")
    assert caught.value.code == "PREVIEW_INTERNAL_ERROR"
    assert inspections == 2
    _assert_empty(snapshot_root)


def test_snapshot_root_oserror_after_creation_cleans_owned_state(monkeypatch, tmp_path):
    resolver, _, snapshot_root = _resolver(tmp_path, b"source")
    unrelated = tmp_path / "unrelated.bin"
    unrelated.write_bytes(b"unchanged")
    original_inspect = artwork_sources_module._inspect_root
    inspections = 0

    def fail_second_inspection(path):
        nonlocal inspections
        if Path(path) == snapshot_root:
            inspections += 1
            if inspections == 2:
                raise OSError(f"simulated private path failure: {snapshot_root}")
        return original_inspect(path)

    monkeypatch.setattr(artwork_sources_module, "_inspect_root", fail_second_inspection)
    with pytest.raises(ArtworkSourceError) as caught:
        resolver.acquire("Album", "cover")
    assert caught.value.code == "PREVIEW_INTERNAL_ERROR"
    assert str(snapshot_root) not in str(caught.value)
    assert inspections == 2
    assert unrelated.read_bytes() == b"unchanged"
    _assert_empty(snapshot_root)


def test_symlink_leaf_and_intermediate_are_rejected_when_supported(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "cover.png").write_bytes(b"outside")

    source_root = tmp_path / "sources"
    snapshot_root = tmp_path / "snapshots"
    source_root.mkdir()
    snapshot_root.mkdir()
    try:
        (source_root / "linked.png").symlink_to(outside / "cover.png")
        (source_root / "linked-dir").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"This host does not permit unprivileged symlink creation: {error}")

    for asset_id, relative_path in (("leaf", "linked.png"), ("parent", "linked-dir/cover.png")):
        registry = ImmutableArtworkRegistry(
            [TrustedArtworkRoot("main", source_root)],
            [ArtworkSourceRegistration("Album", asset_id, "main", relative_path)],
        )
        resolver = SecureFilesystemArtworkSourceResolver(registry, snapshot_root)
        with pytest.raises(ArtworkSourceError) as caught:
            resolver.acquire("Album", asset_id)
        assert caught.value.code == "PREVIEW_SOURCE_UNAVAILABLE"
    _assert_empty(snapshot_root)


def test_symlink_trusted_root_is_rejected_when_supported(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(actual, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"This host does not permit unprivileged symlink creation: {error}")
    with pytest.raises(ValueError, match="reparse|symlink"):
        ImmutableArtworkRegistry([TrustedArtworkRoot("main", linked)], [])


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_windows_junction_intermediate_and_trusted_root_are_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "cover.png").write_bytes(b"outside")
    source_root = tmp_path / "sources"
    snapshot_root = tmp_path / "snapshots"
    source_root.mkdir()
    snapshot_root.mkdir()
    junction = source_root / "junction"
    leaf_junction = source_root / "linked.png"
    root_junction = tmp_path / "root-junction"
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for link, target in (
        (junction, outside),
        (leaf_junction, outside),
        (root_junction, source_root),
    ):
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            creationflags=creation_flags,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip(f"Windows junction creation is unavailable: {result.stderr or result.stdout}")
    try:
        registry = ImmutableArtworkRegistry(
            [TrustedArtworkRoot("main", source_root)],
            [
                ArtworkSourceRegistration("Album", "parent", "main", "junction/cover.png"),
                ArtworkSourceRegistration("Album", "leaf", "main", "linked.png"),
            ],
        )
        resolver = SecureFilesystemArtworkSourceResolver(registry, snapshot_root)
        for asset_id in ("parent", "leaf"):
            with pytest.raises(ArtworkSourceError) as caught:
                resolver.acquire("Album", asset_id)
            assert caught.value.code == "PREVIEW_SOURCE_UNAVAILABLE"
        with pytest.raises(ValueError, match="reparse"):
            ImmutableArtworkRegistry([TrustedArtworkRoot("main", root_junction)], [])
    finally:
        if junction.exists():
            os.rmdir(junction)
        if leaf_junction.exists():
            os.rmdir(leaf_junction)
        if root_junction.exists():
            os.rmdir(root_junction)


@pytest.mark.skipif(os.name != "nt", reason="Windows drive classification")
def test_windows_remote_drive_root_is_rejected(monkeypatch, tmp_path):
    import win32con
    import win32file

    source_root = tmp_path / "sources"
    source_root.mkdir()
    monkeypatch.setattr(win32file, "GetDriveType", lambda _path: win32con.DRIVE_REMOTE)
    with pytest.raises(ValueError, match="local filesystem"):
        ImmutableArtworkRegistry([TrustedArtworkRoot("main", source_root)], [])


@pytest.mark.skipif(os.name != "nt", reason="Windows UNC path behavior")
def test_windows_unc_root_is_rejected_before_volume_access(monkeypatch):
    import win32file

    def unexpected_volume_access(_path):
        raise AssertionError("UNC roots must fail before volume access")

    monkeypatch.setattr(win32file, "GetVolumePathName", unexpected_volume_access)
    with pytest.raises(ValueError, match="local filesystem"):
        ImmutableArtworkRegistry(
            [TrustedArtworkRoot("remote", Path(r"\\server\share\artwork"))],
            [],
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows drive classification")
@pytest.mark.parametrize("drive_type_name", ["DRIVE_UNKNOWN", "DRIVE_NO_ROOT_DIR"])
def test_windows_unknown_drive_classes_fail_closed(monkeypatch, tmp_path, drive_type_name):
    import win32con
    import win32file

    source_root = tmp_path / "sources"
    source_root.mkdir()
    monkeypatch.setattr(
        win32file,
        "GetDriveType",
        lambda _path: getattr(win32con, drive_type_name),
    )
    with pytest.raises(ValueError, match="local filesystem"):
        ImmutableArtworkRegistry([TrustedArtworkRoot("main", source_root)], [])


def test_linux_network_and_unknown_filesystem_types_fail_closed(monkeypatch, tmp_path):
    source_root = tmp_path / "sources"
    source_root.mkdir()
    monkeypatch.setattr(artwork_sources_module.sys, "platform", "linux")
    for filesystem_magic in (0x6969, 0xFF534D42, 0xFE534D42, 0x65735546, 0xDEADBEEF):
        monkeypatch.setattr(
            artwork_sources_module,
            "_linux_filesystem_magic",
            lambda _path, value=filesystem_magic: value,
        )
        with pytest.raises(ValueError, match="supported local filesystem"):
            artwork_sources_module._validate_posix_local_filesystem(source_root)

    monkeypatch.setattr(
        artwork_sources_module,
        "_linux_filesystem_magic",
        lambda _path: 0xEF53,
    )
    artwork_sources_module._validate_posix_local_filesystem(source_root)
