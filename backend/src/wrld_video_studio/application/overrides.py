from collections.abc import Mapping
from typing import Any

from wrld_video_studio.application.ports.override_store import OverrideStorePort


class SaveOverrides:
    def __init__(self, store: OverrideStorePort) -> None:
        self.store = store

    def execute(
        self,
        album_id: str,
        expected_revision: int,
        overrides: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self.store.update(album_id, expected_revision, overrides)
