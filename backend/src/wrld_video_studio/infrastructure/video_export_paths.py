from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.video_export_v4 import PlayerVideoExportPlan


# The pinned Gyan FFmpeg 9.0.2 build is long-path aware. Keep a conservative
# application limit well below the 32,767 UTF-16-unit Windows ceiling while
# allowing ordinary generated test/state nesting beyond legacy MAX_PATH.
WINDOWS_FFMPEG_PATH_LIMIT = 1024


class VideoExportPathPreflight:
    """Validate every FFmpeg-visible export path before a job is created."""

    def __init__(
        self,
        artifacts: Any,
        tool_paths: tuple[Path, ...] = (),
        *,
        windows: bool | None = None,
        max_path_characters: int | None = None,
    ) -> None:
        self.artifacts = artifacts
        self.tool_paths = tuple(Path(path).resolve() for path in tool_paths)
        self.windows = os.name == "nt" if windows is None else windows
        self.max_path_characters = (
            WINDOWS_FFMPEG_PATH_LIMIT
            if max_path_characters is None and self.windows
            else max_path_characters
        )

    def validate(self, project_root: Path, plan: Any) -> None:
        try:
            project_root.resolve(strict=True)
            paths = self.artifacts.preflight_paths(
                plan.output_relative_path,
                player_text=isinstance(plan, PlayerVideoExportPlan),
            )
        except MediaInfrastructureError:
            raise
        except OSError as error:
            raise MediaInfrastructureError(
                "INVALID_OUTPUT_PATH", "The export destination could not be resolved."
            ) from error
        for index, tool in enumerate(self.tool_paths):
            paths[f"media_tool_{index}"] = tool
        limit = self.max_path_characters
        if limit is None:
            return
        for purpose, path in paths.items():
            length = _windows_characters(path)
            if length > limit:
                raise MediaInfrastructureError(
                    "INVALID_OUTPUT_PATH",
                    "The resolved export path exceeds the configured Windows media-tool limit.",
                    {
                        "path_purpose": purpose,
                        "actual_characters": length,
                        "supported_characters": limit,
                    },
                )


def _windows_characters(path: Path) -> int:
    return len(str(path).encode("utf-16-le")) // 2
