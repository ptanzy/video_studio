from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from jsonschema import Draft202012Validator

from wrld_video_studio.domain.canonical_json import canonical_sha256
from wrld_video_studio.domain.errors import StudioError
from wrld_video_studio.domain.wu4 import PROJECT_CATALOG_V1_VERSION, PROJECT_CATALOG_VERSION, WU4Error
from wrld_video_studio.infrastructure.override_store import OverrideStore


class ProjectCatalogStore:
    STORE_ID = "wu4-project-catalog"
    BACKUP_ID = "wu4-project-catalog-v1-backup"

    def __init__(self, store: OverrideStore, payload_schema: str | Path) -> None:
        self._store = store
        schema = json.loads(Path(payload_schema).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema)

    def read(self) -> dict[str, Any]:
        record = self._record()
        payload = record["overrides"]
        self._validate(payload)
        result = copy.deepcopy(payload)
        result["revision"] = record["revision"]
        return result

    def mutate(self, operation: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        current = self._record()
        payload = copy.deepcopy(current["overrides"])
        operation(payload)
        self._validate(payload)
        try:
            stored = self._store.update(self.STORE_ID, current["revision"], payload)
        except StudioError as error:
            if error.code == "REVISION_CONFLICT":
                raise WU4Error("REVISION_CONFLICT", "The project catalog changed concurrently.", dict(error.details)) from error
            raise WU4Error("STORAGE_ERROR", "The project catalog could not be updated.", dict(error.details)) from error
        result = copy.deepcopy(stored["overrides"])
        result["revision"] = stored["revision"]
        return result

    def _record(self) -> dict[str, Any]:
        try:
            record = self._store.read(self.STORE_ID)
        except StudioError as error:
            if error.code != "STORAGE_ERROR":
                raise
            try:
                record = self._store.create(self.STORE_ID)
            except StudioError:
                record = self._store.read(self.STORE_ID)
        if not record["overrides"]:
            initial = {"contract_version": PROJECT_CATALOG_VERSION, "projects": []}
            try:
                record = self._store.update(self.STORE_ID, record["revision"], initial)
            except StudioError as error:
                if error.code != "REVISION_CONFLICT":
                    raise WU4Error("STORAGE_ERROR", "The project catalog could not be initialized.") from error
                record = self._store.read(self.STORE_ID)
        if record["overrides"].get("contract_version") == PROJECT_CATALOG_V1_VERSION:
            record = self._migrate(record)
        return record

    def _migrate(self, record: Mapping[str, Any]) -> dict[str, Any]:
        source = copy.deepcopy(record["overrides"])
        if not isinstance(source.get("projects"), list):
            raise WU4Error("STORAGE_ERROR", "The v1 project catalog cannot be migrated safely.")
        digest = canonical_sha256(source)
        backup = {"contract_version": PROJECT_CATALOG_V1_VERSION, "source_digest": digest, "catalog": source}
        try:
            backup_record = self._store.read(self.BACKUP_ID)
        except StudioError:
            try:
                backup_record = self._store.create(self.BACKUP_ID)
                self._store.update(self.BACKUP_ID, backup_record["revision"], backup)
            except StudioError as error:
                raise WU4Error("STORAGE_ERROR", "The recoverable catalog backup could not be created.") from error
        else:
            stored = backup_record["overrides"]
            if not stored:
                try:
                    self._store.update(self.BACKUP_ID, backup_record["revision"], backup)
                except StudioError as error:
                    raise WU4Error("STORAGE_ERROR", "The recoverable catalog backup could not be completed.") from error
            elif stored.get("source_digest") != digest:
                raise WU4Error("STORAGE_ERROR", "A different catalog migration backup already exists.")
        projects: list[dict[str, Any]] = []
        for item in source["projects"]:
            if not isinstance(item, dict):
                raise WU4Error("STORAGE_ERROR", "The v1 project catalog cannot be migrated safely.")
            projects.append({
                "project_id": item["project_id"], "root_id": item["root_id"],
                "relative_path": item["relative_path"], "active": item["active"],
                "registered_at": item["registered_at"], "updated_at": item["updated_at"],
                "inventory_revision": 0,
                "enrichment": {"status": "recognized", "manifest_format": None, "album_id": item["album_id"]},
            })
        migrated = {
            "contract_version": PROJECT_CATALOG_VERSION,
            "migration": {"source_contract_version": PROJECT_CATALOG_V1_VERSION, "source_digest": digest},
            "projects": projects,
        }
        self._validate(migrated)
        try:
            return self._store.update(self.STORE_ID, record["revision"], migrated)
        except StudioError as error:
            if error.code == "REVISION_CONFLICT":
                latest = self._store.read(self.STORE_ID)
                if latest["overrides"].get("contract_version") == PROJECT_CATALOG_VERSION:
                    return latest
            raise WU4Error("STORAGE_ERROR", "The project catalog migration could not be committed.") from error

    def _validate(self, payload: Mapping[str, Any]) -> None:
        errors = sorted(self._validator.iter_errors(payload), key=lambda item: list(item.path))
        if errors:
            first = errors[0]
            raise WU4Error(
                "STORAGE_ERROR",
                "The private project catalog is invalid.",
                {"path": ".".join(str(part) for part in first.path), "reason": first.message},
            )


__all__ = ["ProjectCatalogStore"]
