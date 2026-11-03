from __future__ import annotations

from typing import Any, Literal

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


class InitializeMetadataModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    save_id: str = Field(min_length=1, max_length=128)
    creation_revision: int = Field(ge=1)
    creation_state_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ValidateMetadataModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    state: dict[str, Any]
    mode: Literal["draft", "approval", "export"]
    target_keys: list[str] | None = None


class ReconcileSelectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    target_key: str = Field(min_length=1, max_length=135)
    field: Literal["title", "description", "tags", "hashtags", "artist_name", "channel_name", "credits", "links", "visibility", "pinned_comment", "release_album_plan_id", "related_video_url"]


class ChapterCarryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    target_key: str = Field(min_length=1, max_length=135)
    track_id: str = Field(min_length=1, max_length=128)


class ReconcilePreviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1)
    refresh_fields: list[ReconcileSelectionModel] = Field(default_factory=list)
    carry_chapter_labels: list[ChapterCarryModel] = Field(default_factory=list)


class ReconcileMetadataModel(ReconcilePreviewModel):
    save_id: str = Field(min_length=1, max_length=128)
    preview_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExportPreviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1)
    target_keys: list[str] = Field(min_length=1)


class ExportMetadataModel(ExportPreviewModel):
    preview_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    replace_existing: bool = False
    expected_existing_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


__all__ = ["ChapterCarryModel", "ExportMetadataModel", "ExportPreviewModel", "InitializeMetadataModel", "ReconcileMetadataModel", "ReconcilePreviewModel", "RegisterProjectModel", "RelinkAssetModel", "RelinkProjectModel", "SaveEditorStateModel", "SaveProjectDocumentModel", "StartScanModel", "ValidateMetadataModel"]
