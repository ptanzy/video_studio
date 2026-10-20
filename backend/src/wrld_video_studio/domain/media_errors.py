from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(eq=False)
class MediaInfrastructureError(Exception):
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    commit_state: str | None = None

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        if self.commit_state is not None:
            payload["commit_state"] = self.commit_state
        return payload


class IndeterminateMediaCommitError(MediaInfrastructureError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            "STORAGE_ERROR",
            message,
            details or {},
            commit_state="indeterminate",
        )