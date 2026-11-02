from __future__ import annotations

import copy
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from wrld_video_studio.domain.wu4 import InventoryScanPolicy, PROJECT_SCAN_VERSION, WU4Error, utc_now


class InventoryScanCoordinator:
    def __init__(self, inventories: Any, policy: InventoryScanPolicy, store: Any | None = None) -> None:
        self.inventories, self.policy, self.store = inventories, policy, store
        self._executor = ThreadPoolExecutor(max_workers=policy.process_scan_concurrency, thread_name_prefix="wu4-inventory")
        self._lock = threading.RLock()
        self._scans: dict[str, dict[str, Any]] = {
            item["scan_id"]: item for item in (() if store is None else store.all())
        }
        self._cancels: dict[str, threading.Event] = {}
        self._active_by_project: dict[str, str] = {}
        self._closed = False
        self._reconcile_interrupted()

    def start(self, project_id: str, retry_of_scan_id: str | None = None) -> dict[str, Any]:
        self.inventories.catalogs.resolve(project_id)
        with self._lock:
            if self._closed:
                raise WU4Error("PROJECT_UNAVAILABLE", "Inventory scanning is shutting down.")
            if project_id in self._active_by_project:
                raise WU4Error("SCAN_CAPACITY_EXCEEDED", "A scan is already active for this project.", {"scan_id": self._active_by_project[project_id]})
            if len(self._active_by_project) >= self.policy.process_scan_concurrency:
                raise WU4Error("SCAN_CAPACITY_EXCEEDED", "Inventory scan capacity is full.")
            if retry_of_scan_id is not None and retry_of_scan_id not in self._scans:
                raise WU4Error("SCAN_NOT_FOUND", "The referenced scan attempt is unknown.")
            scan_id = f"scan-{uuid.uuid4()}"
            document = {
                "contract_version": PROJECT_SCAN_VERSION, "scan_id": scan_id, "project_id": project_id,
                "status": "queued", "started_at": utc_now(), "completed_at": None,
                "visited_entries": 0, "discovered_assets": 0, "progress_percent": None,
                "policy": self.policy.to_dict(), "retry_of_scan_id": retry_of_scan_id, "error": None,
            }
            self._scans[scan_id] = document
            self._persist(document)
            self._cancels[scan_id] = threading.Event()
            self._active_by_project[project_id] = scan_id
            self._executor.submit(self._run, scan_id)
            return copy.deepcopy(document)

    def get(self, project_id: str, scan_id: str) -> dict[str, Any]:
        with self._lock:
            value = self._scans.get(scan_id)
            if value is None or value["project_id"] != project_id:
                raise WU4Error("SCAN_NOT_FOUND", "The inventory scan is unknown.")
            return copy.deepcopy(value)

    def cancel(self, project_id: str, scan_id: str) -> dict[str, Any]:
        with self._lock:
            value = self._scans.get(scan_id)
            if value is None or value["project_id"] != project_id:
                raise WU4Error("SCAN_NOT_FOUND", "The inventory scan is unknown.")
            if value["status"] in {"completed", "failed", "cancelled"}:
                return copy.deepcopy(value)
            value["status"] = "cancel_requested"
            value["error"] = {"code": "SCAN_CANCEL_REQUESTED", "message": "Cancellation was requested.", "details": {}}
            self._persist(value)
            self._cancels[scan_id].set()
            return copy.deepcopy(value)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            for event in self._cancels.values(): event.set()
        self._executor.shutdown(wait=True, cancel_futures=False)

    def _run(self, scan_id: str) -> None:
        with self._lock:
            value = self._scans[scan_id]
            if value["status"] == "cancel_requested":
                value["status"] = "cancelled"; value["completed_at"] = utc_now(); self._finish(value); return
            value["status"] = "running"
            self._persist(value)
            project_id = value["project_id"]
            cancel = self._cancels[scan_id]
        def progress(visited: int, discovered: int) -> None:
            with self._lock:
                status = self._scans[scan_id]
                status["visited_entries"] = visited
                status["discovered_assets"] = discovered
                if visited % 100 == 0:
                    self._persist(status)
        try:
            self.inventories.scan(project_id, scan_id, cancel, progress)
        except WU4Error as error:
            with self._lock:
                value = self._scans[scan_id]
                value["status"] = "cancelled" if error.code == "SCAN_CANCELLED" else "failed"
                value["completed_at"] = utc_now()
                value["error"] = {"code": error.code, "message": error.message, "details": error.details}
                self._finish(value)
        except BaseException:
            with self._lock:
                value = self._scans[scan_id]
                value["status"] = "failed"; value["completed_at"] = utc_now()
                value["error"] = {"code": "SCAN_INTERNAL_ERROR", "message": "The inventory scan failed unexpectedly.", "details": {}}
                self._finish(value)
        else:
            with self._lock:
                value = self._scans[scan_id]
                value["status"] = "completed"; value["completed_at"] = utc_now(); value["progress_percent"] = 100.0
                self._finish(value)

    def _finish(self, value: dict[str, Any]) -> None:
        self._active_by_project.pop(value["project_id"], None)
        self._persist(value)

    def _persist(self, value: dict[str, Any]) -> None:
        if self.store is not None:
            self.store.put(value)

    def _reconcile_interrupted(self) -> None:
        for value in self._scans.values():
            if value["status"] in {"queued", "running", "cancel_requested"}:
                was_cancelled = value["status"] == "cancel_requested"
                value["status"] = "cancelled" if was_cancelled else "failed"
                value["completed_at"] = utc_now()
                value["error"] = {
                    "code": "SCAN_CANCELLED" if was_cancelled else "SCAN_INTERRUPTED",
                    "message": "The scan was interrupted before this application session started.",
                    "details": {},
                }
                self._persist(value)


__all__ = ["InventoryScanCoordinator"]
