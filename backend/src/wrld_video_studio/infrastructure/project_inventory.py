from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from wrld_video_studio.domain.errors import StudioError
from wrld_video_studio.domain.wu4 import PROJECT_INVENTORY_VERSION, WU4Error
from wrld_video_studio.infrastructure.override_store import OverrideStore


class ProjectInventoryStore:
    def __init__(self, store: OverrideStore, schema_path: str | Path) -> None:
        self._store = store
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema)

    def read(self, project_id: str) -> dict[str, Any]:
        try:
            record = self._store.read(project_id)
        except StudioError as error:
            if error.code != "STORAGE_ERROR":
                raise
            return self.empty(project_id)
        value = copy.deepcopy(record["overrides"])
        self._validate(value)
        if value["inventory_revision"] != record["revision"]:
            raise WU4Error("STORAGE_ERROR", "Stored inventory revisions are inconsistent.")
        return value

    def publish(self, project_id: str, expected_revision: int, document: Mapping[str, Any]) -> dict[str, Any]:
        value = copy.deepcopy(dict(document))
        value["inventory_revision"] = expected_revision + 1
        self._validate(value)
        try:
            try:
                record = self._store.read(project_id)
            except StudioError:
                record = self._store.create(project_id)
            if record["revision"] != expected_revision:
                raise WU4Error("REVISION_CONFLICT", "The project inventory changed concurrently.", {"expected_revision": expected_revision, "actual_revision": record["revision"]})
            stored = self._store.update(project_id, expected_revision, value)
        except WU4Error:
            raise
        except StudioError as error:
            code = "REVISION_CONFLICT" if error.code == "REVISION_CONFLICT" else "STORAGE_ERROR"
            raise WU4Error(code, "The project inventory could not be published.", dict(error.details)) from error
        return copy.deepcopy(stored["overrides"])

    @staticmethod
    def empty(project_id: str) -> dict[str, Any]:
        return {
            "contract_version": PROJECT_INVENTORY_VERSION, "project_id": project_id,
            "inventory_revision": 0, "scan_id": None, "completed_at": None,
            "policy_version": "inventory-policy/1.0", "assets": [], "diagnostics": [],
            "counts": {"audio": 0, "image": 0, "video": 0, "unknown": 0, "missing": 0},
        }

    def _validate(self, value: Mapping[str, Any]) -> None:
        errors = sorted(self._validator.iter_errors(value), key=lambda item: list(item.path))
        if errors:
            first = errors[0]
            raise WU4Error("STORAGE_ERROR", "The private project inventory is invalid.", {"path": ".".join(str(part) for part in first.path), "reason": first.message})


__all__ = ["ProjectInventoryStore"]
