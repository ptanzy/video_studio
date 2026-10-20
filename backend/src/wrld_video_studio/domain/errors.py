from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


ERROR_CODES = frozenset(
    {
        "INVALID_MANIFEST",
        "IDENTITY_REVIEW_REQUIRED",
        "DUPLICATE_RECORDING_ID",
        "REVISION_CONFLICT",
        "STORAGE_ERROR",
        "INTERNAL_ERROR",
    }
)


@dataclass(eq=False)
class StudioError(Exception):
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self) -> None:
        if self.code not in ERROR_CODES:
            raise ValueError(f"Unsupported WU1 error code: {self.code}")
        if not isinstance(self.message, str) or not self.message:
            raise ValueError("Error message must be a non-empty string")
        if not isinstance(self.details, dict):
            raise ValueError("Error details must be an object")
        _validate_json_object(self.details)
        if not isinstance(self.correlation_id, str) or not self.correlation_id.strip():
            raise ValueError("Correlation ID must be a non-empty string")
        try:
            self.message.encode("utf-8", errors="strict")
            self.correlation_id.encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise ValueError("Error strings must be valid UTF-8") from error
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "correlation_id": self.correlation_id,
            }
        }


class IndeterminateCommitError(StudioError):
    def __init__(self, message: str, details: dict[str, Any]) -> None:
        super().__init__("STORAGE_ERROR", message, details)


def _validate_json_object(value: dict[str, Any]) -> None:
    def validate(item: Any) -> None:
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float:
            if item != item or item in (float("inf"), float("-inf")):
                raise ValueError("Error details must not contain non-finite numbers")
            return
        if type(item) is list:
            for child in item:
                validate(child)
            return
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError("Error details object keys must be strings")
                validate(child)
            return
        raise ValueError("Error details must contain only JSON values")

    validate(value)
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    encoded.encode("utf-8", errors="strict")
    decoded = json.loads(encoded)
    if not _same_json_types(value, decoded):
        raise ValueError("Error details changed during JSON serialization")


def _same_json_types(original: Any, decoded: Any) -> bool:
    if type(original) is not type(decoded):
        return False
    if type(original) is dict:
        return original.keys() == decoded.keys() and all(
            _same_json_types(original[key], decoded[key]) for key in original
        )
    if type(original) is list:
        return len(original) == len(decoded) and all(
            _same_json_types(left, right) for left, right in zip(original, decoded)
        )
    return original == decoded
