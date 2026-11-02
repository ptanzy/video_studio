from __future__ import annotations

import threading
import time
from pathlib import Path

from wrld_video_studio.application.scan_coordinator import InventoryScanCoordinator
from wrld_video_studio.domain.wu4 import InventoryScanPolicy
from wrld_video_studio.infrastructure.override_store import OverrideStore
from wrld_video_studio.infrastructure.scan_attempt_store import ScanAttemptStore


ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "contracts" / "schemas"


class Catalogs:
    def resolve(self, project_id: str):
        return {"project_id": project_id}, None


class Inventories:
    catalogs = Catalogs()

    def scan(self, project_id: str, scan_id: str, cancel: threading.Event, progress):
        progress(1, 1)
        if cancel.is_set():
            from wrld_video_studio.domain.wu4 import WU4Error
            raise WU4Error("SCAN_CANCELLED", "cancelled")


class BlockingInventories(Inventories):
    def __init__(self) -> None:
        self.started = threading.Event()

    def scan(self, project_id: str, scan_id: str, cancel: threading.Event, progress):
        self.started.set()
        cancel.wait(timeout=5)
        from wrld_video_studio.domain.wu4 import WU4Error
        raise WU4Error("SCAN_CANCELLED", "cancelled")


def store(tmp_path: Path) -> ScanAttemptStore:
    return ScanAttemptStore(
        OverrideStore(tmp_path / "scans", SCHEMAS / "override-store-v1.schema.json"),
        SCHEMAS / "project-scan-v1.schema.json",
    )


def document(status: str) -> dict:
    return {
        "contract_version": "wrld-project-scan/1.0", "scan_id": "scan-old", "project_id": "project-1",
        "status": status, "started_at": "2026-10-30T00:00:00Z", "completed_at": None,
        "visited_entries": 3, "discovered_assets": 1, "progress_percent": None,
        "policy": InventoryScanPolicy().to_dict(), "retry_of_scan_id": None, "error": None,
    }


def test_restart_reconciles_running_scan_and_preserves_retry_ancestry(tmp_path):
    attempts = store(tmp_path)
    attempts.put(document("running"))
    coordinator = InventoryScanCoordinator(Inventories(), InventoryScanPolicy(), attempts)
    interrupted = coordinator.get("project-1", "scan-old")
    assert interrupted["status"] == "failed"
    assert interrupted["error"]["code"] == "SCAN_INTERRUPTED"
    retry = coordinator.start("project-1", "scan-old")
    assert retry["retry_of_scan_id"] == "scan-old"
    for _ in range(100):
        if coordinator.get("project-1", retry["scan_id"])["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.01)
    coordinator.close()
    persisted = {item["scan_id"]: item for item in attempts.all()}
    assert persisted[retry["scan_id"]]["status"] == "completed"


def test_restart_reconciles_cancel_requested_as_cancelled(tmp_path):
    attempts = store(tmp_path)
    value = document("cancel_requested")
    value["error"] = {"code": "SCAN_CANCEL_REQUESTED", "message": "requested", "details": {}}
    attempts.put(value)
    coordinator = InventoryScanCoordinator(Inventories(), InventoryScanPolicy(), attempts)
    restored = coordinator.get("project-1", "scan-old")
    assert restored["status"] == "cancelled"
    assert restored["error"]["code"] == "SCAN_CANCELLED"
    coordinator.close()


def test_active_cancellation_persists_requested_and_final_diagnostics(tmp_path):
    inventories, attempts = BlockingInventories(), store(tmp_path)
    coordinator = InventoryScanCoordinator(inventories, InventoryScanPolicy(), attempts)
    started = coordinator.start("project-1")
    assert inventories.started.wait(timeout=5)
    requested = coordinator.cancel("project-1", started["scan_id"])
    assert requested["status"] == "cancel_requested"
    assert requested["error"]["code"] == "SCAN_CANCEL_REQUESTED"
    for _ in range(100):
        completed = coordinator.get("project-1", started["scan_id"])
        if completed["status"] == "cancelled":
            break
        time.sleep(0.01)
    coordinator.close()
    persisted = {item["scan_id"]: item for item in attempts.all()}[started["scan_id"]]
    assert persisted["status"] == "cancelled"
    assert persisted["error"]["code"] == "SCAN_CANCELLED"
