from __future__ import annotations

import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from wrld_video_studio.application.ports.media import ProcessRunner
from wrld_video_studio.domain.media_errors import MediaInfrastructureError


@dataclass(frozen=True)
class MediaTool:
    path: Path
    version: str


class MediaToolchain:
    def __init__(self, runner: ProcessRunner, configured_paths: dict[str, Path] | None = None) -> None:
        self.runner = runner
        self.configured_paths = dict(configured_paths or {})
        self._cache: dict[str, MediaTool] = {}
        self._lock = threading.Lock()

    def resolve(self, name: str) -> MediaTool:
        if name not in {"ffmpeg", "ffprobe"}:
            raise ValueError("Only ffmpeg and ffprobe are supported media tools")
        with self._lock:
            cached = self._cache.get(name)
        if cached is not None:
            return cached
        env_name = "WRLD_FFMPEG_PATH" if name == "ffmpeg" else "WRLD_FFPROBE_PATH"
        configured_path = self.configured_paths.get(name)
        configured = str(configured_path) if configured_path is not None else os.environ.get(env_name)
        if configured:
            candidate = Path(configured).expanduser()
            if not candidate.is_absolute():
                raise MediaInfrastructureError(
                    "INVALID_TOOL_PATH", f"{env_name} must be an absolute path."
                )
            executable = candidate
        else:
            found = shutil.which(name)
            if found is None:
                raise MediaInfrastructureError(
                    "MEDIA_TOOL_MISSING", f"{name} was not found on PATH or configured path."
                )
            executable = Path(found).resolve()
        try:
            is_file = executable.is_file()
        except OSError as error:
            raise MediaInfrastructureError(
                "MEDIA_TOOL_MISSING", f"Configured {name} executable is not accessible."
            ) from error
        if not is_file:
            raise MediaInfrastructureError(
                "MEDIA_TOOL_MISSING", f"Configured {name} executable does not exist."
            )
        result = self.runner.run([str(executable), "-version"], timeout_seconds=5.0)
        if result.returncode != 0 or not result.stdout.strip():
            raise MediaInfrastructureError(
                "MEDIA_TOOL_INVALID",
                f"Configured {name} did not report a usable version.",
                {"stderr_tail": self.runner.sanitize_diagnostic(result.stderr_tail)},
            )
        version = result.stdout.splitlines()[0].strip()
        tool = MediaTool(executable, version)
        with self._lock:
            self._cache[name] = tool
        return tool
