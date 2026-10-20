from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class OverrideStorePort(Protocol):
    def read(self, album_id: str) -> dict[str, Any]: ...

    def create(self, album_id: str) -> dict[str, Any]: ...

    def update(
        self,
        album_id: str,
        expected_revision: int,
        overrides: Mapping[str, Any],
    ) -> dict[str, Any]: ...
