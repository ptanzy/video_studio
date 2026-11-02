from __future__ import annotations

import hashlib
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

from wrld_video_studio.application.ports.artwork_sources import (
    ArtworkSourceError,
    ArtworkSourceLease,
    ArtworkSourceResolver,
    ArtworkSourceSnapshot,
)
from wrld_video_studio.domain.preview_cache import PreviewTarget


MAX_ARTWORK_SOURCE_BYTES = 40 * 1024 * 1024
SUPPORTED_ARTWORK_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
_ROOT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_COPY_CHUNK_BYTES = 1024 * 1024
_BINARY_OPEN_FLAG = getattr(os, "O_BINARY", 0)
_LINUX_LOCAL_FILESYSTEMS = MappingProxyType(
    {
        0xEF53: "ext2/ext3/ext4",
        0x58465342: "xfs",
        0x9123683E: "btrfs",
        0x01021994: "tmpfs",
        0x794C7630: "overlayfs",
        0x2FC12FC1: "zfs",
        0xF2F52010: "f2fs",
        0x3153464A: "jfs",
        0x52654973: "reiserfs",
        0x3434: "nilfs",
        0x24051905: "ubifs",
        0x858458F6: "ramfs",
    }
)


@dataclass(frozen=True, slots=True)
class TrustedArtworkRoot:
    root_id: str
    path: Path


@dataclass(frozen=True, slots=True)
class ArtworkSourceRegistration:
    album_id: str
    artwork_asset_id: str
    root_id: str
    relative_path: str


@dataclass(frozen=True, slots=True)
class _RegisteredSource:
    root_id: str
    parts: tuple[str, ...]
    suffix: str


@dataclass(frozen=True, slots=True)
class _RootRecord:
    path: Path
    identity: tuple[int, ...]
    final_path: str | None


class ImmutableArtworkRegistry:
    """Server-built exact lookup from opaque target identity to trusted relative source."""

    def __init__(
        self,
        roots: Iterable[TrustedArtworkRoot],
        registrations: Iterable[ArtworkSourceRegistration],
    ) -> None:
        root_records: dict[str, _RootRecord] = {}
        identities: set[tuple[int, ...]] = set()
        for root in roots:
            if not isinstance(root, TrustedArtworkRoot):
                raise TypeError("Trusted artwork roots must use TrustedArtworkRoot values.")
            if not _ROOT_ID_PATTERN.fullmatch(root.root_id):
                raise ValueError("Trusted artwork root IDs must be opaque ASCII identifiers.")
            if root.root_id in root_records:
                raise ValueError("Trusted artwork root IDs must be unique.")
            record = _inspect_root(root.path)
            if record.identity in identities:
                raise ValueError("Trusted artwork roots must identify distinct directories.")
            identities.add(record.identity)
            root_records[root.root_id] = record
        if not root_records:
            raise ValueError("At least one trusted artwork root is required.")

        entries: dict[tuple[str, str], _RegisteredSource] = {}
        for registration in registrations:
            if not isinstance(registration, ArtworkSourceRegistration):
                raise TypeError("Artwork registrations must use ArtworkSourceRegistration values.")
            PreviewTarget(
                album_id=registration.album_id,
                artwork_asset_id=registration.artwork_asset_id,
            )
            if registration.root_id not in root_records:
                raise ValueError("Artwork registration references an unknown trusted root.")
            parts, suffix = _validate_relative_source(registration.relative_path)
            key = (registration.album_id, registration.artwork_asset_id)
            if key in entries:
                raise ValueError("Artwork registrations must have unique composite keys.")
            entries[key] = _RegisteredSource(registration.root_id, parts, suffix)
        self._roots: Mapping[str, _RootRecord] = MappingProxyType(root_records)
        self._entries: Mapping[tuple[str, str], _RegisteredSource] = MappingProxyType(entries)

    def lookup(self, album_id: str, artwork_asset_id: str) -> tuple[_RootRecord, _RegisteredSource]:
        try:
            entry = self._entries[(album_id, artwork_asset_id)]
        except KeyError as error:
            raise ArtworkSourceError(
                "PREVIEW_SOURCE_UNAVAILABLE", "The requested artwork source is unavailable."
            ) from error
        return self._roots[entry.root_id], entry

    @property
    def roots(self) -> tuple[Path, ...]:
        return tuple(record.path for record in self._roots.values())


@dataclass(slots=True)
class _OpenedSource:
    handle: Any
    identity: tuple[int, ...]
    size: int
    read: Callable[[int], bytes]
    rewind: Callable[[], None]
    close: Callable[[], None]


class _FilesystemArtworkSourceLease(ArtworkSourceLease):
    def __init__(
        self,
        resolver: SecureFilesystemArtworkSourceResolver,
        snapshot: ArtworkSourceSnapshot,
        request_directory: Path,
        root: _RootRecord,
        source: _RegisteredSource,
        source_identity: tuple[int, ...],
        snapshot_identity: tuple[int, ...],
    ) -> None:
        self._resolver = resolver
        self._snapshot = snapshot
        self._request_directory = request_directory
        self._root = root
        self._source = source
        self._source_identity = source_identity
        try:
            current_snapshot_identity = _snapshot_identity(snapshot.snapshot_path)
        except (OSError, ValueError) as error:
            raise ArtworkSourceError(
                "PREVIEW_INTERNAL_ERROR", "The owned artwork snapshot failed verification."
            ) from error
        if current_snapshot_identity != snapshot_identity:
            raise ArtworkSourceError(
                "PREVIEW_INTERNAL_ERROR", "The owned artwork snapshot failed verification."
            )
        self._snapshot_identity = snapshot_identity
        self._closed = False

    @property
    def snapshot(self) -> ArtworkSourceSnapshot:
        if self._closed:
            raise ArtworkSourceError("PREVIEW_INTERNAL_ERROR", "The artwork source lease is closed.")
        return self._snapshot

    def verify_snapshot(self, cancel_event: Any = None) -> None:
        if self._closed:
            raise ArtworkSourceError("PREVIEW_INTERNAL_ERROR", "The artwork source lease is closed.")
        _raise_if_cancelled(cancel_event)
        try:
            identity = _snapshot_identity(self._snapshot.snapshot_path)
            digest, size = _hash_path_no_follow(self._snapshot.snapshot_path, cancel_event)
        except (OSError, ValueError) as error:
            raise ArtworkSourceError(
                "PREVIEW_INTERNAL_ERROR", "The owned artwork snapshot failed verification."
            ) from error
        if (
            identity != self._snapshot_identity
            or digest != self._snapshot.source_sha256
            or size != self._snapshot.byte_size
        ):
            raise ArtworkSourceError(
                "PREVIEW_INTERNAL_ERROR", "The owned artwork snapshot failed verification."
            )

    def revalidate_source(self, cancel_event: Any = None) -> None:
        if self._closed:
            raise ArtworkSourceError("PREVIEW_INTERNAL_ERROR", "The artwork source lease is closed.")
        self._resolver._revalidate(
            self._root,
            self._source,
            self._source_identity,
            self._snapshot.source_sha256,
            cancel_event,
        )

    def close(self) -> None:
        if self._closed:
            return
        cleanup_error: OSError | None = None
        try:
            _remove_owned_snapshot(self._snapshot.snapshot_path, self._snapshot_identity)
        except OSError as error:
            cleanup_error = error
        try:
            self._request_directory.rmdir()
        except OSError as error:
            cleanup_error = cleanup_error or error
        if cleanup_error is not None:
            raise ArtworkSourceError(
                "PREVIEW_INTERNAL_ERROR", "The owned artwork snapshot could not be removed."
            ) from cleanup_error
        self._closed = True

    def __enter__(self) -> _FilesystemArtworkSourceLease:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class SecureFilesystemArtworkSourceResolver(ArtworkSourceResolver):
    """Acquire local registered files into private, request-owned snapshots.

    POSIX acquisition walks from a trusted directory descriptor with no-follow
    opens. Windows acquisition inspects every component through Win32 handles,
    rejects reparse points, and reads the leaf through its handle. The optional
    event hook exists solely to make race tests deterministic.
    """

    def __init__(
        self,
        registry: ImmutableArtworkRegistry,
        snapshot_root: str | Path,
        *,
        _event_hook: Callable[[str], None] | None = None,
    ) -> None:
        if not isinstance(registry, ImmutableArtworkRegistry):
            raise TypeError("A trusted immutable artwork registry is required.")
        self._registry = registry
        self._snapshot_root = Path(snapshot_root).absolute()
        self._event_hook = _event_hook
        snapshot_record = _inspect_root(self._snapshot_root)
        self._snapshot_root_record = snapshot_record
        for source_root in registry.roots:
            source_record = _inspect_root(source_root)
            if source_record.identity == snapshot_record.identity:
                raise ValueError("Snapshot storage must be separate from trusted artwork roots.")
            if _paths_overlap(source_record, snapshot_record):
                raise ValueError("Snapshot storage must not overlap a trusted artwork root.")

    def acquire(
        self,
        album_id: str,
        artwork_asset_id: str,
        cancel_event: Any = None,
    ) -> ArtworkSourceLease:
        _raise_if_cancelled(cancel_event)
        root, source = self._registry.lookup(album_id, artwork_asset_id)
        request_directory: Path | None = None
        snapshot_path: Path | None = None
        snapshot_identity: tuple[int, ...] | None = None
        snapshot_descriptor: int | None = None
        opened: _OpenedSource | None = None
        try:
            opened = _open_registered_source(root, source)
            self._notify("source_opened")
            if opened.size == 0:
                raise ArtworkSourceError("PREVIEW_IMAGE_UNSUPPORTED", "The artwork source is empty.")
            if opened.size > MAX_ARTWORK_SOURCE_BYTES:
                raise ArtworkSourceError(
                    "PREVIEW_IMAGE_UNSUPPORTED", "The artwork source exceeds the supported size limit."
                )
            self._revalidate_snapshot_root()
            try:
                request_directory = Path(
                    tempfile.mkdtemp(prefix="preview-source-", dir=self._snapshot_root)
                )
            except OSError as error:
                raise ArtworkSourceError(
                    "PREVIEW_INTERNAL_ERROR", "Private artwork snapshot storage is unavailable."
                ) from error
            self._revalidate_snapshot_root()
            snapshot_path = request_directory / f"source{source.suffix}"
            try:
                snapshot_descriptor = os.open(
                    snapshot_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | _BINARY_OPEN_FLAG,
                    0o600,
                )
                snapshot_metadata = os.fstat(snapshot_descriptor)
                if not stat.S_ISREG(snapshot_metadata.st_mode):
                    raise OSError("Owned artwork snapshot is not a regular file.")
                snapshot_identity = (snapshot_metadata.st_dev, snapshot_metadata.st_ino)
            except OSError as error:
                raise ArtworkSourceError(
                    "PREVIEW_INTERNAL_ERROR", "Private artwork snapshot storage is unavailable."
                ) from error
            try:
                digest, copied_size = self._copy_open_source(
                    opened, snapshot_descriptor, cancel_event
                )
            finally:
                descriptor_to_close = snapshot_descriptor
                snapshot_descriptor = None
                os.close(descriptor_to_close)
            assert snapshot_identity is not None
            try:
                _set_owned_snapshot_mode(snapshot_path, snapshot_identity, stat.S_IREAD)
            except OSError as error:
                raise ArtworkSourceError(
                    "PREVIEW_INTERNAL_ERROR", "The owned artwork snapshot could not be protected."
                ) from error
            self._notify("source_copied")
            opened.rewind()
            second_digest, second_size = _hash_open_source(opened, cancel_event)
            if digest != second_digest or copied_size != second_size or second_size != opened.size:
                raise ArtworkSourceError("SOURCE_CHANGED", "The artwork source changed during acquisition.")
            source_identity = opened.identity
            opened.close()
            opened = None
            self._notify("before_revalidate")
            self._revalidate(root, source, source_identity, digest, cancel_event)
            snapshot = ArtworkSourceSnapshot(
                album_id=album_id,
                artwork_asset_id=artwork_asset_id,
                snapshot_path=snapshot_path,
                source_sha256=digest,
                byte_size=copied_size,
            )
            lease = _FilesystemArtworkSourceLease(
                self,
                snapshot,
                request_directory,
                root,
                source,
                source_identity,
                snapshot_identity,
            )
            lease.verify_snapshot(cancel_event)
            return lease
        except ArtworkSourceError:
            _cleanup_partial(request_directory, snapshot_path, snapshot_identity)
            raise
        except Exception as error:
            _cleanup_partial(request_directory, snapshot_path, snapshot_identity)
            if not _is_filesystem_error(error):
                raise
            raise ArtworkSourceError(
                "PREVIEW_SOURCE_UNAVAILABLE", "The requested artwork source is unavailable."
            ) from error
        finally:
            if snapshot_descriptor is not None:
                os.close(snapshot_descriptor)
            if opened is not None:
                opened.close()

    def _copy_open_source(
        self,
        source: _OpenedSource,
        descriptor: int,
        cancel_event: Any,
    ) -> tuple[str, int]:
        digest = hashlib.sha256()
        total = 0
        while True:
            _raise_if_cancelled(cancel_event)
            chunk = source.read(_COPY_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_ARTWORK_SOURCE_BYTES:
                raise ArtworkSourceError(
                    "PREVIEW_IMAGE_UNSUPPORTED", "The artwork source exceeds the supported size limit."
                )
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                try:
                    written = os.write(descriptor, view)
                except OSError as error:
                    raise ArtworkSourceError(
                        "PREVIEW_INTERNAL_ERROR", "The owned artwork snapshot could not be written."
                    ) from error
                if written <= 0:
                    raise ArtworkSourceError(
                        "PREVIEW_INTERNAL_ERROR", "The owned artwork snapshot could not be written."
                    )
                view = view[written:]
            self._notify("source_chunk_copied")
        try:
            os.fsync(descriptor)
        except OSError as error:
            raise ArtworkSourceError(
                "PREVIEW_INTERNAL_ERROR", "The owned artwork snapshot could not be synchronized."
            ) from error
        return digest.hexdigest(), total

    def _revalidate_snapshot_root(self) -> None:
        try:
            current = _inspect_root(self._snapshot_root)
        except (OSError, RuntimeError, ValueError) as error:
            raise ArtworkSourceError(
                "PREVIEW_INTERNAL_ERROR", "Private artwork snapshot storage is unavailable."
            ) from error
        if not _root_records_match(current, self._snapshot_root_record):
            raise ArtworkSourceError(
                "PREVIEW_INTERNAL_ERROR", "Private artwork snapshot storage changed after configuration."
            )

    def _revalidate(
        self,
        root: _RootRecord,
        source: _RegisteredSource,
        expected_identity: tuple[int, ...],
        expected_digest: str,
        cancel_event: Any,
    ) -> None:
        _raise_if_cancelled(cancel_event)
        current: _OpenedSource | None = None
        try:
            current = _open_registered_source(root, source)
            digest, size = _hash_open_source(current, cancel_event)
            if (
                current.identity != expected_identity
                or digest != expected_digest
                or size != current.size
            ):
                raise ArtworkSourceError("SOURCE_CHANGED", "The artwork source changed after acquisition.")
        except ArtworkSourceError:
            raise
        except Exception as error:
            if not _is_filesystem_error(error):
                raise
            raise ArtworkSourceError("SOURCE_CHANGED", "The artwork source changed after acquisition.") from error
        finally:
            if current is not None:
                current.close()

    def _notify(self, stage: str) -> None:
        if self._event_hook is not None:
            self._event_hook(stage)


def _validate_relative_source(value: str) -> tuple[tuple[str, ...], str]:
    if type(value) is not str or not value or "\\" in value or "\x00" in value:
        raise ValueError("Registered artwork paths must be normalized relative POSIX paths.")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError("Registered artwork paths must contain valid Unicode.") from error
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or value.startswith("//")
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or any(":" in part for part in value.split("/"))
    ):
        raise ValueError("Registered artwork paths must remain beneath their trusted root.")
    suffix = posix.suffix.lower()
    if suffix not in SUPPORTED_ARTWORK_EXTENSIONS:
        raise ValueError("Registered artwork must use a supported Phase 2 image suffix.")
    return tuple(posix.parts), suffix


def _inspect_root(path_value: str | Path) -> _RootRecord:
    path = Path(path_value).absolute()
    if os.name == "nt":
        handle = None
        try:
            win32file, win32con = _win32_modules()
            windows_path = PureWindowsPath(str(path))
            if windows_path.drive.startswith("\\\\"):
                raise ValueError("Trusted artwork roots must use a local filesystem.")
            volume_root = win32file.GetVolumePathName(str(path))
            local_drive_types = {
                win32con.DRIVE_REMOVABLE,
                win32con.DRIVE_FIXED,
                win32con.DRIVE_CDROM,
                win32con.DRIVE_RAMDISK,
            }
            if win32file.GetDriveType(volume_root) not in local_drive_types:
                raise ValueError("Trusted artwork roots must use a local filesystem.")
            handle = win32file.CreateFile(
                str(path),
                0,
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
                None,
                win32con.OPEN_EXISTING,
                win32file.FILE_FLAG_OPEN_REPARSE_POINT | win32con.FILE_FLAG_BACKUP_SEMANTICS,
                None,
            )
            info = win32file.GetFileInformationByHandle(handle)
            if info[0] & win32con.FILE_ATTRIBUTE_REPARSE_POINT or not (
                info[0] & win32con.FILE_ATTRIBUTE_DIRECTORY
            ):
                raise ValueError("Trusted artwork roots must be real local directories, not reparse points.")
            return _RootRecord(path, _windows_identity(info), win32file.GetFinalPathNameByHandle(handle, 0))
        except ValueError:
            raise
        except Exception as error:
            raise ValueError("Trusted artwork roots must be accessible local directories.") from error
        finally:
            if handle is not None:
                handle.Close()
    if (
        not hasattr(os, "O_NOFOLLOW")
        or not hasattr(os, "O_DIRECTORY")
        or os.open not in os.supports_dir_fd
    ):
        raise RuntimeError("Secure POSIX artwork acquisition is unavailable on this platform.")
    _validate_posix_local_filesystem(path)
    try:
        metadata = os.lstat(path)
    except OSError as error:
        raise ValueError("Trusted artwork roots must be accessible local directories.") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("Trusted artwork roots must be real local directories, not symlinks.")
    return _RootRecord(path, (metadata.st_dev, metadata.st_ino), str(path.resolve(strict=True)))


def _open_registered_source(root: _RootRecord, source: _RegisteredSource) -> _OpenedSource:
    if os.name == "nt":
        return _open_windows_source(root, source)
    return _open_posix_source(root, source)


def _open_posix_source(root: _RootRecord, source: _RegisteredSource) -> _OpenedSource:
    nofollow = os.O_NOFOLLOW
    cloexec = getattr(os, "O_CLOEXEC", 0)
    directory = os.O_DIRECTORY
    root_fd = os.open(root.path, os.O_RDONLY | directory | nofollow | cloexec)
    opened_directories = [root_fd]
    leaf_fd: int | None = None
    try:
        root_stat = os.fstat(root_fd)
        if (root_stat.st_dev, root_stat.st_ino) != root.identity or not stat.S_ISDIR(root_stat.st_mode):
            raise ArtworkSourceError("SOURCE_CHANGED", "A trusted artwork root changed after registration.")
        _validate_posix_local_filesystem_descriptor(root_fd)
        parent_fd = root_fd
        for part in source.parts[:-1]:
            parent_fd = os.open(part, os.O_RDONLY | directory | nofollow | cloexec, dir_fd=parent_fd)
            opened_directories.append(parent_fd)
            if not stat.S_ISDIR(os.fstat(parent_fd).st_mode):
                raise OSError("Registered source parent is not a directory.")
            _validate_posix_local_filesystem_descriptor(parent_fd)
        leaf_fd = os.open(source.parts[-1], os.O_RDONLY | nofollow | cloexec, dir_fd=parent_fd)
        info = os.fstat(leaf_fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError("Registered source is not a regular file.")
        _validate_posix_local_filesystem_descriptor(leaf_fd)
        source_descriptor = leaf_fd
        leaf_fd = None
        return _OpenedSource(
            source_descriptor,
            (info.st_dev, info.st_ino),
            info.st_size,
            lambda amount: os.read(source_descriptor, amount),
            lambda: os.lseek(source_descriptor, 0, os.SEEK_SET),
            lambda: os.close(source_descriptor),
        )
    finally:
        if leaf_fd is not None:
            os.close(leaf_fd)
        for descriptor in reversed(opened_directories):
            os.close(descriptor)


def _open_windows_source(root: _RootRecord, source: _RegisteredSource) -> _OpenedSource:
    win32file, win32con = _win32_modules()
    share_all = win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE
    root_handle = win32file.CreateFile(
        str(root.path),
        0,
        share_all,
        None,
        win32con.OPEN_EXISTING,
        win32file.FILE_FLAG_OPEN_REPARSE_POINT | win32con.FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    try:
        root_info = win32file.GetFileInformationByHandle(root_handle)
        if (
            _windows_identity(root_info) != root.identity
            or root_info[0] & win32con.FILE_ATTRIBUTE_REPARSE_POINT
            or not root_info[0] & win32con.FILE_ATTRIBUTE_DIRECTORY
        ):
            raise ArtworkSourceError("SOURCE_CHANGED", "A trusted artwork root changed after registration.")
        if win32file.GetFinalPathNameByHandle(root_handle, 0) != root.final_path:
            raise ArtworkSourceError("SOURCE_CHANGED", "A trusted artwork root changed after registration.")
    finally:
        root_handle.Close()
    for index in range(len(source.parts) - 1):
        prefix = root.path.joinpath(*source.parts[: index + 1])
        handle = win32file.CreateFile(
            str(prefix),
            0,
            share_all,
            None,
            win32con.OPEN_EXISTING,
            win32file.FILE_FLAG_OPEN_REPARSE_POINT | win32con.FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )
        try:
            info = win32file.GetFileInformationByHandle(handle)
            if info[0] & win32con.FILE_ATTRIBUTE_REPARSE_POINT or not (
                info[0] & win32con.FILE_ATTRIBUTE_DIRECTORY
            ):
                raise OSError("Registered source traverses a reparse point.")
            _verify_windows_containment(root, win32file.GetFinalPathNameByHandle(handle, 0))
        finally:
            handle.Close()

    leaf_path = root.path.joinpath(*source.parts)
    handle = win32file.CreateFile(
        str(leaf_path),
        win32con.GENERIC_READ,
        win32con.FILE_SHARE_READ,
        None,
        win32con.OPEN_EXISTING,
        win32file.FILE_FLAG_OPEN_REPARSE_POINT | win32con.FILE_FLAG_SEQUENTIAL_SCAN,
        None,
    )
    try:
        info = win32file.GetFileInformationByHandle(handle)
        if info[0] & (win32con.FILE_ATTRIBUTE_REPARSE_POINT | win32con.FILE_ATTRIBUTE_DIRECTORY):
            raise OSError("Registered source is not a regular non-reparse file.")
        _verify_windows_containment(root, win32file.GetFinalPathNameByHandle(handle, 0))
        size = (int(info[5]) << 32) | int(info[6])

        def read(amount: int) -> bytes:
            _, data = win32file.ReadFile(handle, amount)
            return bytes(data)

        def rewind() -> None:
            win32file.SetFilePointer(handle, 0, win32file.FILE_BEGIN)

        return _OpenedSource(handle, _windows_identity(info), size, read, rewind, handle.Close)
    except Exception:
        handle.Close()
        raise


def _verify_windows_containment(root: _RootRecord, final_path: str) -> None:
    if root.final_path is None:
        raise OSError("Trusted root final path is unavailable.")
    root_text = os.path.normcase(os.path.normpath(root.final_path)).rstrip("\\/")
    candidate = os.path.normcase(os.path.normpath(final_path))
    if candidate != root_text and not candidate.startswith(root_text + "\\"):
        raise OSError("Registered source escaped its trusted root.")


def _windows_identity(info: tuple[Any, ...]) -> tuple[int, ...]:
    return (int(info[4]), int(info[8]), int(info[9]))


def _win32_modules() -> tuple[Any, Any]:
    try:
        import win32con
        import win32file
    except ImportError as error:
        raise RuntimeError("Secure Windows artwork acquisition requires pywin32.") from error
    return win32file, win32con


def _hash_open_source(source: _OpenedSource, cancel_event: Any) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    while True:
        _raise_if_cancelled(cancel_event)
        chunk = source.read(_COPY_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        digest.update(chunk)
    return digest.hexdigest(), total


def _snapshot_identity(path: Path) -> tuple[int, ...]:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("Snapshot is not a regular file.")
    if os.name == "nt" and metadata.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError("Snapshot is a reparse point.")
    return (metadata.st_dev, metadata.st_ino)


def _hash_path_no_follow(path: Path, cancel_event: Any) -> tuple[str, int]:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | _BINARY_OPEN_FLAG
    )
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("Snapshot is not a regular file.")
        digest = hashlib.sha256()
        total = 0
        while True:
            _raise_if_cancelled(cancel_event)
            chunk = os.read(descriptor, _COPY_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
        return digest.hexdigest(), total
    finally:
        os.close(descriptor)


def _paths_overlap(first: _RootRecord, second: _RootRecord) -> bool:
    if os.name == "nt":
        first_path = os.path.normcase(os.path.normpath(first.final_path or str(first.path)))
        second_path = os.path.normcase(os.path.normpath(second.final_path or str(second.path)))
    else:
        first_path = first.final_path or str(first.path)
        second_path = second.final_path or str(second.path)
    try:
        return os.path.commonpath((first_path, second_path)) in {first_path, second_path}
    except ValueError:
        return False


def _root_records_match(first: _RootRecord, second: _RootRecord) -> bool:
    if first.identity != second.identity:
        return False
    if os.name == "nt":
        return os.path.normcase(os.path.normpath(first.final_path or "")) == os.path.normcase(
            os.path.normpath(second.final_path or "")
        )
    return first.final_path == second.final_path


def _raise_if_cancelled(cancel_event: Any) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ArtworkSourceError("PREVIEW_CANCELLED", "Artwork source acquisition was cancelled.")


def _cleanup_partial(
    request_directory: Path | None,
    snapshot_path: Path | None,
    snapshot_identity: tuple[int, ...] | None,
) -> None:
    if request_directory is None:
        return
    try:
        if snapshot_path is not None and snapshot_identity is not None:
            _remove_owned_snapshot(snapshot_path, snapshot_identity)
        request_directory.rmdir()
    except OSError as error:
        raise ArtworkSourceError(
            "PREVIEW_INTERNAL_ERROR", "Partial artwork snapshot cleanup failed."
        ) from error


def _set_owned_snapshot_mode(
    path: Path,
    expected_identity: tuple[int, ...],
    mode: int,
) -> None:
    try:
        if _snapshot_identity(path) != expected_identity:
            raise OSError("Owned artwork snapshot identity changed.")
        path.chmod(mode)
        if _snapshot_identity(path) != expected_identity:
            raise OSError("Owned artwork snapshot identity changed.")
    except (OSError, ValueError) as error:
        raise OSError("Owned artwork snapshot attributes could not be changed safely.") from error


def _remove_owned_snapshot(path: Path, expected_identity: tuple[int, ...]) -> None:
    try:
        current_identity = _snapshot_identity(path)
    except FileNotFoundError:
        return
    except (OSError, ValueError) as error:
        raise OSError("Owned artwork snapshot identity could not be verified.") from error
    if current_identity != expected_identity:
        raise OSError("Owned artwork snapshot identity changed.")
    _set_owned_snapshot_mode(path, expected_identity, stat.S_IREAD | stat.S_IWRITE)
    try:
        if _snapshot_identity(path) != expected_identity:
            raise OSError("Owned artwork snapshot identity changed.")
        path.unlink()
    except (OSError, ValueError) as error:
        raise OSError("Owned artwork snapshot could not be removed safely.") from error


def _is_filesystem_error(error: BaseException) -> bool:
    return isinstance(error, OSError) or error.__class__.__module__ == "pywintypes"


def _validate_posix_local_filesystem(path: Path) -> None:
    if not sys.platform.startswith("linux"):
        raise RuntimeError(
            "Local-filesystem classification is unavailable on this POSIX platform."
        )
    filesystem_magic = _linux_filesystem_magic(path)
    if filesystem_magic not in _LINUX_LOCAL_FILESYSTEMS:
        raise ValueError("Trusted artwork roots must use a supported local filesystem.")


def _validate_posix_local_filesystem_descriptor(descriptor: int) -> None:
    if not sys.platform.startswith("linux"):
        raise OSError("Descriptor filesystem classification is unavailable on this platform.")
    filesystem_magic = _linux_filesystem_magic_fd(descriptor)
    if filesystem_magic not in _LINUX_LOCAL_FILESYSTEMS:
        raise OSError("Registered artwork must remain on a supported local filesystem.")


def _linux_filesystem_magic(path: Path) -> int:
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    statfs = libc.statfs
    statfs.argtypes = (ctypes.c_char_p, ctypes.c_void_p)
    statfs.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(256)
    if statfs(os.fsencode(path), ctypes.byref(buffer)) != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), str(path))
    return int(ctypes.c_long.from_buffer(buffer).value) & 0xFFFFFFFF


def _linux_filesystem_magic_fd(descriptor: int) -> int:
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    fstatfs = libc.fstatfs
    fstatfs.argtypes = (ctypes.c_int, ctypes.c_void_p)
    fstatfs.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(256)
    if fstatfs(descriptor, ctypes.byref(buffer)) != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))
    return int(ctypes.c_long.from_buffer(buffer).value) & 0xFFFFFFFF
