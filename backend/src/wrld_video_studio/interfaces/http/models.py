from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from wrld_video_studio.domain.preview_cache import PreviewContractError, PreviewRequest


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


Intensity = Annotated[float, Field(ge=0.0, le=0.6, allow_inf_nan=False)]
Identifier = Annotated[str, Field(min_length=1)]
ArtworkAssetId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")]


class PreviewTargetModel(_StrictModel):
    album_id: Identifier
    artwork_asset_id: ArtworkAssetId
    track_id: Identifier | SkipJsonSchema[None] = None
    short_id: Identifier | SkipJsonSchema[None] = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_null_identifiers(cls, value):
        if isinstance(value, dict) and any(
            name in value and value[name] is None for name in ("track_id", "short_id")
        ):
            raise ValueError("Optional target identifiers cannot be null.")
        return value


class AutoTreatmentModel(_StrictModel):
    mode: Literal["auto"]
    intensity: Intensity


class PresetTreatmentModel(_StrictModel):
    mode: Literal["preset"]
    preset: Literal["original", "cool", "warm", "lavender", "teal", "dark"]
    intensity: Intensity


class CustomTreatmentModel(_StrictModel):
    mode: Literal["custom"]
    hex: Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]
    intensity: Intensity


TreatmentModel = Annotated[
    AutoTreatmentModel | PresetTreatmentModel | CustomTreatmentModel,
    Field(discriminator="mode"),
]


class PreviewRequestModel(_StrictModel):
    contract_version: Literal["preview-request-v1"]
    target: PreviewTargetModel
    treatment: TreatmentModel
    variant: Literal["authoritative_still"]

    def to_domain(self) -> PreviewRequest:
        try:
            return PreviewRequest.from_dict(self.model_dump(mode="json", exclude_none=True))
        except PreviewContractError:
            raise


class PreviewErrorBodyModel(_StrictModel):
    code: Literal[
        "PREVIEW_INVALID_REQUEST",
        "PREVIEW_SOURCE_UNAVAILABLE",
        "SOURCE_CHANGED",
        "PREVIEW_IMAGE_UNSUPPORTED",
        "PREVIEW_RENDER_FAILED",
        "PREVIEW_CANCELLED",
        "PREVIEW_TIMEOUT",
        "PREVIEW_CAPACITY_EXHAUSTED",
        "PREVIEW_CACHE_CORRUPT",
        "PREVIEW_INTERNAL_ERROR",
    ]
    message: Identifier
    details: dict[str, object]
    correlation_id: Identifier


class PreviewErrorEnvelopeModel(_StrictModel):
    contract_version: Literal["preview-error-v1"]
    error: PreviewErrorBodyModel
