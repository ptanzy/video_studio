from __future__ import annotations

import json
import hashlib
import os
import tempfile
import threading
from pathlib import Path
from pathlib import PureWindowsPath

import portalocker

from wrld_video_studio.domain.canonical_json import canonical_json_bytes
from wrld_video_studio.domain.media_errors import MediaInfrastructureError


class FilesystemArtifactStore:
    def __init__(self, output_root: str | Path) -> None:
        self.output_root = Path(output_root).resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.staging_root = self.output_root / ".wrld-staging"
        self.promotion_root = self.output_root / ".wrld-promotions"
        self._ownership_lock = threading.Lock()
        self._owned_paths: dict[tuple[str, str], set[Path]] = {}

    def stage_path(self, job_id: str, attempt_id: str, relative_path: str) -> Path:
        final = self.resolve_final(relative_path)
        job_key = self._safe_id(job_id)
        attempt_key = self._safe_id(attempt_id)
        staging_root = self._staging_root()
        stage_dir = staging_root / job_key / attempt_key
        self._assert_contained(stage_dir.resolve(strict=False), staging_root)
        stage_dir.mkdir(parents=True, exist_ok=True)
        stage_dir = stage_dir.resolve()
        self._assert_contained(stage_dir, staging_root)
        stage = stage_dir / f"{final.stem}.partial{final.suffix}"
        self._assert_contained(stage, staging_root)
        if stage.exists() or stage.is_symlink():
            self._assert_contained(stage.resolve(strict=False), self.staging_root.resolve())
        with self._ownership_lock:
            self._owned_paths.setdefault((job_key, attempt_key), set()).add(stage)
        self._write_ownership_ledger(stage_dir, stage.name)
        return stage

    def promote(self, staged: Path, relative_path: str) -> Path:
        stage_resolved = staged.resolve(strict=False)
        self._assert_contained(stage_resolved, self._staging_root())
        if not staged.is_file():
            raise MediaInfrastructureError("OUTPUT_INVALID", "Staged output does not exist.")
        try:
            final = self.resolve_final(relative_path)
            final.parent.mkdir(parents=True, exist_ok=True)
            final = self.resolve_final(relative_path)
            with portalocker.Lock(str(self.output_root / ".artifact-promotion.lock"), mode="a", timeout=0):
                if final.exists():
                    raise MediaInfrastructureError("OUTPUT_COLLISION", "Final output already exists.")
                self._write_promotion_record(staged, final)
                os.replace(staged, final)
        except portalocker.exceptions.LockException as error:
            raise MediaInfrastructureError("OUTPUT_BUSY", "Another artifact promotion is active.") from error
        except OSError as error:
            raise MediaInfrastructureError("STORAGE_ERROR", "Could not promote verified output.") from error
        self._remove_owned_stage_record(staged)
        with self._ownership_lock:
            for owned_key, paths in list(self._owned_paths.items()):
                if staged in paths:
                    paths.discard(staged)
                    if not paths:
                        self._owned_paths.pop(owned_key, None)
        return final

    def has_promotion_record(self, job_id: str, attempt_id: str, final: Path) -> bool:
        record = self._promotion_record_path(job_id, attempt_id)
        try:
            payload = json.loads(record.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return False
            if payload != {
                "job_key": self._safe_id(job_id),
                "attempt_key": self._safe_id(attempt_id),
                "final_relative_path": str(final.resolve().relative_to(self.output_root)),
                "staged_sha256": payload.get("staged_sha256"),
            }:
                return False
            if not isinstance(payload["staged_sha256"], str) or len(payload["staged_sha256"]) != 64:
                return False
            digest = hashlib.sha256()
            with final.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest() == payload["staged_sha256"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError, AttributeError):
            return False

    def resolve_final(self, relative_path: str) -> Path:
        candidate = Path(relative_path)
        windows = PureWindowsPath(relative_path)
        if (
            candidate.is_absolute()
            or candidate.drive
            or windows.is_absolute()
            or windows.drive
            or ".." in candidate.parts
            or ".." in windows.parts
        ):
            raise MediaInfrastructureError("INVALID_OUTPUT_PATH", "Output path must be relative and contained.")
        final = (self.output_root / candidate).resolve(strict=False)
        self._assert_contained(final, self.output_root)
        relative = final.relative_to(self.output_root)
        if final == self.output_root or relative.parts[0] in {".wrld-staging", ".wrld-promotions"}:
            raise MediaInfrastructureError("INVALID_OUTPUT_PATH", "Output path targets reserved storage.")
        return final

    def cleanup_owned(self, job_id: str, attempt_id: str) -> None:
        job_key = self._safe_id(job_id)
        attempt_key = self._safe_id(attempt_id)
        staging_root = self._staging_root()
        attempt_dir = staging_root / job_key / attempt_key
        self._assert_contained(attempt_dir.resolve(strict=False), staging_root)
        with self._ownership_lock:
            owned = self._owned_paths.pop((job_key, attempt_key), set())
        ledger = attempt_dir / ".owned-paths.json"
        if ledger.is_file():
            try:
                names = json.loads(ledger.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise MediaInfrastructureError(
                    "STORAGE_ERROR", "Attempt staging ownership record is invalid."
                ) from error
            if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
                raise MediaInfrastructureError(
                    "STORAGE_ERROR", "Attempt staging ownership record is invalid."
                )
            owned.update(attempt_dir / name for name in names)
        for path in owned:
            self._assert_contained(path.resolve(strict=False), staging_root)
            if path.is_file() or path.is_symlink():
                path.unlink(missing_ok=True)
        ledger.unlink(missing_ok=True)
        try:
            attempt_dir.rmdir()
        except OSError:
            return
        try:
            attempt_dir.parent.rmdir()
        except OSError:
            pass

    @staticmethod
    def _safe_id(value: str) -> str:
        import hashlib

        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _staging_root(self) -> Path:
        resolved = self.staging_root.resolve(strict=False)
        self._assert_contained(resolved, self.output_root)
        return resolved

    @staticmethod
    def _write_ownership_ledger(attempt_dir: Path, filename: str) -> None:
        ledger = attempt_dir / ".owned-paths.json"
        temporary_path: str | None = None
        try:
            existing = json.loads(ledger.read_text(encoding="utf-8")) if ledger.exists() else []
            if not isinstance(existing, list) or not all(isinstance(item, str) for item in existing):
                raise ValueError("invalid ownership ledger")
            names = sorted(set(existing) | {filename})
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=attempt_dir, prefix=".owned-paths.",
                suffix=".tmp", delete=False
            ) as stream:
                temporary_path = stream.name
                json.dump(names, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, ledger)
            temporary_path = None
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise MediaInfrastructureError(
                "STORAGE_ERROR", "Could not persist attempt staging ownership."
            ) from error
        finally:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass

    def _promotion_record_path(self, job_id: str, attempt_id: str) -> Path:
        return self.promotion_root / self._safe_id(job_id) / f"{self._safe_id(attempt_id)}.json"

    def _write_promotion_record(self, staged: Path, final: Path) -> None:
        job_key = staged.parent.parent.name
        attempt_key = staged.parent.name
        if not staged.is_file():
            raise MediaInfrastructureError("OUTPUT_INVALID", "Staged output does not exist.")
        digest = hashlib.sha256()
        with staged.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        record = self.promotion_root / job_key / f"{attempt_key}.json"
        record.parent.mkdir(parents=True, exist_ok=True)
        payload = canonical_json_bytes({
            "job_key": job_key,
            "attempt_key": attempt_key,
            "final_relative_path": str(final.resolve().relative_to(self.output_root)),
            "staged_sha256": digest.hexdigest(),
        })
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=record.parent, prefix=f".{record.name}.", suffix=".tmp", delete=False
            ) as temporary:
                temporary_path = temporary.name
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, record)
            temporary_path = None
            if os.name != "nt":
                directory_fd = os.open(record.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except OSError as error:
            raise MediaInfrastructureError(
                "STORAGE_ERROR", "Could not persist the attempt promotion record."
            ) from error
        finally:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass

    @staticmethod
    def _remove_owned_stage_record(staged: Path) -> None:
        ledger = staged.parent / ".owned-paths.json"
        if not ledger.exists():
            return
        try:
            names = json.loads(ledger.read_text(encoding="utf-8"))
            if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
                raise ValueError("invalid ownership ledger")
            remaining = [name for name in names if name != staged.name]
            if remaining:
                with ledger.open("w", encoding="utf-8") as stream:
                    json.dump(remaining, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
                    stream.flush()
                    os.fsync(stream.fileno())
            else:
                ledger.unlink()
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise MediaInfrastructureError(
                "STORAGE_ERROR", "Could not update attempt staging ownership."
            ) from error

    @staticmethod
    def _assert_contained(path: Path, root: Path) -> None:
        try:
            path.relative_to(root)
        except ValueError as error:
            raise MediaInfrastructureError("INVALID_OUTPUT_PATH", "Path escapes configured root.") from error
