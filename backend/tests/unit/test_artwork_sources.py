from __future__ import annotations

import os
import stat
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

import wrld_video_studio.infrastructure.artwork_sources as artwork_sources_module

from wrld_video_studio.application.artwork_sources import AcquireArtworkSource
from wrld_video_studio.application.ports.artwork_sources import (
    ArtworkSourceError,
    ArtworkSourceSnapshot,
)
from wrld_video_studio.domain.preview_cache import PreviewTarget
from wrld_video_studio.infrastructure.artwork_sources import (
    ArtworkSourceRegistration,
    ImmutableArtworkRegistry,
    TrustedArtworkRoot,
)


class _FakeLease:
    snapshot = ArtworkSourceSnapshot("Album", "asset", Path("snapshot.png"), "a" * 64, 4)

    def verify_snapshot(self, cancel_event=None):
        return None

    def revalidate_source(self, cancel_event=None):
        return None

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None


class _FakeResolver:
    def __init__(self):
        self.calls = []

    def acquire(self, album_id, artwork_asset_id, cancel_event=None):
        self.calls.append((album_id, artwork_asset_id, cancel_event))
        return _FakeLease()


def test_acquisition_use_case_passes_only_opaque_composite_identity():
    resolver = _FakeResolver()
    target = PreviewTarget("Album A", "cover_1", track_id="track", short_id="short")

    lease = AcquireArtworkSource(resolver).execute(target, cancel_event="cancel-token")

    assert lease.snapshot.source_sha256 == "a" * 64
    assert resolver.calls == [("Album A", "cover_1", "cancel-token")]


def test_acquisition_use_case_requires_validated_target():
    with pytest.raises(TypeError, match="PreviewTarget"):
        AcquireArtworkSource(_FakeResolver()).execute({"album_id": "Album A"})


def test_registry_is_exact_case_sensitive_and_immutable(tmp_path):
    source_root = tmp_path / "sources"
    source_root.mkdir()
    registry = ImmutableArtworkRegistry(
        [TrustedArtworkRoot("main", source_root)],
        [ArtworkSourceRegistration("Album", "Cover", "main", "art/cover.png")],
    )

    _, registered = registry.lookup("Album", "Cover")
    assert registered.parts == ("art", "cover.png")
    with pytest.raises(ArtworkSourceError) as caught:
        registry.lookup("album", "Cover")
    assert caught.value.code == "PREVIEW_SOURCE_UNAVAILABLE"
    with pytest.raises((FrozenInstanceError, AttributeError)):
        registered.parts = ("other.png",)


@pytest.mark.parametrize(
    "relative_path",
    [
        "../cover.png",
        "art/../cover.png",
        "art/./cover.png",
        "/cover.png",
        "C:/cover.png",
        "file:cover.png",
        "art/file:cover.png",
        "file.png:stream",
        "file::$DATA.png",
        "//server/share/cover.png",
        "art\\cover.png",
        "art//cover.png",
        "cover.gif",
        "",
    ],
)
def test_registry_rejects_untrusted_or_unsupported_relative_paths(tmp_path, relative_path):
    source_root = tmp_path / "sources"
    source_root.mkdir()
    with pytest.raises(ValueError):
        ImmutableArtworkRegistry(
            [TrustedArtworkRoot("main", source_root)],
            [ArtworkSourceRegistration("Album", "cover", "main", relative_path)],
        )


def test_registry_rejects_duplicate_composite_key_and_unknown_root(tmp_path):
    source_root = tmp_path / "sources"
    source_root.mkdir()
    registration = ArtworkSourceRegistration("Album", "cover", "main", "cover.png")
    with pytest.raises(ValueError, match="unique composite"):
        ImmutableArtworkRegistry(
            [TrustedArtworkRoot("main", source_root)],
            [registration, registration],
        )
    with pytest.raises(ValueError, match="unknown trusted root"):
        ImmutableArtworkRegistry(
            [TrustedArtworkRoot("main", source_root)],
            [ArtworkSourceRegistration("Album", "cover", "other", "cover.png")],
        )


def test_registry_accepts_valid_nested_portable_path(tmp_path):
    source_root = tmp_path / "sources"
    source_root.mkdir()
    registry = ImmutableArtworkRegistry(
        [TrustedArtworkRoot("main", source_root)],
        [ArtworkSourceRegistration("Album", "cover", "main", "art/subfolder/cover.PNG")],
    )

    _, registered = registry.lookup("Album", "cover")
    assert registered.parts == ("art", "subfolder", "cover.PNG")
    assert registered.suffix == ".png"


class _FakePosixOs:
    O_RDONLY = 0
    O_NOFOLLOW = 1
    O_CLOEXEC = 2
    O_DIRECTORY = 4
    SEEK_SET = 0

    def __init__(self) -> None:
        self.closed: list[int] = []
        self.opened: list[tuple[object, int | None]] = []

    def open(self, path, _flags, *, dir_fd=None):
        self.opened.append((path, dir_fd))
        if dir_fd is None:
            return 10
        if path == "nested":
            return 11
        if path == "cover.png":
            return 12
        raise AssertionError(f"Unexpected fake open: {path!r}")

    @staticmethod
    def fstat(descriptor):
        if descriptor == 10:
            return SimpleNamespace(st_dev=1, st_ino=10, st_mode=stat.S_IFDIR | 0o700, st_size=0)
        if descriptor == 11:
            return SimpleNamespace(st_dev=1, st_ino=11, st_mode=stat.S_IFDIR | 0o700, st_size=0)
        if descriptor == 12:
            return SimpleNamespace(st_dev=1, st_ino=12, st_mode=stat.S_IFREG | 0o600, st_size=4)
        raise AssertionError(f"Unexpected fake descriptor: {descriptor}")

    def close(self, descriptor):
        self.closed.append(descriptor)

    @staticmethod
    def read(_descriptor, _amount):
        return b""

    @staticmethod
    def lseek(_descriptor, _offset, _origin):
        return 0


@pytest.mark.parametrize(
    ("magic_by_descriptor", "failure_descriptor"),
    [
        ({10: 0xEF53, 11: 0x6969, 12: 0xEF53}, None),
        ({10: 0xEF53, 11: 0xEF53, 12: 0xFF534D42}, None),
        ({10: 0xEF53, 11: 0xEF53, 12: 0x65735546}, None),
        ({10: 0xEF53, 11: 0xEF53, 12: 0xDEADBEEF}, None),
        ({10: 0xEF53, 11: 0xEF53, 12: 0xEF53}, 11),
    ],
)
def test_posix_descriptor_locality_rejects_network_unknown_and_failures(
    monkeypatch,
    magic_by_descriptor,
    failure_descriptor,
):
    fake_os = _FakePosixOs()
    monkeypatch.setattr(artwork_sources_module, "os", fake_os)
    monkeypatch.setattr(artwork_sources_module.sys, "platform", "linux")

    def filesystem_magic(descriptor):
        if descriptor == failure_descriptor:
            raise OSError("simulated fstatfs failure")
        return magic_by_descriptor[descriptor]

    monkeypatch.setattr(artwork_sources_module, "_linux_filesystem_magic_fd", filesystem_magic)
    root = artwork_sources_module._RootRecord(Path("/trusted"), (1, 10), "/trusted")
    source = artwork_sources_module._RegisteredSource(
        "main", ("nested", "cover.png"), ".png"
    )

    with pytest.raises(OSError, match="filesystem|fstatfs"):
        artwork_sources_module._open_posix_source(root, source)

    expected_closed = (
        {10, 11}
        if magic_by_descriptor[11] != 0xEF53 or failure_descriptor == 11
        else {10, 11, 12}
    )
    assert set(fake_os.closed) == expected_closed


def test_posix_descriptor_locality_accepts_local_root_parent_and_leaf(monkeypatch):
    fake_os = _FakePosixOs()
    monkeypatch.setattr(artwork_sources_module, "os", fake_os)
    monkeypatch.setattr(artwork_sources_module.sys, "platform", "linux")
    monkeypatch.setattr(
        artwork_sources_module,
        "_linux_filesystem_magic_fd",
        lambda descriptor: {10: 0xEF53, 11: 0x794C7630, 12: 0x01021994}[descriptor],
    )
    root = artwork_sources_module._RootRecord(Path("/trusted"), (1, 10), "/trusted")
    source = artwork_sources_module._RegisteredSource(
        "main", ("nested", "cover.png"), ".png"
    )

    opened = artwork_sources_module._open_posix_source(root, source)

    assert fake_os.closed == [11, 10]
    opened.close()
    assert fake_os.closed == [11, 10, 12]


def test_snapshot_value_is_frozen():
    snapshot = ArtworkSourceSnapshot("Album", "cover", Path("source.png"), "a" * 64, 1)
    with pytest.raises(FrozenInstanceError):
        snapshot.source_sha256 = "b" * 64


def test_artwork_source_errors_reuse_preview_codes_only():
    assert ArtworkSourceError("SOURCE_CHANGED", "changed").code == "SOURCE_CHANGED"
    with pytest.raises(ValueError, match="approved preview"):
        ArtworkSourceError("ARBITRARY_NEW_CODE", "bad")
