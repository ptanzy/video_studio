from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
import portalocker

from wrld_video_studio.domain.errors import IndeterminateCommitError, StudioError


class OverrideStore:
    """Revisioned JSON store with process-local and exclusive-file write guards."""

    def __init__(
        self,
        root: str | Path,
        schema_path: str | Path,
        *,
        replace: Callable[[str | os.PathLike[str], str | os.PathLike[str]], None] = os.replace,
        sync_directory: Callable[[Path], None] | None = None,
    ) -> None:
        self.root = Path(root)
        self.schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(self.schema)
        self.validator = Draft202012Validator(self.schema)
        self.replace = replace
        self.sync_directory = sync_directory or self._sync_directory
        self._guard = threading.Lock()
        self._album_locks: dict[str, threading.Lock] = {}

    def read(self, album_id: str) -> dict[str, Any]:
        path = self._store_path(album_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise StudioError(
                "STORAGE_ERROR", "Override store does not exist.", {"album_id": album_id}
            ) from None
        except (OSError, json.JSONDecodeError) as error:
            raise StudioError(
                "STORAGE_ERROR", "Override store could not be read.", {"album_id": album_id}
            ) from error
        self._validate(value, album_id)
        return value

    def create(self, album_id: str) -> dict[str, Any]:
        initial = {
            "schema_version": "1.0",
            "album_id": album_id,
            "revision": 0,
            "overrides": {},
        }
        self._write_new(initial)
        return initial

    def update(
        self,
        album_id: str,
        expected_revision: int,
        overrides: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._ensure_root(album_id)
        lock = self._album_lock(album_id)
        committed: dict[str, Any] | None = None
        with lock:
            try:
                with self._writer_lock(album_id):
                    committed = self._update_locked(album_id, expected_revision, overrides)
                return committed
            except IndeterminateCommitError:
                raise
            except StudioError:
                raise
            except portalocker.exceptions.LockException as error:
                if committed is not None:
                    raise self._indeterminate_error(album_id, committed["revision"], error) from error
                raise StudioError(
                    "STORAGE_ERROR",
                    "Another writer is active for this album; retry after it completes.",
                    {"album_id": album_id},
                ) from error
            except Exception as error:
                if committed is not None:
                    raise self._indeterminate_error(album_id, committed["revision"], error) from error
                raise self._storage_error(album_id, error) from error

    def _update_locked(
        self,
        album_id: str,
        expected_revision: int,
        overrides: Mapping[str, Any],
    ) -> dict[str, Any]:
        current = self.read(album_id)
        if current["revision"] != expected_revision:
            raise StudioError(
                "REVISION_CONFLICT",
                "Stored revision differs from expected revision.",
                {
                    "expected_revision": expected_revision,
                    "actual_revision": current["revision"],
                },
            )
        updated = {
            "schema_version": "1.0",
            "album_id": album_id,
            "revision": current["revision"] + 1,
            "overrides": dict(overrides),
        }
        self._validate(updated, album_id)
        self._atomic_write(self._store_path(album_id), updated)
        return updated

    def _write_new(self, value: dict[str, Any]) -> None:
        album_id = value["album_id"]
        self._ensure_root(album_id)
        lock = self._album_lock(album_id)
        committed = False
        with lock:
            try:
                with self._writer_lock(album_id):
                    path = self._store_path(album_id)
                    if path.exists():
                        raise StudioError(
                            "STORAGE_ERROR", "Override store already exists.", {"album_id": album_id}
                        )
                    self._validate(value, album_id)
                    self._atomic_write(path, value)
                    committed = True
            except IndeterminateCommitError:
                raise
            except StudioError:
                raise
            except portalocker.exceptions.LockException as error:
                if committed:
                    raise self._indeterminate_error(album_id, value["revision"], error) from error
                raise StudioError(
                    "STORAGE_ERROR",
                    "Another writer is active for this album; retry after it completes.",
                    {"album_id": album_id},
                ) from error
            except Exception as error:
                if committed:
                    raise self._indeterminate_error(album_id, value["revision"], error) from error
                raise self._storage_error(album_id, error) from error

    @contextmanager
    def _writer_lock(self, album_id: str):
        if os.name == "nt":
            import win32api
            import win32event

            mutex_name = f"Local\\WRLDVideoStudio-{self._lock_key(album_id)}"
            mutex = win32event.CreateMutex(None, False, mutex_name)
            process_id = os.getpid()
            thread_id = threading.get_native_id()
            try:
                result = win32event.WaitForSingleObject(mutex, 0)
                if result == win32event.WAIT_TIMEOUT:
                    raise StudioError(
                        "STORAGE_ERROR",
                        "Another writer is active for this album; retry after it completes.",
                        {
                            "album_id": album_id,
                            "process_id": process_id,
                            "thread_id": thread_id,
                            "mutex_name": mutex_name,
                            "wait_result": "WAIT_TIMEOUT",
                        },
                    )
                if result == win32event.WAIT_FAILED:
                    error_code = win32api.GetLastError()
                    raise OSError(error_code, "WaitForSingleObject failed")
                if result == win32event.WAIT_OBJECT_0:
                    wait_result = "WAIT_OBJECT_0"
                elif result == win32event.WAIT_ABANDONED:
                    wait_result = "WAIT_ABANDONED"
                else:
                    raise OSError(f"Unexpected mutex wait result: {result}")
                try:
                    yield {
                        "process_id": process_id,
                        "thread_id": thread_id,
                        "mutex_name": mutex_name,
                        "wait_result": wait_result,
                    }
                finally:
                    if threading.get_native_id() != thread_id:
                        raise RuntimeError("Windows mutex must be released by its acquiring thread")
                    win32event.ReleaseMutex(mutex)
            finally:
                win32api.CloseHandle(mutex)
            return

        lock = portalocker.Lock(str(self._lock_path(album_id)), mode="a", timeout=0)
        with lock:
            yield {
                "process_id": os.getpid(),
                "thread_id": threading.get_native_id(),
                "mutex_name": str(self._lock_path(album_id).resolve()),
                "wait_result": "LOCK_ACQUIRED",
            }

    def _atomic_write(self, path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._validate_json_value(value, path)
        temp_path: str | None = None
        replaced = False
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temp_path = temporary.name
                json.dump(
                    value,
                    temporary,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                )
                temporary.flush()
                os.fsync(temporary.fileno())
            self.replace(temp_path, path)
            temp_path = None
            replaced = True
            self.sync_directory(path.parent)
        except Exception as error:
            if replaced:
                raise self._indeterminate_error(value["album_id"], value["revision"], error) from error
            raise
        finally:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    pass

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        if os.name == "nt":
            return
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @staticmethod
    def _validate_json_value(value: Any, path: Path) -> None:
        def validate(item: Any, location: str) -> None:
            if item is None or type(item) in (str, bool, int):
                return
            if type(item) is float:
                if not (float("-inf") < item < float("inf")):
                    raise ValueError(f"Non-finite number at {location}")
                return
            if type(item) is list:
                for index, child in enumerate(item):
                    validate(child, f"{location}[{index}]")
                return
            if type(item) is dict:
                for key, child in item.items():
                    if type(key) is not str:
                        raise ValueError(f"Non-string object key at {location}")
                    validate(child, f"{location}.{key}")
                return
            raise ValueError(f"Unsupported JSON value at {location}: {type(item).__name__}")

        validate(value, str(path))
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        encoded.encode("utf-8", errors="strict")
        decoded = json.loads(encoded, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
        if not OverrideStore._json_values_equal(value, decoded):
            raise ValueError(f"JSON round trip changed value for {path}")

    @staticmethod
    def _json_values_equal(original: Any, decoded: Any) -> bool:
        if type(original) is not type(decoded):
            return False
        if type(original) is dict:
            return original.keys() == decoded.keys() and all(
                OverrideStore._json_values_equal(original[key], decoded[key]) for key in original
            )
        if type(original) is list:
            return len(original) == len(decoded) and all(
                OverrideStore._json_values_equal(left, right)
                for left, right in zip(original, decoded)
            )
        return original == decoded

    def _ensure_root(self, album_id: str) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise self._storage_error(album_id, error) from error

    def _validate(self, value: Any, album_id: str) -> None:
        errors = list(self.validator.iter_errors(value))
        if errors or not isinstance(value, dict) or value.get("album_id") != album_id:
            reason = (
                errors[0].message
                if errors
                else "album_id does not match the requested store"
            )
            raise StudioError(
                "STORAGE_ERROR", "Override store violates its schema.", {"reason": reason}
            )

    def _store_path(self, album_id: str) -> Path:
        key = hashlib.sha256(album_id.encode("utf-8")).hexdigest()
        return self.root / f"{key}.json"

    def _lock_path(self, album_id: str) -> Path:
        return self.root / f"{self._lock_key(album_id)}.lock"

    def _lock_key(self, album_id: str) -> str:
        identity = f"{self.root.resolve()}\0{album_id}"
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def _album_lock(self, album_id: str) -> threading.Lock:
        with self._guard:
            return self._album_locks.setdefault(album_id, threading.Lock())

    @staticmethod
    def _storage_error(album_id: str, error: BaseException) -> StudioError:
        return StudioError(
            "STORAGE_ERROR", "Override store could not be updated.", {"album_id": album_id}
        )

    @staticmethod
    def _indeterminate_error(
        album_id: str, revision: int, error: BaseException
    ) -> IndeterminateCommitError:
        return IndeterminateCommitError(
            "Override file was replaced, but completion could not be confirmed.",
            {"album_id": album_id, "revision": revision, "commit_state": "indeterminate"},
        )
