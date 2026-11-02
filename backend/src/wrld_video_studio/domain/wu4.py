from __future__ import annotations

import copy
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from wrld_video_studio.domain.canonical_json import canonical_sha256
from wrld_video_studio.domain.preview_cache import PreviewTreatmentSelection
from wrld_video_studio.domain.video_effects import VideoEffects
from wrld_video_studio.domain.video_effects_v2 import VideoEffectsV2
from wrld_video_studio.domain.video_effects_v3 import VideoEffectsV3
from wrld_video_studio.domain.video_export import SAMPLE_RATE
from wrld_video_studio.domain.video_export_v2 import MOTION_PROFILE_ID
from wrld_video_studio.domain.video_export_v3 import REFINED_PROFILE_ID
from wrld_video_studio.domain.video_export_v4 import PLAYER_PROFILE_ID


PROJECT_CATALOG_V1_VERSION = "wrld-project-catalog/1.0"
PROJECT_CATALOG_VERSION = "wrld-project-catalog/2.0"
PROJECT_INVENTORY_VERSION = "wrld-project-inventory/1.0"
PROJECT_SCAN_VERSION = "wrld-project-scan/1.0"
IMPORT_HANDOFF_VERSION = "wrld-import-handoff/1.0"
IMPORT_HANDOFF_V2_VERSION = "wrld-import-handoff/2.0"
PROJECT_PREFERENCES_VERSION = "wrld-project-preferences/1.0"
CREATION_STATE_VERSION = "wrld-creation-state/1.0"
CREATION_STATE_V2_VERSION = "wrld-creation-state/2.0"
CREATION_STATE_V3_VERSION = "wrld-creation-state/3.0"
CREATION_STATE_V4_VERSION = "wrld-creation-state/4.0"
INVENTORY_POLICY_VERSION = "inventory-policy/1.0"
ALBUM_READ_VERSION = "wrld-album-read/1.0"
VALIDATION_REPORT_VERSION = "wrld-project-validation/1.0"
EDITOR_STATE_VERSION = "wrld-editor-state/1.0"
API_ERROR_VERSION = "wrld-api-error/1.0"
PRIMARY_SHORT_NAMESPACE = uuid.UUID("53f141f0-6445-5fcf-9a24-f22a6813485e")
DEFAULT_SHORT_SAMPLES = 30 * SAMPLE_RATE
MIN_APPROVABLE_SHORT_SAMPLES = 5 * SAMPLE_RATE
DEFAULT_PREFERRED_SHORT_SECONDS = 45
MIN_PREFERRED_SHORT_SECONDS = 20
MAX_PREFERRED_SHORT_SECONDS = 120
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class InventoryScanPolicy:
    max_entries: int = 20_000
    max_depth: int = 32
    max_seconds: float = 600.0
    probe_concurrency: int = 2
    hash_concurrency: int = 1
    process_scan_concurrency: int = 2
    probe_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        limits = {
            "max_entries": (self.max_entries, 100_000),
            "max_depth": (self.max_depth, 64),
            "probe_concurrency": (self.probe_concurrency, 4),
            "hash_concurrency": (self.hash_concurrency, 2),
            "process_scan_concurrency": (self.process_scan_concurrency, 4),
        }
        for name, (value, ceiling) in limits.items():
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError(f"{name} must be an integer in [1, {ceiling}]")
        if type(self.max_seconds) not in (int, float) or not 0 < self.max_seconds <= 3600:
            raise ValueError("max_seconds must be in (0, 3600]")
        if type(self.probe_timeout_seconds) not in (int, float) or not 0 < self.probe_timeout_seconds <= 120:
            raise ValueError("probe_timeout_seconds must be in (0, 120]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_version": INVENTORY_POLICY_VERSION,
            "max_entries": self.max_entries,
            "max_depth": self.max_depth,
            "max_seconds": float(self.max_seconds),
            "probe_concurrency": self.probe_concurrency,
            "hash_concurrency": self.hash_concurrency,
            "process_scan_concurrency": self.process_scan_concurrency,
            "probe_timeout_seconds": float(self.probe_timeout_seconds),
        }


@dataclass(eq=False)
class WU4Error(Exception):
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.code or not self.message:
            raise ValueError("WU4 errors require a code and message")
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class TrustedProjectRoot:
    root_id: str
    label: str
    path: Any

    def __post_init__(self) -> None:
        if not _OPAQUE_ID.fullmatch(self.root_id):
            raise ValueError("Trusted project root IDs must be opaque ASCII identifiers")
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("Trusted project roots require a display label")


def portable_directory(value: Any) -> str:
    if value in ("", "."):
        return ""
    if not isinstance(value, str):
        raise ValueError("project location must be text")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        "\\" in value
        or posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        raise ValueError("project location must be portable and root-relative")
    return posix.as_posix()


def stable_primary_short_id(project_id: str, track_id: str) -> str:
    if not _OPAQUE_ID.fullmatch(project_id) or not _OPAQUE_ID.fullmatch(track_id):
        raise ValueError("stable project and track IDs are required")
    return f"short-{uuid.uuid5(PRIMARY_SHORT_NAMESPACE, project_id + chr(0) + track_id + chr(0) + 'primary')}"


def primary_short_document(
    project_id: str,
    track_id: str,
    sample_count: int,
) -> dict[str, Any]:
    if type(sample_count) is not int or sample_count <= 0:
        raise ValueError("track sample count must be positive")
    selected = min(sample_count, DEFAULT_SHORT_SAMPLES)
    return {
        "short_id": stable_primary_short_id(project_id, track_id),
        "track_id": track_id,
        "role": "primary",
        "start_sample": 0,
        "sample_count": selected,
        "origin": "fallback",
        "review_required": selected < MIN_APPROVABLE_SHORT_SAMPLES,
        "settings": {},
        "approval": None,
    }


def deep_merge_settings(base: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(base))

    def merge(target: dict[str, Any], update: Mapping[str, Any], path: str) -> None:
        for key, value in update.items():
            if value is None:
                raise WU4Error("EDITOR_STATE_INVALID", "Override values cannot be null.", {"path": path + key})
            if key not in target:
                raise WU4Error("EDITOR_STATE_INVALID", "An override field is unsupported.", {"path": path + key})
            current = target[key]
            if isinstance(value, Mapping):
                if not isinstance(current, Mapping):
                    raise WU4Error("EDITOR_STATE_INVALID", "An override value has the wrong shape.", {"path": path + key})
                nested = copy.deepcopy(dict(current))
                merge(nested, value, path + key + ".")
                target[key] = nested
            else:
                target[key] = copy.deepcopy(value)

    merge(result, patch, "")
    return result


def validate_effects(profile_id: str, value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        if profile_id == MOTION_PROFILE_ID:
            return VideoEffects.from_dict(value).to_dict()
        if profile_id == REFINED_PROFILE_ID:
            return VideoEffectsV2.from_dict(value).to_dict()
        if profile_id == PLAYER_PROFILE_ID:
            return VideoEffectsV3.from_dict(value).to_dict()
        if value:
            raise ValueError("the static profile has no effect configuration")
        return {}
    except (TypeError, ValueError) as error:
        raise WU4Error(
            "EDITOR_STATE_INVALID",
            "The resolved effect configuration is invalid for the project profile.",
        ) from error


def validate_treatment(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return PreviewTreatmentSelection.from_dict(value).to_dict()
    except Exception as error:
        raise WU4Error("EDITOR_STATE_INVALID", "The color treatment is invalid.") from error


def approval_digest(
    *,
    track_fingerprint: str,
    short: Mapping[str, Any],
    effective_settings: Mapping[str, Any],
    profile_id: str,
) -> str:
    if not _SHA256.fullmatch(track_fingerprint):
        raise ValueError("track fingerprint must be SHA-256")
    return canonical_sha256(
        {
            "track_fingerprint": track_fingerprint,
            "range": {
                "start_sample": short["start_sample"],
                "sample_count": short["sample_count"],
            },
            "effective_settings": dict(effective_settings),
            "profile_id": profile_id,
        }
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "ALBUM_READ_VERSION",
    "API_ERROR_VERSION",
    "CREATION_STATE_VERSION",
    "CREATION_STATE_V2_VERSION",
    "CREATION_STATE_V3_VERSION",
    "CREATION_STATE_V4_VERSION",
    "DEFAULT_PREFERRED_SHORT_SECONDS",
    "DEFAULT_SHORT_SAMPLES",
    "EDITOR_STATE_VERSION",
    "MIN_APPROVABLE_SHORT_SAMPLES",
    "IMPORT_HANDOFF_VERSION",
    "IMPORT_HANDOFF_V2_VERSION",
    "INVENTORY_POLICY_VERSION",
    "InventoryScanPolicy",
    "PROJECT_CATALOG_V1_VERSION",
    "PROJECT_CATALOG_VERSION",
    "PROJECT_INVENTORY_VERSION",
    "PROJECT_PREFERENCES_VERSION",
    "PROJECT_SCAN_VERSION",
    "MIN_PREFERRED_SHORT_SECONDS",
    "MAX_PREFERRED_SHORT_SECONDS",
    "TrustedProjectRoot",
    "VALIDATION_REPORT_VERSION",
    "WU4Error",
    "approval_digest",
    "deep_merge_settings",
    "portable_directory",
    "primary_short_document",
    "stable_primary_short_id",
    "utc_now",
    "validate_effects",
    "validate_treatment",
]
