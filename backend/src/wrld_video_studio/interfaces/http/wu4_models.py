from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RegisterProjectModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    root_id: str = Field(min_length=1, max_length=128)
    relative_path: str = Field(max_length=1024)


class RelinkProjectModel(RegisterProjectModel):
    pass


class RelinkAssetModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    relative_path: str = Field(min_length=1, max_length=4096)


class SaveEditorStateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1)
    save_id: str = Field(min_length=1, max_length=128)
    state: dict[str, Any]


class SaveProjectDocumentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1)
    save_id: str = Field(min_length=1, max_length=128)
    state: dict[str, Any]


class StartScanModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    retry_of_scan_id: str | None = Field(default=None, min_length=1, max_length=128)


__all__ = ["RegisterProjectModel", "RelinkAssetModel", "RelinkProjectModel", "SaveEditorStateModel", "SaveProjectDocumentModel", "StartScanModel"]
