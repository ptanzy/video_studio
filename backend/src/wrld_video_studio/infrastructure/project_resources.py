from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable

from wrld_video_studio.domain.wu4 import TrustedProjectRoot, WU4Error, portable_directory


@dataclass(frozen=True, slots=True)
class _RootRecord:
    root_id: str
    label: str
    path: Path
    final_path: str


class SecureProjectFile:
    def __init__(self, stream: BinaryIO, *, size: int) -> None:
        self._stream = stream
        self.size = size
        self._closed = False

    def read(self, amount: int = -1) -> bytes:
        if self._closed:
            return b""
        return self._stream.read(amount)

    def seek(self, offset: int) -> None:
        if self._closed:
            raise ValueError("resource is closed")
        self._stream.seek(offset)

    def sha256(self) -> str:
        if self._closed:
            raise ValueError("resource is closed")
        self._stream.seek(0)
        digest = hashlib.sha256()
        for chunk in iter(lambda: self._stream.read(1024 * 1024), b""):
            digest.update(chunk)
        self._stream.seek(0)
        return digest.hexdigest()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._stream.close()

    def __enter__(self) -> SecureProjectFile:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class TrustedProjectResolver:
    """Resolve only configured, non-linked local project resources."""

    def __init__(self, roots: Iterable[TrustedProjectRoot]) -> None:
        records: dict[str, _RootRecord] = {}
        final_paths: set[str] = set()
        for root in roots:
            if not isinstance(root, TrustedProjectRoot):
                raise TypeError("Trusted roots must use TrustedProjectRoot values")
            supplied = Path(root.path)
            if not supplied.is_absolute():
                raise ValueError("Trusted project roots must be absolute")
            try:
                path = supplied.resolve(strict=True)
            except OSError as error:
                raise ValueError("A trusted project root is unavailable") from error
            if not path.is_dir() or self._is_reparse(path):
                raise ValueError("Trusted project roots must be regular non-reparse directories")
            final = self._normal(path)
            if root.root_id in records or final in final_paths:
                raise ValueError("Trusted project roots must be unique")
            records[root.root_id] = _RootRecord(root.root_id, root.label, path, final)
            final_paths.add(final)
        if not records:
            raise ValueError("At least one trusted project root is required")
        ordered = tuple(records.values())
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                if left.final_path.startswith(right.final_path + os.sep) or right.final_path.startswith(left.final_path + os.sep):
                    raise ValueError("Trusted project roots may not overlap")
        self._roots = records

    def roots(self) -> tuple[dict[str, str], ...]:
        return tuple(
            {"root_id": item.root_id, "label": item.label}
            for item in sorted(self._roots.values(), key=lambda value: value.root_id)
        )

    def directories(self, root_id: str, parent: str = "") -> tuple[dict[str, str], ...]:
        directory = self.resolve_directory(root_id, parent)
        values: list[dict[str, str]] = []
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
        except OSError as error:
            raise WU4Error("PROJECT_UNAVAILABLE", "The trusted directory cannot be listed.") from error
        for child in children:
            try:
                if child.is_dir() and not self._is_reparse(child):
                    relative = child.relative_to(self._roots[root_id].path).as_posix()
                    values.append({"name": child.name, "relative_path": relative})
            except (OSError, ValueError):
                continue
        return tuple(values)

    def resolve_directory(self, root_id: str, relative_path: str) -> Path:
        try:
            root = self._roots[root_id]
        except KeyError as error:
            raise WU4Error("PROJECT_ROOT_NOT_FOUND", "The trusted library root is unknown.") from error
        try:
            relative = portable_directory(relative_path)
        except ValueError as error:
            raise WU4Error("PROJECT_PATH_INVALID", "The project location is invalid.") from error
        candidate = root.path
        for part in (() if not relative else tuple(relative.split("/"))):
            candidate = candidate / part
            if self._is_reparse(candidate):
                raise WU4Error("PROJECT_PATH_INVALID", "Project paths may not traverse links or reparse points.")
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root.path)
        except (OSError, ValueError) as error:
            raise WU4Error("PROJECT_NOT_FOUND", "The project directory does not exist under the trusted root.") from error
        if not resolved.is_dir() or self._is_reparse(resolved):
            raise WU4Error("PROJECT_PATH_INVALID", "The project location must be a regular directory.")
        if not self._normal(resolved).startswith(root.final_path + os.sep) and self._normal(resolved) != root.final_path:
            raise WU4Error("PROJECT_PATH_INVALID", "The project directory escaped its trusted root.")
        return resolved

    def open_project_file(self, project_root: Path, relative_path: str) -> SecureProjectFile:
        resolved = self.resolve_project_file(project_root, relative_path)
        project = project_root.resolve(strict=True)
        try:
            if os.name == "nt":
                return self._open_windows(project, resolved)
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(resolved, flags)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                os.close(descriptor)
                raise OSError("resource is not regular")
            return SecureProjectFile(os.fdopen(descriptor, "rb", closefd=True), size=metadata.st_size)
        except WU4Error:
            raise
        except OSError as error:
            raise WU4Error("RESOURCE_NOT_FOUND", "The project resource could not be opened safely.") from error

    def resolve_project_file(self, project_root: Path, relative_path: str) -> Path:
        try:
            relative = portable_directory(relative_path)
        except ValueError as error:
            raise WU4Error("RESOURCE_NOT_FOUND", "The project resource path is invalid.") from error
        if not relative:
            raise WU4Error("RESOURCE_NOT_FOUND", "A project file is required.")
        project = project_root.resolve(strict=True)
        candidate = project
        for part in relative.split("/"):
            candidate = candidate / part
            if self._is_reparse(candidate):
                raise WU4Error("PROJECT_PATH_INVALID", "Project resources may not traverse links or reparse points.")
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(project)
        except (OSError, ValueError) as error:
            raise WU4Error("RESOURCE_NOT_FOUND", "The project resource is missing.") from error
        if not resolved.is_file() or self._is_reparse(resolved):
            raise WU4Error("RESOURCE_NOT_FOUND", "The project resource is not a regular file.")
        return resolved

    @staticmethod
    def _open_windows(project: Path, source: Path) -> SecureProjectFile:
        import msvcrt
        import win32con
        import win32file

        share = win32con.FILE_SHARE_READ
        handle = win32file.CreateFile(
            str(source),
            win32con.GENERIC_READ,
            share,
            None,
            win32con.OPEN_EXISTING,
            win32file.FILE_FLAG_OPEN_REPARSE_POINT | win32con.FILE_FLAG_SEQUENTIAL_SCAN,
            None,
        )
        try:
            info = win32file.GetFileInformationByHandle(handle)
            if info[0] & (win32con.FILE_ATTRIBUTE_REPARSE_POINT | win32con.FILE_ATTRIBUTE_DIRECTORY):
                raise OSError("resource is linked or not regular")
            project_text = os.path.normcase(os.path.normpath(str(project))).rstrip("\\/")
            final_text = os.path.normcase(
                os.path.normpath(win32file.GetFinalPathNameByHandle(handle, 0).removeprefix("\\\\?\\"))
            )
            if final_text != project_text and not final_text.startswith(project_text + "\\"):
                raise OSError("resource escaped project")
            size = (int(info[5]) << 32) | int(info[6])
            descriptor = msvcrt.open_osfhandle(handle.Detach(), os.O_RDONLY | getattr(os, "O_BINARY", 0))
            return SecureProjectFile(os.fdopen(descriptor, "rb", closefd=True), size=size)
        except Exception:
            handle.Close()
            raise

    @staticmethod
    def _normal(path: Path) -> str:
        return os.path.normcase(os.path.normpath(str(path)))

    @staticmethod
    def _is_reparse(path: Path) -> bool:
        try:
            info = path.lstat()
        except OSError:
            return False
        attributes = getattr(info, "st_file_attributes", 0)
        return stat.S_ISLNK(info.st_mode) or bool(
            attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )


__all__ = ["SecureProjectFile", "TrustedProjectResolver"]
