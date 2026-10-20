from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
import portalocker

from wrld_video_studio.domain.canonical_json import canonical_json_bytes
from wrld_video_studio.domain.jobs import (
    InputFingerprint,
    JobState,
    JobStatus,
    RenderSnapshot,
    create_snapshot,
)
from wrld_video_studio.domain.media_errors import (
    IndeterminateMediaCommitError,
    MediaInfrastructureError,
)


_LOCKS_GUARD = threading.Lock()
_ROOT_LOCKS: dict[str, threading.RLock] = {}
_WORKER_LOCKS: dict[str, threading.Lock] = {}
_PUBLICATION_LOCKS: dict[str, threading.Lock] = {}


class JsonJobRepository:
    """Durable snapshots and revisioned statuses with cross-process writer guards."""

    def __init__(
        self,
        root: str | Path,
        snapshot_schema_path: str | Path,
        status_schema_path: str | Path,
        *,
        replace: Callable[[str | os.PathLike[str], str | os.PathLike[str]], None] = os.replace,
        sync_directory: Callable[[Path], None] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.snapshot_schema = self._load_schema(snapshot_schema_path)
        self.status_schema = self._load_schema(status_schema_path)
        self.snapshot_validator = Draft202012Validator(
            self.snapshot_schema, format_checker=FormatChecker()
        )
        self.status_validator = Draft202012Validator(
            self.status_schema, format_checker=FormatChecker()
        )
        self.replace = replace
        self.sync_directory = sync_directory or self._sync_directory
        key = str(self.root)
        with _LOCKS_GUARD:
            self._root_lock = _ROOT_LOCKS.setdefault(key, threading.RLock())
            self._worker_thread_lock = _WORKER_LOCKS.setdefault(key, threading.Lock())
        self._writer_lock_path = self.root / ".writer.lock"
        self._worker_lock_path = self.root / ".worker.lock"
        self._publication_root = self.root / ".publication-locks"

    @contextmanager
    def worker_lock(self):
        if not self._worker_thread_lock.acquire(blocking=False):
            raise MediaInfrastructureError(
                "WORKER_ALREADY_ACTIVE", "Another worker owns this job repository."
            )
        try:
            with portalocker.Lock(str(self._worker_lock_path), mode="a", timeout=0):
                yield
        except portalocker.exceptions.LockException as error:
            raise MediaInfrastructureError(
                "WORKER_ALREADY_ACTIVE", "Another worker owns this job repository."
            ) from error
        finally:
            self._worker_thread_lock.release()

    @contextmanager
    def _writer_guard(self):
        try:
            with portalocker.Lock(str(self._writer_lock_path), mode="a", timeout=0):
                yield
        except portalocker.exceptions.LockException as error:
            raise MediaInfrastructureError(
                "REPOSITORY_BUSY", "Another process is updating this job repository."
            ) from error

    @contextmanager
    def publication_lock(self, job_id: str, attempt_id: str):
        key = f"{self.root}:{self._key(job_id)}:{self._key(attempt_id)}"
        with _LOCKS_GUARD:
            thread_lock = _PUBLICATION_LOCKS.setdefault(key, threading.Lock())
        thread_lock.acquire()
        lock_path = self._publication_root / f"{self._key(job_id)}-{self._key(attempt_id)}.lock"
        try:
            self._publication_root.mkdir(parents=True, exist_ok=True)
            with portalocker.Lock(str(lock_path), mode="a"):
                yield
        except portalocker.exceptions.LockException as error:
            raise MediaInfrastructureError(
                "PUBLICATION_BUSY", "Could not acquire the attempt publication lock."
            ) from error
        finally:
            thread_lock.release()

    def create(self, snapshot: RenderSnapshot, status: JobStatus) -> None:
        self._validate(snapshot.to_dict(), self.snapshot_validator, "snapshot")
        self._validate(status.to_dict(), self.status_validator, "status")
        if status.snapshot_digest != snapshot.snapshot_digest:
            raise MediaInfrastructureError("INVALID_JOB", "Status snapshot digest does not match.")
        if status.job_id != snapshot.job_id or status.attempt_id != snapshot.attempt_id:
            raise MediaInfrastructureError("INVALID_JOB", "Snapshot and status identity differ.")

        with self._root_lock, self._writer_guard():
            snapshot_path, status_path = self._attempt_paths(
                snapshot.job_id, snapshot.attempt_id
            )
            if snapshot_path.exists() or status_path.exists():
                raise MediaInfrastructureError("JOB_ALREADY_EXISTS", "Job attempt already exists.")
            self._atomic_write(snapshot_path, snapshot.to_dict())
            try:
                self._atomic_write(status_path, status.to_dict())
            except IndeterminateMediaCommitError:
                raise
            except Exception as error:
                try:
                    snapshot_path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise self._storage_error("Could not persist initial job status.", error) from error

    def get(self, job_id: str) -> tuple[RenderSnapshot, JobStatus]:
        with self._root_lock:
            attempts = self._attempt_directories(job_id)
            if not attempts:
                raise MediaInfrastructureError("JOB_NOT_FOUND", "Job does not exist.")
            records = [self._read_attempt_dir(path) for path in attempts]
            return max(records, key=lambda item: item[1].updated_at)

    def get_attempt(
        self, job_id: str, attempt_id: str
    ) -> tuple[RenderSnapshot, JobStatus]:
        snapshot_path, status_path = self._attempt_paths(job_id, attempt_id)
        with self._root_lock:
            if not snapshot_path.is_file() or not status_path.is_file():
                raise MediaInfrastructureError("JOB_NOT_FOUND", "Job attempt does not exist.")
            return self._read_pair(snapshot_path, status_path)

    def update_status(self, status: JobStatus, expected_revision: int) -> JobStatus:
        _, status_path = self._attempt_paths(status.job_id, status.attempt_id)
        with self._root_lock, self._writer_guard():
            current = self._read_json(status_path)
            actual_revision = current.get("revision")
            if actual_revision != expected_revision:
                raise MediaInfrastructureError(
                    "REVISION_CONFLICT",
                    "Stored job revision differs from expected revision.",
                    {"expected_revision": expected_revision, "actual_revision": actual_revision},
                )
            if status.revision != expected_revision + 1:
                raise MediaInfrastructureError(
                    "REVISION_CONFLICT",
                    "New job status must increment the revision exactly once.",
                )
            self._write_status(status_path, status)
            return status

    def find_by_request_digest(
        self, request_digest: str
    ) -> tuple[RenderSnapshot, JobStatus] | None:
        matches: list[tuple[RenderSnapshot, JobStatus]] = []
        with self._root_lock:
            for job_dir in self.root.iterdir():
                if not job_dir.is_dir():
                    continue
                for attempt_dir in job_dir.glob("attempts/*"):
                    snapshot_path = attempt_dir / "snapshot.json"
                    status_path = attempt_dir / "status.json"
                    if snapshot_path.is_file() and status_path.is_file():
                        pair = self._read_pair(snapshot_path, status_path)
                        if pair[0].request_digest == request_digest:
                            matches.append(pair)
        if not matches:
            return None
        return max(matches, key=lambda item: item[1].updated_at)

    def queued(self) -> list[tuple[RenderSnapshot, JobStatus]]:
        matches: list[tuple[RenderSnapshot, JobStatus]] = []
        with self._root_lock:
            for job_dir in self.root.iterdir():
                if not job_dir.is_dir():
                    continue
                for attempt_dir in job_dir.glob("attempts/*"):
                    snapshot_path = attempt_dir / "snapshot.json"
                    status_path = attempt_dir / "status.json"
                    if snapshot_path.is_file() and status_path.is_file():
                        pair = self._read_pair(snapshot_path, status_path)
                        if pair[1].status is JobState.QUEUED:
                            matches.append(pair)
        return sorted(matches, key=lambda item: item[1].created_at)

    def claim_next(self) -> tuple[RenderSnapshot, JobStatus] | None:
        with self._root_lock, self._writer_guard():
            for job_dir in self.root.iterdir():
                attempts_dir = job_dir / "attempts"
                if not job_dir.is_dir() or not attempts_dir.is_dir():
                    continue
                for attempt_dir in attempts_dir.iterdir():
                    status_path = attempt_dir / "status.json"
                    if not status_path.is_file():
                        continue
                    current = self._read_json(status_path)
                    if current.get("status") in {
                        JobState.RUNNING.value,
                        JobState.VALIDATING.value,
                        JobState.CANCEL_REQUESTED.value,
                    }:
                        return None
            queued: list[tuple[RenderSnapshot, JobStatus, Path]] = []
            for job_dir in self.root.iterdir():
                attempts_dir = job_dir / "attempts"
                if not job_dir.is_dir() or not attempts_dir.is_dir():
                    continue
                for attempt_dir in attempts_dir.iterdir():
                    snapshot_path = attempt_dir / "snapshot.json"
                    status_path = attempt_dir / "status.json"
                    if snapshot_path.is_file() and status_path.is_file():
                        snapshot, status = self._read_pair(snapshot_path, status_path)
                        if status.status is JobState.QUEUED:
                            queued.append((snapshot, status, status_path))
            queued.sort(key=lambda item: item[1].created_at)
            for snapshot, status, status_path in queued:
                running = status.transition(JobState.RUNNING)
                self._write_status(status_path, running)
                return snapshot, running
        return None

    def _write_status(self, status_path: Path, status: JobStatus) -> None:
        self._validate(status.to_dict(), self.status_validator, "status")
        self._atomic_write(status_path, status.to_dict())

    def attempts(self, job_id: str) -> list[tuple[RenderSnapshot, JobStatus]]:
        return [self._read_attempt_dir(path) for path in self._attempt_directories(job_id)]

    def all_attempts(self) -> list[tuple[RenderSnapshot, JobStatus]]:
        results: list[tuple[RenderSnapshot, JobStatus]] = []
        with self._root_lock:
            for job_dir in self.root.iterdir():
                if job_dir.is_dir():
                    results.extend(self._read_attempt_dir(path) for path in self._attempt_directories_from_job(job_dir))
        return results

    def get_attempt_from_directory(
        self, attempt_dir: Path
    ) -> tuple[RenderSnapshot, JobStatus]:
        return self._read_attempt_dir(attempt_dir)

    def _attempt_directories(self, job_id: str) -> list[Path]:
        path = self.root / self._key(job_id)
        return self._attempt_directories_from_job(path)

    @staticmethod
    def _attempt_directories_from_job(path: Path) -> list[Path]:
        attempts_path = path / "attempts"
        if not attempts_path.is_dir():
            return []
        return sorted((item for item in attempts_path.iterdir() if item.is_dir()))

    def _read_attempt_dir(self, attempt_dir: Path) -> tuple[RenderSnapshot, JobStatus]:
        return self._read_pair(attempt_dir / "snapshot.json", attempt_dir / "status.json")

    def _read_pair(self, snapshot_path: Path, status_path: Path) -> tuple[RenderSnapshot, JobStatus]:
        snapshot_data = self._read_json(snapshot_path)
        status_data = self._read_json(status_path)
        self._validate(snapshot_data, self.snapshot_validator, "snapshot")
        self._validate(status_data, self.status_validator, "status")
        snapshot = RenderSnapshot(
            schema_version=snapshot_data["schema_version"],
            job_id=snapshot_data["job_id"],
            attempt_id=snapshot_data["attempt_id"],
            created_at=snapshot_data["created_at"],
            renderer_version=snapshot_data["renderer_version"],
            request_digest=snapshot_data["request_digest"],
            inputs=tuple(InputFingerprint(**item) for item in snapshot_data["inputs"]),
            _request_json=canonical_json_bytes(snapshot_data["request"]),
        )
        status = JobStatus(
            schema_version=status_data["schema_version"],
            job_id=status_data["job_id"],
            attempt_id=status_data["attempt_id"],
            snapshot_digest=status_data["snapshot_digest"],
            revision=status_data["revision"],
            status=JobState(status_data["status"]),
            created_at=status_data["created_at"],
            updated_at=status_data["updated_at"],
            progress_percent=status_data["progress_percent"],
            last_heartbeat_at=status_data["last_heartbeat_at"],
            error=status_data["error"],
            commit_state=status_data.get("commit_state"),
        )
        if status.snapshot_digest != snapshot.snapshot_digest:
            raise MediaInfrastructureError("INVALID_JOB", "Persisted snapshot digest mismatch.")
        expected_request_digest = create_snapshot(
            job_id=snapshot.job_id,
            attempt_id=snapshot.attempt_id,
            created_at=snapshot.created_at,
            renderer_version=snapshot.renderer_version,
            request=snapshot.request,
            inputs=snapshot.inputs,
        ).request_digest
        if snapshot.request_digest != expected_request_digest:
            raise MediaInfrastructureError("INVALID_JOB", "Persisted request digest mismatch.")
        return snapshot, status

    def _attempt_paths(self, job_id: str, attempt_id: str) -> tuple[Path, Path]:
        attempt_dir = self.root / self._key(job_id) / "attempts" / self._key(attempt_id)
        return attempt_dir / "snapshot.json", attempt_dir / "status.json"

    @staticmethod
    def _key(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _load_schema(path: str | Path) -> dict[str, Any]:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(value)
        return value

    @staticmethod
    def _validate(value: Any, validator: Draft202012Validator, label: str) -> None:
        errors = sorted(validator.iter_errors(value), key=lambda item: list(item.absolute_path))
        if errors:
            raise MediaInfrastructureError(
                "INVALID_JOB", f"{label.title()} does not match the WU2 contract.",
                {"reason": errors[0].message},
            )

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            return json.loads(
                path.read_text(encoding="utf-8"),
                parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
            )
        except FileNotFoundError as error:
            raise MediaInfrastructureError("JOB_NOT_FOUND", "Job record does not exist.") from error
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise MediaInfrastructureError("STORAGE_ERROR", "Job record could not be read.") from error

    def _atomic_write(self, path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: str | None = None
        replaced = False
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
            ) as temporary:
                temp_path = temporary.name
                temporary.write(canonical_json_bytes(value))
                temporary.flush()
                os.fsync(temporary.fileno())
            self.replace(temp_path, path)
            temp_path = None
            replaced = True
            self.sync_directory(path.parent)
        except Exception as error:
            if replaced:
                raise IndeterminateMediaCommitError(
                    "Job record was replaced but directory durability is indeterminate."
                ) from error
            raise self._storage_error("Could not atomically persist job record.", error) from error
        finally:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    pass

    @staticmethod
    def _storage_error(message: str, error: BaseException) -> MediaInfrastructureError:
        return MediaInfrastructureError("STORAGE_ERROR", message)

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        if os.name == "nt":
            return
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)