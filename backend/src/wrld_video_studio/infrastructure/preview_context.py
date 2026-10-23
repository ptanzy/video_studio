from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from wrld_video_studio.application.ports.preview_context import PreviewContextError
from wrld_video_studio.domain.color_resolution import (
    INPUT_CONTRACT_VERSION,
    ColorResolutionError,
    resolve_color_treatment,
)
from wrld_video_studio.domain.preview_cache import PreviewTarget


@dataclass(frozen=True, slots=True)
class PreviewContextRegistration:
    album_id: str
    artwork_asset_id: str
    context: Mapping[str, Any]
    track_id: str | None = None
    short_id: str | None = None


class ImmutablePreviewContextRegistry:
    """Exact, immutable lookup for trusted automatic-color context."""

    def __init__(self, registrations: Iterable[PreviewContextRegistration]) -> None:
        entries: dict[tuple[str, str, str | None, str | None], Mapping[str, Any]] = {}
        for registration in registrations:
            if not isinstance(registration, PreviewContextRegistration):
                raise TypeError("Preview context registrations must use trusted values.")
            target = PreviewTarget(
                album_id=registration.album_id,
                artwork_asset_id=registration.artwork_asset_id,
                track_id=registration.track_id,
                short_id=registration.short_id,
            )
            context = _copy_json_object(registration.context)
            try:
                resolve_color_treatment(
                    {
                        "contract_version": INPUT_CONTRACT_VERSION,
                        "treatment": {"mode": "auto", "intensity": 0.0},
                        "context": context,
                    }
                )
            except ColorResolutionError as error:
                raise ValueError("Trusted preview color context is invalid.") from error
            key = (
                target.album_id,
                target.artwork_asset_id,
                target.track_id,
                target.short_id,
            )
            if key in entries:
                raise ValueError("Preview context registrations must have unique exact targets.")
            entries[key] = _freeze_json(context)
        self._entries = MappingProxyType(entries)

    def context_for(self, target: PreviewTarget) -> Mapping[str, Any]:
        if not isinstance(target, PreviewTarget):
            raise PreviewContextError(
                "PREVIEW_INVALID_REQUEST", "The preview target is invalid."
            )
        key = (
            target.album_id,
            target.artwork_asset_id,
            target.track_id,
            target.short_id,
        )
        try:
            context = self._entries[key]
        except KeyError as error:
            raise PreviewContextError(
                "PREVIEW_INVALID_REQUEST",
                "The preview target is not registered for automatic color resolution.",
            ) from error
        return _thaw_json(context)


def _copy_json_object(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Trusted preview context must be an object.")
    copied = _thaw_json(value)
    if type(copied) is not dict:
        raise ValueError("Trusted preview context must be an object.")
    return copied


def _freeze_json(value: Any) -> Any:
    if value is None or type(value) in (bool, int, str):
        if type(value) is str:
            value.encode("utf-8", errors="strict")
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("Trusted preview context contains a non-finite number.")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, child in value.items():
            if type(key) is not str:
                raise ValueError("Trusted preview context keys must be strings.")
            key.encode("utf-8", errors="strict")
            frozen[key] = _freeze_json(child)
        return MappingProxyType(frozen)
    if type(value) in (list, tuple):
        return tuple(_freeze_json(child) for child in value)
    raise ValueError("Trusted preview context must contain JSON-compatible values.")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(child) for key, child in value.items()}
    if type(value) in (list, tuple):
        return [_thaw_json(child) for child in value]
    return value
