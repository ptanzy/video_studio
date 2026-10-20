from __future__ import annotations

import json
import hashlib
import os
import threading
from pathlib import Path

from wrld_video_studio.domain.canonical_json import canonical_json_bytes
from wrld_video_studio.domain.jobs import JobEvent
from wrld_video_studio.domain.media_errors import MediaInfrastructureError


class JsonlJobEventSink:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def emit(self, event: JobEvent) -> None:
        event_key = hashlib.sha256(
            f"{event.job_id}\0{event.attempt_id}".encode("utf-8")
        ).hexdigest()
        event_path = self.root / f"{event_key}.jsonl"
        payload = {
            "timestamp": event.timestamp,
            "job_id": event.job_id,
            "attempt_id": event.attempt_id,
            "phase": event.phase,
            "event": event.event,
            "elapsed_ms": max(0, event.elapsed_ms),
            "error": None if event.error is None else dict(event.error),
            "command": None if event.command is None else list(event.command),
        }
        try:
            encoded = canonical_json_bytes(payload) + b"\n"
            with self._lock, event_path.open("ab") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except (OSError, TypeError, ValueError) as error:
            raise MediaInfrastructureError("STORAGE_ERROR", "Could not append job event.") from error
