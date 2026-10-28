from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.render_progress import RenderProgress
from wrld_video_studio.infrastructure.render_report_store import JsonVideoResultStore


class JsonRenderProgressStore:
    def __init__(self, root: str | Path, schema_path: str | Path) -> None:
        self.root = Path(root).resolve()
        self.validator = _validator(schema_path)
        self._lock = threading.RLock()

    def save(self, progress: RenderProgress) -> None:
        value = progress.to_dict()
        _validate(self.validator, value, "progress")
        with self._lock:
            JsonVideoResultStore._write(self._path(progress.job_id, progress.attempt_id), value)

    def load(self, job_id: str, attempt_id: str) -> RenderProgress | None:
        with self._lock:
            path = self._path(job_id, attempt_id)
            if not path.is_file():
                return None
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                _validate(self.validator, value, "progress")
                return RenderProgress.from_dict(value)
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                raise MediaInfrastructureError(
                    "STORAGE_ERROR", "Private render progress is invalid."
                ) from error

    def reference(self, job_id: str, attempt_id: str) -> str:
        return f"progress/{_key(job_id)}/{_key(attempt_id)}.json"

    def _path(self, job_id: str, attempt_id: str) -> Path:
        return self.root / _key(job_id) / f"{_key(attempt_id)}.json"


class JsonRenderDiagnosticStore:
    def __init__(
        self,
        root: str | Path,
        schema_path: str | Path,
        *,
        fallback_root: str | Path | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.fallback_root = Path(fallback_root).resolve() if fallback_root is not None else None
        self.validator = _validator(schema_path)
        self._lock = threading.RLock()

    def save(self, diagnostic: Mapping[str, Any]) -> str:
        value = dict(diagnostic)
        _validate(self.validator, value, "diagnostic")
        reference = self.reference(value["job_id"], value["attempt_id"])
        with self._lock:
            try:
                self._write_unique(
                    self.root / Path(reference).relative_to("diagnostics"), value
                )
                return reference
            except (OSError, MediaInfrastructureError) as primary_error:
                if self.fallback_root is None:
                    raise MediaInfrastructureError(
                        "STORAGE_ERROR", "Private render diagnostic could not be persisted."
                    ) from primary_error
                fallback_reference = self.fallback_reference(
                    value["job_id"], value["attempt_id"]
                )
                try:
                    self._write_unique(
                        self.fallback_root
                        / Path(fallback_reference).relative_to("diagnostics-fallback"),
                        value,
                    )
                    return fallback_reference
                except (OSError, MediaInfrastructureError) as fallback_error:
                    failure = MediaInfrastructureError(
                        "STORAGE_ERROR",
                        "Private render diagnostic could not be persisted in either location.",
                    )
                    failure.__cause__ = fallback_error
                    failure.add_note(f"Primary diagnostic persistence failed: {type(primary_error).__name__}")
                    raise failure

    @staticmethod
    def reference(job_id: str, attempt_id: str) -> str:
        return f"diagnostics/{_short_key(job_id)}/{_short_key(attempt_id)}.json"

    @staticmethod
    def fallback_reference(job_id: str, attempt_id: str) -> str:
        return f"diagnostics-fallback/{_short_key(job_id)}/{_short_key(attempt_id)}.json"

    @staticmethod
    def _write_unique(path: Path, value: Mapping[str, Any]) -> None:
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise MediaInfrastructureError(
                    "STORAGE_ERROR", "Existing private render diagnostic is invalid."
                ) from error
            if (
                existing.get("job_id") != value.get("job_id")
                or existing.get("attempt_id") != value.get("attempt_id")
            ):
                raise MediaInfrastructureError(
                    "STORAGE_ERROR", "Private render diagnostic key collision detected."
                )
        JsonVideoResultStore._write(path, value)


def _validator(schema_path: str | Path) -> Draft202012Validator:
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate(validator: Draft202012Validator, value: Any, label: str) -> None:
    errors = sorted(validator.iter_errors(value), key=lambda item: list(item.absolute_path))
    if errors:
        raise MediaInfrastructureError(
            "STORAGE_ERROR", f"Private render {label} violates its contract.",
            {"reason": errors[0].message},
        )


def _key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _short_key(value: str) -> str:
    return _key(value)[:24]
