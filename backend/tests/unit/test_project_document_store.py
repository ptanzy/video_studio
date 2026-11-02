import copy

from wrld_video_studio.domain.errors import StudioError
from wrld_video_studio.infrastructure.project_document_store import ProjectDocumentStore


class MemoryOverrideStore:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    def read(self, project_id: str) -> dict:
        if project_id not in self.records:
            raise StudioError("STORAGE_ERROR", "Missing.")
        return copy.deepcopy(self.records[project_id])

    def create(self, project_id: str) -> dict:
        if project_id in self.records:
            raise StudioError("STORAGE_ERROR", "Exists.")
        value = {"revision": 0, "overrides": {}}
        self.records[project_id] = value
        return copy.deepcopy(value)

    def update(self, project_id: str, expected_revision: int, document: dict) -> dict:
        current = self.records[project_id]
        if current["revision"] != expected_revision:
            raise StudioError("REVISION_CONFLICT", "Stale.")
        value = {"revision": expected_revision + 1, "overrides": copy.deepcopy(document)}
        self.records[project_id] = value
        return copy.deepcopy(value)


def test_creation_document_store_reads_v1_and_atomically_publishes_v2_v3_and_v4(schema_dir):
    store = ProjectDocumentStore(
        MemoryOverrideStore(),  # type: ignore[arg-type]
        (
            schema_dir / "creation-state-v1.schema.json",
            schema_dir / "creation-state-v2.schema.json",
            schema_dir / "creation-state-v3.schema.json",
            schema_dir / "creation-state-v4.schema.json",
        ),
        label="Creation state",
    )
    v1 = store.create("project-1", {
        "contract_version": "wrld-creation-state/1.0", "project_id": "project-1",
        "revision": 1, "save_id": "initial", "preferred_short_duration_seconds": 45,
        "albums": [], "singles": [], "shorts": [], "state_digest": "0" * 64,
    })
    assert store.read("project-1") == v1
    v2 = store.update("project-1", v1["revision"], {
        **v1, "contract_version": "wrld-creation-state/2.0", "save_id": "upgrade",
        "visual_templates": [],
    })
    assert v2["revision"] == 2
    assert v2["contract_version"] == "wrld-creation-state/2.0"
    assert store.read("project-1") == v2
    v3 = store.update("project-1", v2["revision"], {
        **v2, "contract_version": "wrld-creation-state/3.0", "save_id": "upgrade-v3",
        "visual_template_families": [],
    })
    assert v3["revision"] == 3
    assert v3["contract_version"] == "wrld-creation-state/3.0"
    assert store.read("project-1") == v3
    v4 = store.update("project-1", v3["revision"], {
        **v3, "contract_version": "wrld-creation-state/4.0", "save_id": "upgrade-v4",
    })
    assert v4["revision"] == 4
    assert v4["contract_version"] == "wrld-creation-state/4.0"
    assert store.read("project-1") == v4
