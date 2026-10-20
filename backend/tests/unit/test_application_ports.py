from typing import Any

from wrld_video_studio.application.overrides import SaveOverrides


class FakeOverrideStore:
    def __init__(self):
        self.calls = []

    def read(self, album_id: str) -> dict[str, Any]:
        return {"album_id": album_id}

    def create(self, album_id: str) -> dict[str, Any]:
        return {"album_id": album_id, "revision": 0}

    def update(self, album_id, expected_revision, overrides):
        self.calls.append((album_id, expected_revision, dict(overrides)))
        return {
            "album_id": album_id,
            "revision": expected_revision + 1,
            "overrides": dict(overrides),
        }


def test_save_overrides_uses_port_and_fake():
    fake = FakeOverrideStore()
    result = SaveOverrides(fake).execute("album-1", 4, {"opaque": "value"})

    assert fake.calls == [("album-1", 4, {"opaque": "value"})]
    assert result["revision"] == 5
