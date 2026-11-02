from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from wrld_video_studio.domain.canonical_json import canonical_sha256


INPUT_CONTRACT_VERSION = "color-resolution-input-v1"
OUTPUT_CONTRACT_VERSION = "color-resolution-output-v1"
RESOLVER_VERSION = "1.0.0-provisional.1"
PRESET_MAPPING_VERSION = "provisional-1"
MIN_INTENSITY = 0.0
MAX_INTENSITY = 0.6

# These aesthetic mappings are provisional and require explicit product approval.
PRESET_HEX_BY_ID: Mapping[str, str | None] = MappingProxyType(
    {
        "original": None,
        "cool": "#71869A",
        "warm": "#B47B55",
        "lavender": "#887A9B",
        "teal": "#5F817B",
        "dark": "#48525A",
    }
)

_HEX_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
_INPUT_FIELDS = frozenset({"contract_version", "treatment", "context"})
_CONTEXT_FIELDS = frozenset(
    {"track_preference", "album_palette", "album_default_preset", "mood", "features"}
)
_FEATURE_FIELDS = frozenset({"brightness", "energy", "tension"})


def _freeze_json(value: Any, path: str) -> Any:
    if value is None or type(value) in (str, bool, int):
        if type(value) is str:
            value.encode("utf-8", errors="strict")
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"Non-finite error detail at {path}")
        return value
    if type(value) is dict:
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError(f"Error detail keys must be strings at {path}")
            key.encode("utf-8", errors="strict")
            frozen[key] = _freeze_json(item, f"{path}.{key}")
        return MappingProxyType(frozen)
    if type(value) is list:
        return tuple(_freeze_json(item, f"{path}[{index}]") for index, item in enumerate(value))
    raise ValueError(f"Unsupported error detail at {path}")


class ColorResolutionError(ValueError):
    """Stable, transport-independent color contract/resolution error."""

    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None) -> None:
        self.code = code
        self.message = message
        self._details = _freeze_json(dict(details or {}), "details")
        super().__init__(message)

    @property
    def details(self) -> Mapping[str, Any]:
        return self._details


@dataclass(frozen=True, slots=True)
class ColorResolution:
    contract_version: str
    mode: str
    resolved_hex: str | None
    preset_id: str | None
    intensity: float
    source: str
    reason: str
    resolver_version: str
    preset_mapping_version: str
    input_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "mode": self.mode,
            "resolved_hex": self.resolved_hex,
            "preset_id": self.preset_id,
            "intensity": self.intensity,
            "source": self.source,
            "reason": self.reason,
            "resolver_version": self.resolver_version,
            "preset_mapping_version": self.preset_mapping_version,
            "input_fingerprint": self.input_fingerprint,
        }


def resolve_color_treatment(payload: Mapping[str, Any]) -> ColorResolution:
    """Resolve a versioned color-treatment input without mutating caller data."""
    normalized_payload = _copy_json_object(payload, "input")
    _validate_input_envelope(normalized_payload)

    treatment = normalized_payload["treatment"]
    mode = treatment["mode"]
    intensity = _validate_intensity(treatment["intensity"])
    treatment["intensity"] = intensity
    if mode == "custom":
        treatment["hex"] = _validate_hex(treatment["hex"], "COLOR_INVALID_HEX")
    context = normalized_payload.get("context", {})
    _validate_context_shape(context)
    _normalize_context_hex(context)

    if mode == "custom":
        resolved_hex = treatment["hex"]
        source, reason, preset_id = "user_selection", "explicit_custom", None
        final_intensity = intensity
    elif mode == "preset":
        preset_id = treatment["preset"]
        if preset_id not in PRESET_HEX_BY_ID:
            raise ColorResolutionError(
                "COLOR_INVALID_PRESET", "Preset identifier is not supported.", {"field": "treatment.preset"}
            )
        resolved_hex = PRESET_HEX_BY_ID[preset_id]
        source, reason = "user_selection", "explicit_original" if preset_id == "original" else "explicit_preset"
        final_intensity = 0.0 if preset_id == "original" else intensity
    else:
        resolved_hex, preset_id, source, reason = _resolve_auto(context)
        final_intensity = 0.0 if resolved_hex is None else intensity

    fingerprint_payload = {
        "input": normalized_payload,
        "resolver_version": RESOLVER_VERSION,
        "preset_mapping_version": PRESET_MAPPING_VERSION,
    }
    try:
        fingerprint = canonical_sha256(fingerprint_payload)
    except (TypeError, ValueError, UnicodeError, OverflowError) as error:
        raise ColorResolutionError(
            "COLOR_INVALID_INPUT", "Input cannot be represented by the canonical JSON contract."
        ) from error
    return ColorResolution(
        contract_version=OUTPUT_CONTRACT_VERSION,
        mode=mode,
        resolved_hex=resolved_hex,
        preset_id=preset_id,
        intensity=final_intensity,
        source=source,
        reason=reason,
        resolver_version=RESOLVER_VERSION,
        preset_mapping_version=PRESET_MAPPING_VERSION,
        input_fingerprint=fingerprint,
    )


def _resolve_auto(context: Mapping[str, Any]) -> tuple[str | None, str | None, str, str]:
    preference = context.get("track_preference")
    if isinstance(preference, dict):
        preference_hex = preference.get("hex")
        return preference_hex, None, "track_preference", "explicit_track_preference"

    palette = context.get("album_palette", ())
    if palette:
        color = palette[0]["hex"]
        return color, None, "album_palette", "first_palette_entry"

    default_preset = context.get("album_default_preset")
    if isinstance(default_preset, str) and default_preset in PRESET_HEX_BY_ID:
        default_hex = PRESET_HEX_BY_ID[default_preset]
        if default_hex is None:
            return None, "original", "album_default", "album_default_original"
        return default_hex, default_preset, "album_default", "album_default_preset"

    return None, "original", "fallback", "no_usable_auto_color"


def _validate_input_envelope(payload: dict[str, Any]) -> None:
    if set(payload) - _INPUT_FIELDS or "contract_version" not in payload or "treatment" not in payload:
        raise ColorResolutionError("COLOR_INVALID_INPUT", "Input fields do not match the versioned contract.")
    if payload["contract_version"] != INPUT_CONTRACT_VERSION:
        raise ColorResolutionError(
            "COLOR_UNSUPPORTED_CONTRACT", "Input contract version is not supported.", {"field": "contract_version"}
        )
    treatment = payload["treatment"]
    if not isinstance(treatment, dict):
        raise ColorResolutionError("COLOR_INVALID_INPUT", "Treatment must be an object.", {"field": "treatment"})
    mode = treatment.get("mode")
    required_by_mode = {
        "auto": {"mode", "intensity"},
        "preset": {"mode", "preset", "intensity"},
        "custom": {"mode", "hex", "intensity"},
    }
    if not isinstance(mode, str) or mode not in required_by_mode:
        raise ColorResolutionError("COLOR_INVALID_MODE", "Treatment mode is not supported.", {"field": "treatment.mode"})
    expected = required_by_mode[mode]
    if set(treatment) != expected:
        raise ColorResolutionError(
            "COLOR_INVALID_INPUT", "Treatment fields do not match the selected mode.", {"field": "treatment"}
        )
    if mode == "custom":
        _validate_hex(treatment["hex"], "COLOR_INVALID_HEX")
    if mode == "preset" and (
        not isinstance(treatment["preset"], str) or treatment["preset"] not in PRESET_HEX_BY_ID
    ):
        raise ColorResolutionError(
            "COLOR_INVALID_PRESET", "Preset identifier is not supported.", {"field": "treatment.preset"}
        )
    if "context" in payload and type(payload["context"]) is not dict:
        raise ColorResolutionError("COLOR_INVALID_INPUT", "Context must be an object.", {"field": "context"})


def _validate_context_shape(context: dict[str, Any]) -> None:
    if set(context) - _CONTEXT_FIELDS:
        raise ColorResolutionError("COLOR_INVALID_INPUT", "Context contains unsupported fields.", {"field": "context"})
    preference = context.get("track_preference")
    if preference is not None and type(preference) is not dict:
        raise ColorResolutionError("COLOR_INVALID_INPUT", "Track preference must be an object.")
    if type(preference) is dict:
        if set(preference) != {"hex"}:
            raise ColorResolutionError("COLOR_INVALID_INPUT", "Track preference must contain only a HEX value.")
        _validate_hex(preference["hex"], "COLOR_INVALID_HEX")

    palette = context.get("album_palette")
    if "album_palette" in context and type(palette) is not list:
        raise ColorResolutionError("COLOR_INVALID_INPUT", "Album palette must be an array.")
    if type(palette) is list:
        for entry in palette:
            if type(entry) is not dict or set(entry) - {"hex", "name"} or "hex" not in entry:
                raise ColorResolutionError("COLOR_INVALID_INPUT", "Palette entries require HEX and allow only an optional name.")
            _validate_hex(entry["hex"], "COLOR_INVALID_HEX")
            if "name" in entry and type(entry["name"]) is not str:
                raise ColorResolutionError("COLOR_INVALID_INPUT", "Palette name must be text.")

    if "album_default_preset" in context:
        default_preset = context["album_default_preset"]
        if type(default_preset) is not str or default_preset not in PRESET_HEX_BY_ID:
            raise ColorResolutionError(
                "COLOR_INVALID_PRESET", "Album default preset identifier is not supported.",
                {"field": "context.album_default_preset"},
            )

    mood = context.get("mood")
    if mood is not None and type(mood) is not str:
        raise ColorResolutionError("COLOR_INVALID_INPUT", "Mood must be unrestricted text.")
    if "features" in context:
        features = context["features"]
        if type(features) is not dict or set(features) - _FEATURE_FIELDS:
            raise ColorResolutionError("COLOR_INVALID_INPUT", "Features must contain supported numeric values only.")
        for name, value in features.items():
            if (
                type(value) not in (int, float)
                or (type(value) is float and not math.isfinite(value))
                or not 0.0 <= value <= 1.0
            ):
                raise ColorResolutionError(
                    "COLOR_INVALID_INPUT", "Numeric features must be finite values in [0, 1].", {"field": name}
                )


def _normalize_context_hex(context: dict[str, Any]) -> None:
    preference = context.get("track_preference")
    if isinstance(preference, dict):
        value = preference.get("hex")
        preference["hex"] = value.upper()
    palette = context.get("album_palette")
    if isinstance(palette, list):
        for entry in palette:
            entry["hex"] = entry["hex"].upper()


def _validate_intensity(value: Any) -> float:
    if (
        type(value) not in (int, float)
        or (type(value) is float and not math.isfinite(value))
        or not MIN_INTENSITY <= value <= MAX_INTENSITY
    ):
        raise ColorResolutionError(
            "COLOR_INVALID_INTENSITY", "Intensity must be a finite number in [0.0, 0.6].", {"field": "treatment.intensity"}
        )
    normalized = float(value)
    return 0.0 if normalized == 0.0 else normalized


def _validate_hex(value: Any, code: str) -> str:
    if not isinstance(value, str) or not _HEX_PATTERN.fullmatch(value):
        raise ColorResolutionError(code, "Color must be a six-digit sRGB HEX value.", {"field": "hex"})
    return value.upper()


def _copy_json_object(value: Mapping[str, Any], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ColorResolutionError("COLOR_INVALID_INPUT", f"{label.capitalize()} must be an object.")

    def copy_json(item: Any, path: str) -> Any:
        if item is None or type(item) in (bool, int):
            return item
        if type(item) is str:
            try:
                item.encode("utf-8", errors="strict")
            except UnicodeEncodeError as error:
                raise ColorResolutionError(
                    "COLOR_INVALID_INPUT", "Input contains malformed Unicode.", {"field": path}
                ) from error
            return item
        if type(item) is float:
            if not math.isfinite(item) and path != "input.treatment.intensity":
                raise ColorResolutionError(
                    "COLOR_INVALID_INPUT", "Input contains a non-finite number.", {"field": path}
                )
            return item
        if type(item) is dict:
            copied: dict[str, Any] = {}
            for key, child in item.items():
                if type(key) is not str:
                    raise ColorResolutionError("COLOR_INVALID_INPUT", "Object keys must be strings.", {"field": path})
                try:
                    key.encode("utf-8", errors="strict")
                except UnicodeEncodeError as error:
                    raise ColorResolutionError(
                        "COLOR_INVALID_INPUT", "Input contains a malformed Unicode key.", {"field": path}
                    ) from error
                copied[key] = copy_json(child, f"{path}.{key}")
            return copied
        if type(item) is list:
            return [copy_json(child, f"{path}[{index}]") for index, child in enumerate(item)]
        raise ColorResolutionError("COLOR_INVALID_INPUT", "Input must contain JSON-compatible values.", {"field": path})

    copied = copy_json(value, label)
    if not isinstance(copied, dict):
        raise ColorResolutionError("COLOR_INVALID_INPUT", f"{label.capitalize()} must be an object.")
    return copied