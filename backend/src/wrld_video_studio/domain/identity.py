from collections.abc import Iterable, Mapping
from typing import Any

from .errors import StudioError


def validate_recording_ids(candidates: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    recording_ids: list[str] = []
    seen: set[str] = set()

    for index, candidate in enumerate(candidates):
        recording_id = candidate.get("recording_id")
        if not isinstance(recording_id, str) or not recording_id.strip():
            raise StudioError(
                "IDENTITY_REVIEW_REQUIRED",
                "A non-empty recording_id is required for this join candidate.",
                {"candidate_index": index},
            )
        if recording_id in seen:
            raise StudioError(
                "DUPLICATE_RECORDING_ID",
                "Recording IDs in a join must be unique.",
                {"recording_id": recording_id, "candidate_index": index},
            )
        seen.add(recording_id)
        recording_ids.append(recording_id)

    return tuple(recording_ids)
