from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from wrld_video_studio.domain.canonical_json import canonical_sha256
from wrld_video_studio.domain.errors import IndeterminateCommitError, StudioError
from wrld_video_studio.domain.wu4 import WU4Error
from wrld_video_studio.infrastructure.override_store import OverrideStore


class EditorStateStore:
    def __init__(self, store: OverrideStore, schema_path: str | Path) -> None:
        self._store = store
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema)

    def read(self, project_id: str) -> dict[str, Any]:
        try:
            record = self._store.read(project_id)
        except StudioError as error:
            if error.code == "STORAGE_ERROR":
                raise WU4Error("EDITOR_STATE_NOT_FOUND", "Editor state has not been initialized.") from error
            raise
        value = copy.deepcopy(record["overrides"])
        if value.get("revision") != record["revision"]:
            raise WU4Error("STORAGE_ERROR", "Stored editor-state revisions are inconsistent.")
        self._validate(value)
        return value

    def create(self, project_id: str, document: Mapping[str, Any]) -> dict[str, Any]:
        value = self._prepare(document, revision=1)
        try:
            initial = self._store.create(project_id)
        except StudioError:
            return self.read(project_id)
        try:
            stored = self._store.update(project_id, initial["revision"], value)
        except StudioError as error:
            if error.code == "REVISION_CONFLICT":
                return self.read(project_id)
            raise WU4Error("STORAGE_ERROR", "Editor state could not be initialized.") from error
        return copy.deepcopy(stored["overrides"])

    def update(
        self,
        project_id: str,
        expected_revision: int,
        document: Mapping[str, Any],
    ) -> dict[str, Any]:
        value = self._prepare(document, revision=expected_revision + 1)
        try:
            stored = self._store.update(project_id, expected_revision, value)
        except IndeterminateCommitError as error:
            raise WU4Error(
                "COMMIT_INDETERMINATE",
                "The editor-state file was replaced, but completion could not be confirmed.",
                {
                    "candidate_revision": expected_revision + 1,
                    "save_id": value["save_id"],
                    "state_digest": value["state_digest"],
                },
            ) from error
        except StudioError as error:
            if error.code == "REVISION_CONFLICT":
                raise WU4Error("REVISION_CONFLICT", "Stored editor state changed before this save.", dict(error.details)) from error
            raise WU4Error("STORAGE_ERROR", "Editor state could not be saved.", dict(error.details)) from error
        return copy.deepcopy(stored["overrides"])

    def _prepare(self, document: Mapping[str, Any], *, revision: int) -> dict[str, Any]:
        value = copy.deepcopy(dict(document))
        value["revision"] = revision
        value["state_digest"] = "0" * 64
        value["state_digest"] = canonical_sha256(
            {key: item for key, item in value.items() if key != "state_digest"}
        )
        self._validate(value)
        return value

    def _validate(self, value: Mapping[str, Any]) -> None:
        errors = sorted(self._validator.iter_errors(value), key=lambda item: list(item.path))
        if errors:
            first = errors[0]
            raise WU4Error(
                "EDITOR_STATE_INVALID",
                "Editor state does not satisfy its strict contract.",
                {"path": ".".join(str(part) for part in first.path), "reason": first.message},
            )


__all__ = ["EditorStateStore"]
