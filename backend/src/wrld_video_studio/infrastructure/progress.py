from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProgressUpdate:
    values: dict[str, str]
    progress_percent: float | None
    ended: bool


class FFmpegProgressParser:
    def __init__(self, duration_seconds: float | None) -> None:
        self.duration_seconds = duration_seconds if duration_seconds and duration_seconds > 0 else None
        self._values: dict[str, str] = {}
        self._last_percent: float | None = None

    def feed_line(self, line: str) -> ProgressUpdate | None:
        text = line.strip()
        if not text or "=" not in text:
            return None
        key, value = text.split("=", 1)
        self._values[key] = value
        if key != "progress":
            return None
        ended = value == "end"
        percent = self._estimate(self._values)
        if ended and self.duration_seconds is not None:
            percent = 100.0
        if percent is not None:
            if self._last_percent is not None:
                percent = max(self._last_percent, percent)
            self._last_percent = percent
        update = ProgressUpdate(dict(self._values), percent, ended)
        self._values.clear()
        return update

    def _estimate(self, values: dict[str, str]) -> float | None:
        if self.duration_seconds is None:
            return None
        raw = values.get("out_time_us") or values.get("out_time_ms")
        if raw is None:
            return None
        try:
            timestamp_seconds = int(raw) / 1_000_000
        except ValueError:
            return None
        return min(100.0, max(0.0, timestamp_seconds / self.duration_seconds * 100.0))
