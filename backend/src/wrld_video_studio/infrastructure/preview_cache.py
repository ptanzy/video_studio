from __future__ import annotations

import errno
import hashlib
import io
import json
import math
import os
import re
import stat
import struct
import sys
import threading
import uuid
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import portalocker

from wrld_video_studio.application.ports.preview_cache import (
    PREVIEW_CACHE_MANIFEST_VERSION,
    CachedPreviewArtifact,
    PreviewArtifactLease,
    PreviewCacheError,
    PreviewCacheStagingLease,
    PreviewCacheStore,
)
from wrld_video_studio.domain.canonical_json import canonical_json_bytes, canonical_sha256
from wrld_video_studio.domain.preview_cache import (
    DEFAULT_PREVIEW_CACHE_MAX_BYTES,
    DEFAULT_PREVIEW_CACHE_MAX_ENTRIES,
    PREVIEW_CACHE_KEY_VERSION,
    STILL_OUTPUT_MAX_DIMENSION,
    PreviewCacheIdentity,
    PreviewRenderPolicy,
)
from wrld_video_studio.domain.color_resolution import PRESET_MAPPING_VERSION, RESOLVER_VERSION
from wrld_video_studio.infrastructure.artwork_sources import (
    _RootRecord,
    _inspect_root,
    _root_records_match,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STAGING_NAME = re.compile(r"^entry-[0-9a-f]{32}$")
_SHARD_NAME = re.compile(r"^[0-9a-f]{2}$")
_ARTIFACT_NAME = "preview.png"
_MANIFEST_NAME = "entry.json"
_LOCK_NAME = ".preview-cache.lock"
_ENTRIES_NAME = "entries"
_STAGING_ROOT_NAME = ".preview-cache-staging"
_READ_CHUNK = 1024 * 1024
_MAX_MANIFEST_BYTES = 256 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MANIFEST_FIELDS = {"contract_version", "preview_id", "descriptor", "artifact"}
_ARTIFACT_FIELDS = {"sha256", "byte_size", "width", "height", "media_type"}
_DESCRIPTOR_FIELDS = {"contract_version", "source_sha256", "treatment", "render_policy", "toolchain"}
_TREATMENT_FIELDS = {"state", "resolved_hex", "intensity", "resolver_version", "preset_mapping_version"}
_TOOLCHAIN_FIELDS = {"ffmpeg_sha256", "ffprobe_sha256"}
_PROCESS_ROOTS_LOCK = threading.Lock()
_PROCESS_ROOTS: set[tuple[int, ...]] = set()


@dataclass(slots=True)
class _Reader:
    identity: tuple[int, ...]
    size: int
    links: int
    read: Callable[[int], bytes]
    seek: Callable[[int, int], int]
    close: Callable[[], None]


@dataclass(frozen=True, slots=True)
class _VerifiedEntry:
    artifact: CachedPreviewArtifact
    directory: Path
    directory_identity: tuple[int, ...]
    manifest_size: int
    artifact_reader: _Reader


@dataclass(frozen=True, slots=True)
class _EvictionCandidate:
    preview_id: str
    directory: Path
    identity: tuple[int, ...]
    total_size: int
    age_ns: int


class _FilesystemPreviewArtifactLease(PreviewArtifactLease):
    def __init__(
        self,
        store: SecureFilesystemPreviewCache,
        artifact: CachedPreviewArtifact,
        reader: _Reader,
    ) -> None:
        self._store = store
        self._artifact = artifact
        self._reader = reader
        self._closed = False

    @property
    def artifact(self) -> CachedPreviewArtifact:
        if self._closed:
            raise PreviewCacheError("PREVIEW_INTERNAL_ERROR", "The preview artifact lease is closed.")
        return self._artifact

    def read(self, amount: int = -1) -> bytes:
        if self._closed:
            raise PreviewCacheError("PREVIEW_INTERNAL_ERROR", "The preview artifact lease is closed.")
        if type(amount) is not int or amount < -1:
            raise ValueError("Read amount must be -1 or a non-negative integer.")
        try:
            if amount >= 0:
                return self._reader.read(amount)
            chunks: list[bytes] = []
            while chunk := self._reader.read(_READ_CHUNK):
                chunks.append(chunk)
            return b"".join(chunks)
        except OSError as error:
            raise PreviewCacheError("PREVIEW_CACHE_CORRUPT", "The cached preview could not be read.") from error

    def seek(self, offset: int, whence: int = 0) -> int:
        if self._closed:
            raise PreviewCacheError("PREVIEW_INTERNAL_ERROR", "The preview artifact lease is closed.")
        if type(offset) is not int or type(whence) is not int:
            raise TypeError("Seek arguments must be integers.")
        try:
            return self._reader.seek(offset, whence)
        except OSError as error:
            raise PreviewCacheError("PREVIEW_CACHE_CORRUPT", "The cached preview could not be read.") from error

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._reader.close()
        finally:
            self._closed = True
            self._store._unpin(self._artifact.preview_id)

    def __enter__(self) -> _FilesystemPreviewArtifactLease:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class _FilesystemPreviewCacheStagingLease(PreviewCacheStagingLease):
    def __init__(
        self,
        store: SecureFilesystemPreviewCache,
        identity: PreviewCacheIdentity,
        directory: Path,
        directory_identity: tuple[int, ...],
    ) -> None:
        self._store = store
        self._identity = identity
        self._directory: Path | None = directory
        self._directory_identity = directory_identity
        self._closed = False

    @property
    def output_path(self) -> Path:
        if self._closed or self._directory is None:
            raise PreviewCacheError("PREVIEW_INTERNAL_ERROR", "The preview staging lease is closed.")
        return self._directory / _ARTIFACT_NAME

    def publish(
        self,
        *,
        width: int,
        height: int,
        cancel_event: Any = None,
    ) -> PreviewArtifactLease:
        if self._closed or self._directory is None:
            raise PreviewCacheError("PREVIEW_INTERNAL_ERROR", "The preview staging lease is closed.")
        lease, moved = self._store._publish(
            self._identity,
            self._directory,
            self._directory_identity,
            width,
            height,
            cancel_event,
        )
        del moved  # both publication and a verified collision consume staging
        self._store._release_staging(self._directory_identity)
        self._directory = None
        self._closed = True
        return lease

    def close(self) -> None:
        if self._closed:
            return
        directory = self._directory
        try:
            if directory is not None:
                self._store._remove_staging(directory, self._directory_identity)
        finally:
            self._directory = None
            self._closed = True
            self._store._release_staging(self._directory_identity)

    def __enter__(self) -> _FilesystemPreviewCacheStagingLease:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class SecureFilesystemPreviewCache(PreviewCacheStore):
    """Single-process, local-filesystem cache for immutable authoritative PNGs."""

    def __init__(
        self,
        cache_root: str | Path,
        *,
        max_bytes: int = DEFAULT_PREVIEW_CACHE_MAX_BYTES,
        max_entries: int = DEFAULT_PREVIEW_CACHE_MAX_ENTRIES,
        _event_hook: Callable[[str], None] | None = None,
    ) -> None:
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("Preview cache byte capacity must be a positive integer.")
        if type(max_entries) is not int or max_entries < 1:
            raise ValueError("Preview cache entry capacity must be a positive integer.")
        self._root = Path(cache_root).absolute()
        self._max_bytes = max_bytes
        self._max_entries = max_entries
        self._event_hook = _event_hook
        self._mutex = threading.RLock()
        self._pins: dict[str, int] = {}
        self._active_staging: set[tuple[int, ...]] = set()
        self._closed = True
        self._process_lock: portalocker.Lock | None = None
        self._process_lock_handle: Any = None
        self._lock_identity: tuple[int, int] | None = None
        self._registered_root_identity: tuple[int, ...] | None = None
        try:
            self._root_record = _inspect_root(self._root)
            self._claim_process_root()
            self._acquire_process_lock()
            self._assert_root()
            self._verify_writable()
            self._entries_root = self._ensure_directory(self._root / _ENTRIES_NAME)
            self._staging_root = self._ensure_directory(self._root / _STAGING_ROOT_NAME)
            self._closed = False
            self._recover_abandoned_staging()
            self._make_room(0, 0, permit_existing_exhaustion=True)
        except PreviewCacheError:
            self._release_initialization()
            raise
        except (OSError, RuntimeError, ValueError, portalocker.exceptions.LockException) as error:
            self._release_initialization()
            raise PreviewCacheError(
                "PREVIEW_INTERNAL_ERROR", "Preview cache storage is unavailable."
            ) from error

    def lookup(
        self,
        identity: PreviewCacheIdentity,
        cancel_event: Any = None,
    ) -> PreviewArtifactLease | None:
        _require_identity(identity)
        with self._mutex:
            self._assert_open()
            self._assert_root()
            _raise_if_cancelled(cancel_event)
            try:
                entry_path = self._entry_path(identity.preview_id, create_shard=False)
            except (OSError, RuntimeError, ValueError) as error:
                raise PreviewCacheError(
                    "PREVIEW_INTERNAL_ERROR", "Preview cache entry location validation failed."
                ) from error
            if not _lexists(entry_path):
                return None
            try:
                verified = self._verify_entry(entry_path, identity, cancel_event)
            except PreviewCacheError:
                raise
            except (OSError, ValueError, json.JSONDecodeError, zlib.error) as error:
                raise PreviewCacheError(
                    "PREVIEW_CACHE_CORRUPT", "The cached preview failed integrity verification."
                ) from error
            self._pins[identity.preview_id] = self._pins.get(identity.preview_id, 0) + 1
            return _FilesystemPreviewArtifactLease(self, verified.artifact, verified.artifact_reader)

    def begin_write(self, identity: PreviewCacheIdentity) -> PreviewCacheStagingLease:
        _require_identity(identity)
        with self._mutex:
            self._assert_open()
            self._assert_root()
            self._assert_directory_record(self._staging_root)
            name = f"entry-{uuid.uuid4().hex}"
            directory = self._staging_root.path / name
            try:
                directory.mkdir(mode=0o700)
                record = _inspect_root(directory)
                self._assert_root()
            except (OSError, RuntimeError, ValueError) as error:
                raise PreviewCacheError(
                    "PREVIEW_INTERNAL_ERROR", "Private preview staging could not be created."
                ) from error
            self._active_staging.add(record.identity)
            return _FilesystemPreviewCacheStagingLease(self, identity, directory, record.identity)

    def discard_corrupt(self, identity: PreviewCacheIdentity) -> bool:
        """Safely remove only the exact invalid entry selected by the trusted identity.

        A valid entry is never discarded. The future Phase 3C-3 caller owns the
        one-attempt regeneration counter.
        """
        _require_identity(identity)
        with self._mutex:
            self._assert_open()
            self._assert_root()
            if self._pins.get(identity.preview_id, 0):
                raise PreviewCacheError("PREVIEW_INTERNAL_ERROR", "A pinned cached preview cannot be removed.")
            try:
                path = self._entry_path(identity.preview_id, create_shard=False)
            except (OSError, RuntimeError, ValueError) as error:
                raise PreviewCacheError(
                    "PREVIEW_INTERNAL_ERROR", "Preview cache entry location validation failed."
                ) from error
            if not _lexists(path):
                return False
            try:
                verified = self._verify_entry(path, identity, None)
            except PreviewCacheError as error:
                if error.code != "PREVIEW_CACHE_CORRUPT":
                    raise
            except (OSError, ValueError, json.JSONDecodeError, zlib.error):
                pass
            else:
                verified.artifact_reader.close()
                return False
            self._delete_exact_entry(path)
            return True

    def enforce_limits(self) -> None:
        with self._mutex:
            self._assert_open()
            self._assert_root()
            self._make_room(0, 0)

    def close(self) -> None:
        with self._mutex:
            if self._closed:
                return
            if any(self._pins.values()):
                raise PreviewCacheError(
                    "PREVIEW_INTERNAL_ERROR", "Preview cache storage still has active artifact leases."
                )
            if self._active_staging:
                raise PreviewCacheError(
                    "PREVIEW_INTERNAL_ERROR", "Preview cache storage still has active staging leases."
                )
            self._closed = True
            self._release_process_lock()
            self._release_process_root()

    def __enter__(self) -> SecureFilesystemPreviewCache:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _publish(
        self,
        identity: PreviewCacheIdentity,
        staging: Path,
        staging_identity: tuple[int, ...],
        width: int,
        height: int,
        cancel_event: Any,
    ) -> tuple[PreviewArtifactLease, bool]:
        try:
            width = _dimension(width)
            height = _dimension(height)
        except ValueError as error:
            raise PreviewCacheError(
                "PREVIEW_INTERNAL_ERROR", "Preview publication metadata is invalid."
            ) from error
        with self._mutex:
            self._assert_open()
            self._assert_root()
            self._assert_owned_staging(staging, staging_identity)
            _raise_if_cancelled(cancel_event)
            artifact_path = staging / _ARTIFACT_NAME
            try:
                reader = _open_regular_file(artifact_path, self._root_record)
                try:
                    if reader.links != 1:
                        raise ValueError("Artifact ownership is invalid.")
                    if reader.size > self._max_bytes:
                        raise PreviewCacheError(
                            "PREVIEW_CAPACITY_EXHAUSTED", "Preview cache capacity is exhausted."
                        )
                    artifact_sha256, artifact_size, actual_width, actual_height = _inspect_png_reader(
                        reader, self._max_bytes, cancel_event
                    )
                    if (actual_width, actual_height) != (width, height):
                        raise ValueError("PNG dimensions do not match publication metadata.")
                finally:
                    reader.close()
            except PreviewCacheError:
                raise
            except (OSError, ValueError, zlib.error) as error:
                raise PreviewCacheError(
                    "PREVIEW_CACHE_CORRUPT", "The preview artifact failed integrity verification."
                ) from error

            manifest = _manifest(identity, artifact_sha256, artifact_size, width, height)
            manifest_bytes = canonical_json_bytes(manifest)
            self._write_private_file(staging / _MANIFEST_NAME, manifest_bytes)
            try:
                _fsync_directory(staging)
                self._call_hook("before_publish")
                _raise_if_cancelled(cancel_event)
            except PreviewCacheError:
                raise
            except OSError as error:
                raise PreviewCacheError(
                    "PREVIEW_INTERNAL_ERROR", "Preview cache publication did not begin."
                ) from error
            destination = self._entry_path(identity.preview_id, create_shard=True)
            if _lexists(destination):
                self._remove_staging(staging, staging_identity)
                collision = self.lookup(identity, cancel_event)
                if collision is None:
                    raise PreviewCacheError(
                        "PREVIEW_INTERNAL_ERROR", "Preview cache publication collision could not be verified."
                    )
                return collision, False
            self._make_room(artifact_size + len(manifest_bytes), 1)
            _raise_if_cancelled(cancel_event)
            try:
                published = _atomic_directory_publish_no_replace(staging, destination)
            except (OSError, RuntimeError) as error:
                raise PreviewCacheError(
                    "PREVIEW_INTERNAL_ERROR", "Preview cache publication is unavailable."
                ) from error
            if not published:
                self._remove_staging(staging, staging_identity)
                collision = self.lookup(identity, cancel_event)
                if collision is None:
                    raise PreviewCacheError(
                        "PREVIEW_INTERNAL_ERROR", "Preview cache publication collision could not be verified."
                    )
                return collision, False
            try:
                _fsync_directory(destination.parent)
                self._call_hook("after_publish")
            except OSError as error:
                raise PreviewCacheError(
                    "PREVIEW_INTERNAL_ERROR", "Preview cache publication could not be confirmed."
                ) from error
            lease = self.lookup(identity, cancel_event)
            if lease is None:
                raise PreviewCacheError(
                    "PREVIEW_INTERNAL_ERROR", "Published preview cache entry is unavailable."
                )
            return lease, True

    def _verify_entry(
        self,
        path: Path,
        identity: PreviewCacheIdentity | None,
        cancel_event: Any,
    ) -> _VerifiedEntry:
        try:
            directory_record = _inspect_root(path)
            _verify_containment(self._root_record, directory_record)
            children = {child.name for child in path.iterdir()}
            if children != {_ARTIFACT_NAME, _MANIFEST_NAME}:
                raise ValueError("Cache entry has unexpected material.")
            manifest_reader = _open_regular_file(path / _MANIFEST_NAME, self._root_record)
            try:
                if manifest_reader.links != 1 or manifest_reader.size > _MAX_MANIFEST_BYTES:
                    raise ValueError("Manifest ownership or size is invalid.")
                raw_manifest = _read_all(manifest_reader, _MAX_MANIFEST_BYTES, cancel_event)
            finally:
                manifest_reader.close()
            manifest = json.loads(raw_manifest.decode("utf-8"))
            if type(manifest) is not dict or canonical_json_bytes(manifest) != raw_manifest:
                raise ValueError("Manifest encoding is not canonical.")
            _validate_manifest_structure(manifest)
            expected_preview_id = identity.preview_id if identity is not None else path.name
            expected_descriptor = identity.descriptor.to_dict() if identity is not None else None
            if manifest["preview_id"] != expected_preview_id:
                raise ValueError("Manifest preview ID differs from its cache location.")
            if expected_descriptor is not None and manifest["descriptor"] != expected_descriptor:
                raise ValueError("Manifest descriptor differs from the requested identity.")
            if canonical_sha256(manifest["descriptor"]) != manifest["preview_id"]:
                raise ValueError("Manifest descriptor digest is inconsistent.")
            artifact_reader = _open_regular_file(path / _ARTIFACT_NAME, self._root_record)
            try:
                artifact_metadata = manifest["artifact"]
                if artifact_reader.links != 1 or artifact_reader.size != artifact_metadata["byte_size"]:
                    raise ValueError("Artifact size or ownership is inconsistent.")
                digest, observed_size, width, height = _inspect_png_reader(
                    artifact_reader, artifact_reader.size, cancel_event
                )
                if observed_size != artifact_metadata["byte_size"]:
                    raise ValueError("Artifact size is inconsistent.")
                if (width, height) != (artifact_metadata["width"], artifact_metadata["height"]):
                    raise ValueError("Artifact dimensions are inconsistent.")
                if digest != artifact_metadata["sha256"]:
                    raise ValueError("Artifact digest is inconsistent.")
                artifact_reader.seek(0, os.SEEK_SET)
            except Exception:
                artifact_reader.close()
                raise
            return _VerifiedEntry(
                artifact=CachedPreviewArtifact(
                    preview_id=manifest["preview_id"],
                    artifact_sha256=artifact_metadata["sha256"],
                    byte_size=artifact_metadata["byte_size"],
                    width=artifact_metadata["width"],
                    height=artifact_metadata["height"],
                ),
                directory=path,
                directory_identity=directory_record.identity,
                manifest_size=len(raw_manifest),
                artifact_reader=artifact_reader,
            )
        except PreviewCacheError:
            raise
        except (OSError, RuntimeError, ValueError, UnicodeError, json.JSONDecodeError, zlib.error) as error:
            raise PreviewCacheError(
                "PREVIEW_CACHE_CORRUPT", "The cached preview failed integrity verification."
            ) from error

    def _make_room(
        self,
        additional_bytes: int,
        additional_entries: int,
        *,
        permit_existing_exhaustion: bool = False,
    ) -> None:
        candidates, total_bytes, total_entries = self._scan_verified_entries()
        required_bytes = total_bytes + additional_bytes
        required_entries = total_entries + additional_entries
        if additional_bytes > self._max_bytes or additional_entries > self._max_entries:
            raise PreviewCacheError("PREVIEW_CAPACITY_EXHAUSTED", "Preview cache capacity is exhausted.")
        for candidate in sorted(candidates, key=lambda item: (item.age_ns, item.preview_id)):
            if required_bytes <= self._max_bytes and required_entries <= self._max_entries:
                break
            if self._pins.get(candidate.preview_id, 0):
                continue
            self._delete_verified_entry(candidate)
            required_bytes -= candidate.total_size
            required_entries -= 1
        if required_bytes > self._max_bytes or required_entries > self._max_entries:
            if permit_existing_exhaustion and additional_bytes == 0 and additional_entries == 0:
                return
            raise PreviewCacheError("PREVIEW_CAPACITY_EXHAUSTED", "Preview cache capacity is exhausted.")

    def _scan_verified_entries(self) -> tuple[list[_EvictionCandidate], int, int]:
        self._assert_directory_record(self._entries_root)
        candidates: list[_EvictionCandidate] = []
        total_bytes = 0
        total_entries = 0
        try:
            for shard in self._entries_root.path.iterdir():
                if not _SHARD_NAME.fullmatch(shard.name):
                    raise PreviewCacheError(
                        "PREVIEW_INTERNAL_ERROR", "Unrecognized material exists in managed preview storage."
                    )
                shard_record = _inspect_root(shard)
                _verify_containment(self._root_record, shard_record)
                for entry in shard.iterdir():
                    if not _SHA256.fullmatch(entry.name) or not entry.name.startswith(shard.name):
                        raise PreviewCacheError(
                            "PREVIEW_INTERNAL_ERROR", "Unrecognized material exists in managed preview storage."
                        )
                    entry_record = _inspect_root(entry)
                    _verify_containment(self._root_record, entry_record)
                    try:
                        verified = self._verify_entry(entry, None, None)
                    except PreviewCacheError as error:
                        if error.code != "PREVIEW_CACHE_CORRUPT":
                            raise
                        total_bytes += self._measure_corrupt_entry(entry, entry_record)
                        total_entries += 1
                        continue
                    try:
                        metadata = entry.stat()
                        candidate = _EvictionCandidate(
                            preview_id=entry.name,
                            directory=entry,
                            identity=verified.directory_identity,
                            total_size=verified.artifact.byte_size + verified.manifest_size,
                            age_ns=metadata.st_mtime_ns,
                        )
                    finally:
                        verified.artifact_reader.close()
                    candidates.append(candidate)
                    total_bytes += candidate.total_size
                    total_entries += 1
        except PreviewCacheError:
            raise
        except (OSError, RuntimeError, ValueError) as error:
            raise PreviewCacheError(
                "PREVIEW_INTERNAL_ERROR", "Preview cache inventory could not be verified."
            ) from error
        return candidates, total_bytes, total_entries

    def _measure_corrupt_entry(self, path: Path, expected: _RootRecord) -> int:
        """Count safely inspectable corrupt material without making it evictable."""
        try:
            current = _inspect_root(path)
            if not _root_records_match(expected, current):
                raise OSError("Corrupt cache entry identity changed.")
            _verify_containment(self._root_record, current)
            total_size = 0
            for child in path.iterdir():
                metadata = child.lstat()
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                    raise OSError("Corrupt cache entry contains unsafe material.")
                if os.name == "nt" and metadata.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    raise OSError("Corrupt cache entry contains a reparse point.")
                total_size += metadata.st_size
            return total_size
        except (OSError, RuntimeError, ValueError) as error:
            raise PreviewCacheError(
                "PREVIEW_INTERNAL_ERROR", "Corrupt preview cache material could not be accounted safely."
            ) from error

    def _delete_verified_entry(self, candidate: _EvictionCandidate) -> None:
        try:
            record = _inspect_root(candidate.directory)
        except (OSError, RuntimeError, ValueError) as error:
            raise PreviewCacheError(
                "PREVIEW_INTERNAL_ERROR", "A cache entry changed before eviction."
            ) from error
        if record.identity != candidate.identity:
            raise PreviewCacheError("PREVIEW_INTERNAL_ERROR", "A cache entry changed before eviction.")
        verified = self._verify_entry(candidate.directory, None, None)
        verified.artifact_reader.close()
        self._delete_exact_entry(candidate.directory)

    def _delete_exact_entry(self, path: Path) -> None:
        try:
            record = _inspect_root(path)
            _verify_containment(self._root_record, record)
            children = {child.name: child for child in path.iterdir()}
            if set(children) != {_ARTIFACT_NAME, _MANIFEST_NAME}:
                raise OSError("Entry ownership is ambiguous.")
            for child in children.values():
                metadata = child.lstat()
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                    raise OSError("Entry material is not an owned regular file.")
                if os.name == "nt" and metadata.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    raise OSError("Entry material is a reparse point.")
            quarantine = self._staging_root.path / f"entry-{uuid.uuid4().hex}"
            if not _atomic_directory_publish_no_replace(path, quarantine):
                raise OSError("A unique cache cleanup quarantine already exists.")
            _fsync_directory(path.parent)
            self._remove_staging(quarantine, record.identity)
        except (OSError, RuntimeError, ValueError) as error:
            raise PreviewCacheError(
                "PREVIEW_INTERNAL_ERROR", "The exact cached preview could not be removed safely."
            ) from error

    def _remove_staging(self, path: Path, expected_identity: tuple[int, ...]) -> None:
        with self._mutex:
            self._assert_root()
            try:
                if not _lexists(path):
                    return
                record = _inspect_root(path)
                if record.identity != expected_identity:
                    raise OSError("Staging ownership changed.")
                children = list(path.iterdir())
                child_identities: dict[Path, tuple[int, int]] = {}
                for child in children:
                    if not _is_owned_staging_file(child):
                        raise OSError("Staging contains unknown material.")
                    metadata = child.lstat()
                    child_identities[child] = (metadata.st_dev, metadata.st_ino)
                for child in children:
                    metadata = child.lstat()
                    if (metadata.st_dev, metadata.st_ino) != child_identities[child]:
                        raise OSError("Staging material identity changed.")
                    child.unlink()
                path.rmdir()
            except (OSError, RuntimeError, ValueError) as error:
                raise PreviewCacheError(
                    "PREVIEW_INTERNAL_ERROR", "Owned preview staging could not be removed safely."
                ) from error

    def _recover_abandoned_staging(self) -> None:
        self._assert_directory_record(self._staging_root)
        for path in self._staging_root.path.iterdir():
            if not _STAGING_NAME.fullmatch(path.name):
                continue
            try:
                record = _inspect_root(path)
                if all(_is_owned_staging_file(child) for child in path.iterdir()):
                    self._remove_staging(path, record.identity)
            except (OSError, RuntimeError, ValueError, PreviewCacheError):
                continue

    def _entry_path(self, preview_id: str, *, create_shard: bool) -> Path:
        shard_path = self._entries_root.path / preview_id[:2]
        if create_shard:
            shard = self._ensure_directory(shard_path)
            self._assert_directory_record(shard)
        elif _lexists(shard_path):
            shard = _inspect_root(shard_path)
            _verify_containment(self._root_record, shard)
        return shard_path / preview_id

    def _write_private_file(self, path: Path, value: bytes) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor: int | None = None
        try:
            descriptor = os.open(path, flags, 0o600)
            written = 0
            while written < len(value):
                written += os.write(descriptor, value[written:])
            os.fsync(descriptor)
        except OSError as error:
            raise PreviewCacheError(
                "PREVIEW_INTERNAL_ERROR", "Private preview metadata could not be created."
            ) from error
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _ensure_directory(self, path: Path) -> _RootRecord:
        try:
            try:
                path.mkdir(mode=0o700)
            except FileExistsError:
                pass
            record = _inspect_root(path)
            _verify_containment(self._root_record, record)
            return record
        except (OSError, RuntimeError, ValueError) as error:
            raise PreviewCacheError(
                "PREVIEW_INTERNAL_ERROR", "Preview cache directory validation failed."
            ) from error

    def _assert_owned_staging(self, path: Path, identity: tuple[int, ...]) -> None:
        try:
            record = _inspect_root(path)
            _verify_containment(self._root_record, record)
        except (OSError, RuntimeError, ValueError) as error:
            raise PreviewCacheError(
                "PREVIEW_INTERNAL_ERROR", "Preview staging ownership validation failed."
            ) from error
        if record.identity != identity:
            raise PreviewCacheError("PREVIEW_INTERNAL_ERROR", "Preview staging ownership changed.")

    def _assert_directory_record(self, expected: _RootRecord) -> None:
        try:
            current = _inspect_root(expected.path)
        except (OSError, RuntimeError, ValueError) as error:
            raise PreviewCacheError(
                "PREVIEW_INTERNAL_ERROR", "Preview cache directory validation failed."
            ) from error
        if not _root_records_match(expected, current):
            raise PreviewCacheError("PREVIEW_INTERNAL_ERROR", "Preview cache directory identity changed.")

    def _assert_root(self) -> None:
        try:
            current = _inspect_root(self._root)
        except (OSError, RuntimeError, ValueError) as error:
            raise PreviewCacheError("PREVIEW_INTERNAL_ERROR", "Preview cache root validation failed.") from error
        if not _root_records_match(self._root_record, current):
            raise PreviewCacheError("PREVIEW_INTERNAL_ERROR", "Preview cache root identity changed.")
        if self._process_lock_handle is not None:
            try:
                self._validate_lock_path_shape(allow_missing=False)
                path_metadata = (self._root / _LOCK_NAME).lstat()
                handle_metadata = os.fstat(self._process_lock_handle.fileno())
            except (OSError, ValueError) as error:
                raise PreviewCacheError(
                    "PREVIEW_INTERNAL_ERROR", "Preview cache ownership lock validation failed."
                ) from error
            current_identity = (path_metadata.st_dev, path_metadata.st_ino)
            handle_identity = (handle_metadata.st_dev, handle_metadata.st_ino)
            if (
                self._lock_identity is None
                or current_identity != self._lock_identity
                or handle_identity != self._lock_identity
                or path_metadata.st_nlink != 1
            ):
                raise PreviewCacheError("PREVIEW_INTERNAL_ERROR", "Preview cache ownership lock changed.")

    def _assert_open(self) -> None:
        if self._closed:
            raise PreviewCacheError("PREVIEW_INTERNAL_ERROR", "Preview cache storage is closed.")

    def _verify_writable(self) -> None:
        probe = self._root / f".preview-cache-write-{uuid.uuid4().hex}"
        descriptor: int | None = None
        created_identity: tuple[int, int] | None = None
        try:
            descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            metadata = os.fstat(descriptor)
            created_identity = (metadata.st_dev, metadata.st_ino)
            os.fsync(descriptor)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if created_identity is not None and _lexists(probe):
                metadata = probe.lstat()
                if (
                    stat.S_ISLNK(metadata.st_mode)
                    or not stat.S_ISREG(metadata.st_mode)
                    or (metadata.st_dev, metadata.st_ino) != created_identity
                ):
                    raise OSError("Preview cache write probe identity changed.")
                probe.unlink()

    def _claim_process_root(self) -> None:
        with _PROCESS_ROOTS_LOCK:
            if self._root_record.identity in _PROCESS_ROOTS:
                raise PreviewCacheError(
                    "PREVIEW_INTERNAL_ERROR", "Preview cache storage is already owned by this process."
                )
            _PROCESS_ROOTS.add(self._root_record.identity)
            self._registered_root_identity = self._root_record.identity

    def _release_process_root(self) -> None:
        identity = self._registered_root_identity
        if identity is None:
            return
        with _PROCESS_ROOTS_LOCK:
            _PROCESS_ROOTS.discard(identity)
        self._registered_root_identity = None

    def _acquire_process_lock(self) -> None:
        self._validate_lock_path_shape(allow_missing=True)
        lock = portalocker.Lock(str(self._root / _LOCK_NAME), mode="a", timeout=0)
        self._process_lock_handle = lock.acquire()
        self._process_lock = lock
        self._validate_lock_path_shape(allow_missing=False)
        path_metadata = (self._root / _LOCK_NAME).lstat()
        handle_metadata = os.fstat(self._process_lock_handle.fileno())
        self._lock_identity = (path_metadata.st_dev, path_metadata.st_ino)
        if self._lock_identity != (handle_metadata.st_dev, handle_metadata.st_ino):
            raise ValueError("Preview cache ownership lock identity is inconsistent.")

    def _validate_lock_path_shape(self, *, allow_missing: bool) -> None:
        path = self._root / _LOCK_NAME
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            if allow_missing:
                return
            raise
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("Preview cache ownership lock is not a private regular file.")
        if os.name == "nt" and metadata.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("Preview cache ownership lock is a reparse point.")

    def _release_process_lock(self) -> None:
        lock = self._process_lock
        self._process_lock = None
        self._process_lock_handle = None
        self._lock_identity = None
        if lock is not None:
            lock.release()

    def _release_initialization(self) -> None:
        try:
            self._release_process_lock()
        finally:
            self._release_process_root()

    def _unpin(self, preview_id: str) -> None:
        with self._mutex:
            count = self._pins.get(preview_id, 0)
            if count <= 1:
                self._pins.pop(preview_id, None)
            else:
                self._pins[preview_id] = count - 1

    def _release_staging(self, identity: tuple[int, ...]) -> None:
        with self._mutex:
            self._active_staging.discard(identity)

    def _call_hook(self, event: str) -> None:
        if self._event_hook is not None:
            self._event_hook(event)


def _manifest(
    identity: PreviewCacheIdentity,
    artifact_sha256: str,
    byte_size: int,
    width: int,
    height: int,
) -> dict[str, object]:
    return {
        "contract_version": PREVIEW_CACHE_MANIFEST_VERSION,
        "preview_id": identity.preview_id,
        "descriptor": identity.descriptor.to_dict(),
        "artifact": {
            "sha256": artifact_sha256,
            "byte_size": byte_size,
            "width": width,
            "height": height,
            "media_type": "image/png",
        },
    }


def _validate_manifest_structure(value: Any) -> None:
    if type(value) is not dict or set(value) != _MANIFEST_FIELDS:
        raise ValueError("Manifest fields are invalid.")
    if value["contract_version"] != PREVIEW_CACHE_MANIFEST_VERSION:
        raise ValueError("Manifest version is unsupported.")
    if type(value["preview_id"]) is not str or not _SHA256.fullmatch(value["preview_id"]):
        raise ValueError("Manifest preview ID is invalid.")
    descriptor = value["descriptor"]
    if type(descriptor) is not dict or set(descriptor) != _DESCRIPTOR_FIELDS:
        raise ValueError("Manifest descriptor fields are invalid.")
    if descriptor["contract_version"] != PREVIEW_CACHE_KEY_VERSION:
        raise ValueError("Manifest cache-key version is unsupported.")
    if type(descriptor["source_sha256"]) is not str or not _SHA256.fullmatch(descriptor["source_sha256"]):
        raise ValueError("Manifest source digest is invalid.")
    treatment = descriptor["treatment"]
    if type(treatment) is not dict or set(treatment) != _TREATMENT_FIELDS:
        raise ValueError("Manifest treatment fields are invalid.")
    intensity = treatment["intensity"]
    if (
        type(intensity) is not float
        or not math.isfinite(intensity)
        or not 0.0 <= intensity <= 0.6
        or (intensity == 0.0 and math.copysign(1.0, intensity) < 0.0)
        or treatment["resolver_version"] != RESOLVER_VERSION
        or treatment["preset_mapping_version"] != PRESET_MAPPING_VERSION
    ):
        raise ValueError("Manifest treatment metadata is invalid.")
    if treatment["state"] == "untreated":
        if treatment["resolved_hex"] is not None or intensity != 0.0:
            raise ValueError("Manifest untreated identity is inconsistent.")
    elif treatment["state"] == "treated":
        if type(treatment["resolved_hex"]) is not str or not re.fullmatch(r"#[0-9A-F]{6}", treatment["resolved_hex"]):
            raise ValueError("Manifest treated identity is inconsistent.")
    else:
        raise ValueError("Manifest treatment state is invalid.")
    render_policy = descriptor["render_policy"]
    if type(render_policy) is not dict or render_policy != PreviewRenderPolicy().to_dict():
        raise ValueError("Manifest render policy is unsupported.")
    toolchain = descriptor["toolchain"]
    if type(toolchain) is not dict or set(toolchain) != _TOOLCHAIN_FIELDS:
        raise ValueError("Manifest toolchain fields are invalid.")
    if any(type(toolchain[name]) is not str or not _SHA256.fullmatch(toolchain[name]) for name in _TOOLCHAIN_FIELDS):
        raise ValueError("Manifest toolchain digest is invalid.")
    artifact = value["artifact"]
    if type(artifact) is not dict or set(artifact) != _ARTIFACT_FIELDS:
        raise ValueError("Manifest artifact fields are invalid.")
    if type(artifact["sha256"]) is not str or not _SHA256.fullmatch(artifact["sha256"]):
        raise ValueError("Manifest artifact digest is invalid.")
    if type(artifact["byte_size"]) is not int or artifact["byte_size"] < 1:
        raise ValueError("Manifest artifact size is invalid.")
    _dimension(artifact["width"])
    _dimension(artifact["height"])
    if artifact["media_type"] != "image/png":
        raise ValueError("Manifest media type is invalid.")


def _validate_png(value: bytes) -> tuple[int, int]:
    stream = io.BytesIO(value)
    reader = _Reader(
        identity=(0, 0),
        size=len(value),
        links=1,
        read=stream.read,
        seek=stream.seek,
        close=stream.close,
    )
    try:
        _, _, width, height = _inspect_png_reader(reader, len(value), None)
        return width, height
    finally:
        reader.close()


def _inspect_png_reader(
    reader: _Reader,
    limit: int,
    cancel_event: Any,
) -> tuple[str, int, int, int]:
    """Stream and validate an 8-bit RGB/RGBA Phase 2 PNG without loading it whole."""
    if reader.size < len(_PNG_SIGNATURE) + 12 or reader.size > limit:
        raise ValueError("PNG size is outside the configured bound.")
    reader.seek(0, os.SEEK_SET)
    digest = hashlib.sha256()
    consumed = 0

    def read_exact(amount: int) -> bytes:
        nonlocal consumed
        if amount < 0 or consumed + amount > reader.size or consumed + amount > limit:
            raise ValueError("PNG chunk is truncated.")
        parts: list[bytes] = []
        remaining = amount
        while remaining:
            _raise_if_cancelled(cancel_event)
            chunk = reader.read(min(remaining, _READ_CHUNK))
            if not chunk:
                raise ValueError("PNG chunk is truncated.")
            if len(chunk) > remaining:
                raise ValueError("PNG reader exceeded the requested boundary.")
            digest.update(chunk)
            consumed += len(chunk)
            remaining -= len(chunk)
            parts.append(chunk)
        return b"".join(parts)

    if read_exact(len(_PNG_SIGNATURE)) != _PNG_SIGNATURE:
        raise ValueError("PNG signature is invalid.")
    width = height = channels = color_type = None
    saw_ihdr = saw_plte = saw_idat = saw_iend = False
    idat_closed = False
    decompressor = zlib.decompressobj()
    decompressed = bytearray()
    while consumed < reader.size:
        header = read_exact(8)
        length = struct.unpack(">I", header[:4])[0]
        chunk_type = header[4:]
        if not re.fullmatch(rb"[A-Za-z]{4}", chunk_type) or length + 4 > reader.size - consumed:
            raise ValueError("PNG chunk is invalid or truncated.")
        if chunk_type[2:3].islower():
            raise ValueError("PNG chunk uses the reserved naming bit.")
        if not saw_ihdr:
            if chunk_type != b"IHDR" or length != 13:
                raise ValueError("PNG IHDR is invalid.")
        elif chunk_type == b"IHDR":
            raise ValueError("PNG contains multiple IHDR chunks.")
        if chunk_type in {b"acTL", b"fcTL", b"fdAT"}:
            raise ValueError("Animated PNG is unsupported.")
        if chunk_type[:1].isupper() and chunk_type not in {b"IHDR", b"PLTE", b"IDAT", b"IEND"}:
            raise ValueError("PNG contains an unknown critical chunk.")
        if chunk_type == b"PLTE":
            if saw_plte or saw_idat:
                raise ValueError("PNG palette placement is invalid.")
            if length < 3 or length > 256 * 3 or length % 3:
                raise ValueError("PNG palette length is invalid.")
            if color_type not in {2, 6}:
                raise ValueError("PNG palette is invalid for its color type.")
            saw_plte = True
        crc = zlib.crc32(chunk_type)
        chunk_remaining = length
        ihdr = bytearray()
        while chunk_remaining:
            part = read_exact(min(chunk_remaining, _READ_CHUNK))
            crc = zlib.crc32(part, crc)
            chunk_remaining -= len(part)
            if chunk_type == b"IHDR":
                ihdr.extend(part)
            elif chunk_type == b"IDAT":
                if width is None or height is None or channels is None:
                    raise ValueError("PNG IDAT precedes IHDR.")
                expected_pixels = height * (1 + width * channels)
                remaining_output = expected_pixels - len(decompressed) + 1
                if remaining_output <= 0:
                    raise ValueError("PNG pixel stream exceeds its dimensions.")
                decompressed.extend(decompressor.decompress(part, remaining_output))
                if decompressor.unconsumed_tail or decompressor.unused_data or len(decompressed) > expected_pixels:
                    raise ValueError("PNG pixel stream exceeds its dimensions.")
        expected_crc = struct.unpack(">I", read_exact(4))[0]
        if crc & 0xFFFFFFFF != expected_crc:
            raise ValueError("PNG chunk checksum is invalid.")
        if not saw_ihdr:
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", ihdr
            )
            if (
                not 1 <= width <= STILL_OUTPUT_MAX_DIMENSION
                or not 1 <= height <= STILL_OUTPUT_MAX_DIMENSION
                or bit_depth != 8
                or color_type not in {2, 6}
                or compression != 0
                or filtering != 0
                or interlace != 0
            ):
                raise ValueError("PNG encoding is unsupported.")
            channels = 3 if color_type == 2 else 4
            saw_ihdr = True
        elif chunk_type == b"IDAT":
            if idat_closed or saw_iend:
                raise ValueError("PNG IDAT chunks are not contiguous.")
            saw_idat = True
        elif saw_idat:
            idat_closed = True
        if chunk_type == b"IEND":
            if length != 0 or saw_iend or consumed != reader.size:
                raise ValueError("PNG IEND is invalid or trailing material exists.")
            saw_iend = True
    if not saw_ihdr or not saw_idat or not saw_iend or not decompressor.eof:
        raise ValueError("PNG structure is incomplete.")
    decompressed.extend(decompressor.flush())
    assert width is not None and height is not None and channels is not None
    row_size = 1 + width * channels
    if len(decompressed) != height * row_size or any(decompressed[row * row_size] > 4 for row in range(height)):
        raise ValueError("PNG pixel stream size is inconsistent.")
    return digest.hexdigest(), consumed, width, height


def _open_regular_file(path: Path, root: _RootRecord) -> _Reader:
    if os.name == "nt":
        from wrld_video_studio.infrastructure.artwork_sources import (
            _verify_windows_containment,
            _win32_modules,
            _windows_identity,
        )

        win32file, win32con = _win32_modules()
        handle = win32file.CreateFile(
            str(path),
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
                raise OSError("Cached material is not a regular non-reparse file.")
            _verify_windows_containment(root, win32file.GetFinalPathNameByHandle(handle, 0))
            size = (int(info[5]) << 32) | int(info[6])

            def read(amount: int) -> bytes:
                _, data = win32file.ReadFile(handle, amount)
                return bytes(data)

            def seek(offset: int, whence: int) -> int:
                mapping = {os.SEEK_SET: win32file.FILE_BEGIN, os.SEEK_CUR: win32file.FILE_CURRENT, os.SEEK_END: win32file.FILE_END}
                if whence not in mapping:
                    raise ValueError("Unsupported seek origin.")
                return int(win32file.SetFilePointer(handle, offset, mapping[whence]))

            return _Reader(_windows_identity(info), size, int(info[7]), read, seek, handle.Close)
        except Exception:
            handle.Close()
            raise
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_BINARY", 0),
    )
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("Cached material is not a regular file.")
        resolved = path.resolve(strict=True)
        root_resolved = Path(root.final_path or root.path).resolve(strict=True)
        if os.path.commonpath((str(root_resolved), str(resolved))) != str(root_resolved):
            raise OSError("Cached material escaped its trusted root.")
        return _Reader(
            (metadata.st_dev, metadata.st_ino),
            metadata.st_size,
            metadata.st_nlink,
            lambda amount: os.read(descriptor, amount),
            lambda offset, whence: os.lseek(descriptor, offset, whence),
            lambda: os.close(descriptor),
        )
    except Exception:
        os.close(descriptor)
        raise


def _read_all(reader: _Reader, limit: int, cancel_event: Any) -> bytes:
    if reader.size > limit:
        raise ValueError("Cached material exceeds its configured bound.")
    reader.seek(0, os.SEEK_SET)
    chunks: list[bytes] = []
    total = 0
    while True:
        _raise_if_cancelled(cancel_event)
        chunk = reader.read(_READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ValueError("Cached material exceeds its configured bound.")
        chunks.append(chunk)
    if total != reader.size:
        raise ValueError("Cached material changed while being read.")
    return b"".join(chunks)


def _atomic_directory_publish_no_replace(source: Path, destination: Path) -> bool:
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move_file_ex = kernel32.MoveFileExW
        move_file_ex.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint)
        move_file_ex.restype = ctypes.c_int
        if move_file_ex(str(source), str(destination), 0x8):  # MOVEFILE_WRITE_THROUGH, never REPLACE_EXISTING
            return True
        error_number = ctypes.get_last_error()
        if error_number in {80, 183}:
            return False
        raise OSError(error_number, "Atomic preview directory publication failed.")
    if not sys.platform.startswith("linux"):
        raise RuntimeError("Atomic no-replace directory publication is unsupported on this platform.")
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = libc.renameat2
    except AttributeError as error:
        raise RuntimeError("renameat2 is unavailable for atomic preview publication.") from error
    renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    renameat2.restype = ctypes.c_int
    if renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1) == 0:  # RENAME_NOREPLACE
        return True
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        return False
    if error_number in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}:
        raise RuntimeError("Atomic no-replace directory publication is unsupported.")
    raise OSError(error_number, "Atomic preview directory publication failed.")


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _verify_containment(root: _RootRecord, child: _RootRecord) -> None:
    if os.name == "nt":
        root_text = os.path.normcase(os.path.normpath(root.final_path or str(root.path))).rstrip("\\/")
        child_text = os.path.normcase(os.path.normpath(child.final_path or str(child.path)))
        if child_text != root_text and not child_text.startswith(root_text + "\\"):
            raise ValueError("Preview cache material escaped its root.")
        return
    root_text = str(Path(root.final_path or root.path).resolve(strict=True))
    child_text = str(Path(child.final_path or child.path).resolve(strict=True))
    if os.path.commonpath((root_text, child_text)) != root_text:
        raise ValueError("Preview cache material escaped its root.")


def _is_owned_staging_file(path: Path) -> bool:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        return False
    if os.name == "nt" and metadata.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        return False
    return path.name in {_ARTIFACT_NAME, _MANIFEST_NAME} or (
        path.name.startswith(".preview.") and path.name.endswith(".partial.png")
    )


def _dimension(value: Any) -> int:
    if type(value) is not int or not 1 <= value <= STILL_OUTPUT_MAX_DIMENSION:
        raise ValueError("Preview dimensions must be bounded positive integers.")
    return value


def _require_identity(value: Any) -> PreviewCacheIdentity:
    if not isinstance(value, PreviewCacheIdentity):
        raise TypeError("A trusted PreviewCacheIdentity is required.")
    return value


def _raise_if_cancelled(cancel_event: Any) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise PreviewCacheError("PREVIEW_CANCELLED", "Preview cache operation was cancelled.")


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)
