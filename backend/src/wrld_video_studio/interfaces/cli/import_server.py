from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from wrld_video_studio.domain.wu4 import TrustedProjectRoot
from wrld_video_studio.interfaces.cli.video_export import _schema_root
from wrld_video_studio.interfaces.http.app import WU4ApplicationConfig, serve_import


def add_import_server_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "serve-import", help="Run the local Import and Review backend"
    )
    parser.add_argument(
        "--project-root",
        action="append",
        required=True,
        help="Absolute trusted music-library location; repeat for multiple locations",
    )
    parser.add_argument("--state-root")
    parser.add_argument("--ffmpeg-path")
    parser.add_argument("--ffprobe-path")
    parser.add_argument("--port", type=int, default=8000)
    parser.set_defaults(command=run_import_server)


def run_import_server(args: argparse.Namespace) -> int:
    try:
        config = build_import_config(args)
        serve_import(config, port=args.port)
        return 0
    except (OSError, ValueError) as error:
        print(
            json.dumps(
                {"code": "IMPORT_SERVER_CONFIGURATION_INVALID", "message": str(error)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


def build_import_config(args: argparse.Namespace) -> WU4ApplicationConfig:
    if type(args.port) is not int or not 1 <= args.port <= 65_535:
        raise ValueError("The local HTTP port must be an integer in [1, 65535].")
    if (args.ffmpeg_path is None) != (args.ffprobe_path is None):
        raise ValueError("FFmpeg and FFprobe overrides must be supplied together.")
    roots = tuple(_trusted_root(value) for value in args.project_root)
    if len({item.root_id for item in roots}) != len(roots):
        raise ValueError("Trusted project locations must be unique.")
    state_root = (
        Path(args.state_root).expanduser()
        if args.state_root is not None
        else default_import_state_root()
    )
    if not state_root.is_absolute():
        raise ValueError("--state-root must be an absolute path.")
    state_root = state_root.resolve(strict=False)
    configured: dict[str, Path | None] = {"ffmpeg": None, "ffprobe": None}
    if args.ffmpeg_path is not None:
        configured = {
            "ffmpeg": _absolute_file(args.ffmpeg_path, "FFmpeg"),
            "ffprobe": _absolute_file(args.ffprobe_path, "FFprobe"),
        }
    schemas = _schema_root()
    return WU4ApplicationConfig(
        project_roots=roots,
        state_root=state_root,
        manifest_schemas=tuple(
            schemas / f"video-manifest-v{version}.schema.json"
            for version in range(1, 5)
        ),
        override_schema=schemas / "override-store-v1.schema.json",
        catalog_schema=schemas / "project-catalog-v2.schema.json",
        editor_state_schema=schemas / "editor-state-v1.schema.json",
        inventory_schema=schemas / "project-inventory-v1.schema.json",
        project_preferences_schema=schemas / "project-preferences-v1.schema.json",
        creation_state_schema=schemas / "creation-state-v1.schema.json",
        youtube_metadata_editor_schema=schemas / "youtube-metadata-editor-v1.schema.json",
        ffmpeg_path=configured["ffmpeg"],
        ffprobe_path=configured["ffprobe"],
    )


def default_import_state_root() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "WRLD Video Studio" / "state" / "import"
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "wrld-video-studio" / "import"


def _trusted_root(value: str) -> TrustedProjectRoot:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("Every --project-root must be an absolute path.")
    path = path.resolve(strict=True)
    if not path.is_dir():
        raise ValueError("Every --project-root must name an existing directory.")
    digest = hashlib.sha256(str(path).casefold().encode("utf-8")).hexdigest()[:20]
    return TrustedProjectRoot(f"music-{digest}", path.name or "Music Location", path)


def _absolute_file(value: str, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path.")
    path = path.resolve(strict=True)
    if not path.is_file():
        raise ValueError(f"{label} must name an existing file.")
    return path


__all__ = [
    "add_import_server_parser",
    "build_import_config",
    "default_import_state_root",
    "run_import_server",
]
