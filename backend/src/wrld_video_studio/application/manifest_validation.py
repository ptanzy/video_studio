from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from wrld_video_studio.domain.errors import StudioError


def validate_manifest(
    manifest: Any,
    schema_path: str | Path,
) -> dict[str, Any]:
    try:
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError) as error:
        raise StudioError(
            "INTERNAL_ERROR",
            "The manifest validation schema could not be loaded.",
        ) from error

    if not isinstance(manifest, Mapping):
        raise StudioError("INVALID_MANIFEST", "Manifest must be a JSON object.")

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(manifest), key=lambda item: list(item.absolute_path))
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.absolute_path)
        raise StudioError(
            "INVALID_MANIFEST",
            "Manifest does not match the supported structural subset.",
            {"path": path, "reason": first.message},
        )

    track_ids = [track["id"] for track in manifest["tracks"]]
    if len(track_ids) != len(set(track_ids)):
        raise StudioError(
            "INVALID_MANIFEST",
            "Track IDs must be unique within the manifest.",
            {"field": "tracks[].id"},
        )

    return dict(manifest)
