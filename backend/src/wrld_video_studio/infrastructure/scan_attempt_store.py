from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from wrld_video_studio.domain.errors import StudioError
from wrld_video_studio.domain.wu4 import WU4Error
from wrld_video_studio.infrastructure.override_store import OverrideStore


class ScanAttemptStore:
    """Durable private scan-attempt records backed by atomic revisioned files."""

    def __init__(self, store: OverrideStore, schema_path: str | Path) -> None:
        self._store = store
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema)

    def all(self) -> list[dict[str, Any]]:
        if not self._store.root.exists():
            return []
        attempts: list[dict[str, Any]] = []
        for path in sorted(self._store.root.glob("*.json")):
            try:
                wrapper = json.loads(path.read_text(encoding="utf-8"))
                value = wrapper["overrides"]
                self._validate(value)
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
                raise WU4Error("STORAGE_ERROR", "A stored inventory scan attempt is invalid.") from error
            attempts.append(copy.deepcopy(value))
        return attempts

    def put(self, document: Mapping[str, Any]) -> dict[str, Any]:
        value = copy.deepcopy(dict(document))
        self._validate(value)
        scan_id = value["scan_id"]
        try:
            record = self._store.read(scan_id)
        except StudioError as error:
            if error.code != "STORAGE_ERROR":
                raise
            try:
                record = self._store.create(scan_id)
            except StudioError:
                record = self._store.read(scan_id)
        try:
            stored = self._store.update(scan_id, record["revision"], value)
        except StudioError as error:
            raise WU4Error("STORAGE_ERROR", "The inventory scan attempt could not be persisted.") from error
        return copy.deepcopy(stored["overrides"])

    def _validate(self, value: Mapping[str, Any]) -> None:
        errors = sorted(self._validator.iter_errors(value), key=lambda item: list(item.path))
        if errors:
            first = errors[0]
            raise WU4Error(
                "STORAGE_ERROR",
                "The inventory scan attempt violates its contract.",
                {"path": ".".join(str(part) for part in first.path), "reason": first.message},
            )


__all__ = ["ScanAttemptStore"]
