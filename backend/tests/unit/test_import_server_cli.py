from __future__ import annotations

from argparse import Namespace

import pytest

from wrld_video_studio.interfaces.cli.import_server import build_import_config


def arguments(project_root, **overrides):
    values = {
        "project_root": [str(project_root)],
        "state_root": None,
        "ffmpeg_path": None,
        "ffprobe_path": None,
        "port": 8000,
    }
    values.update(overrides)
    return Namespace(**values)


def test_import_server_builds_stable_private_configuration(tmp_path):
    music = tmp_path / "Music"; music.mkdir()
    state = tmp_path / "state"
    first = build_import_config(arguments(music, state_root=str(state)))
    second = build_import_config(arguments(music, state_root=str(state)))
    assert first.project_roots[0].root_id == second.project_roots[0].root_id
    assert first.project_roots[0].label == "Music"
    assert first.project_roots[0].path == music.resolve()
    assert first.state_root == state.resolve()
    assert first.catalog_schema.name == "project-catalog-v2.schema.json"
    assert first.creation_state_schema.name == "creation-state-v1.schema.json"


def test_import_server_rejects_partial_media_tool_override(tmp_path):
    music = tmp_path / "Music"; music.mkdir()
    with pytest.raises(ValueError, match="supplied together"):
        build_import_config(arguments(music, ffmpeg_path=str(tmp_path / "ffmpeg.exe")))
