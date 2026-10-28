import argparse
from pathlib import Path

from wrld_video_studio.interfaces.cli.video_export import project_identity, run_video_export


def args(**updates):
    value = {
        "album_project": str(Path.cwd()),
        "target": "album",
        "track_id": None,
        "profile": "youtube-1080p30-v1",
        "ffmpeg_path": None,
        "ffprobe_path": None,
    }
    value.update(updates)
    return argparse.Namespace(**value)


def test_cli_rejects_incomplete_tool_override(capsys, tmp_path):
    code = run_video_export(args(ffmpeg_path=str(tmp_path / "ffmpeg.exe")), state_root=tmp_path)
    assert code == 2
    assert "INVALID_TOOL_PATH" in capsys.readouterr().err


def test_cli_requires_track_id(capsys, tmp_path):
    code = run_video_export(args(target="track"), state_root=tmp_path)
    assert code == 2
    assert "INVALID_EXPORT_REQUEST" in capsys.readouterr().err


def test_project_identity_is_deterministic(tmp_path):
    assert project_identity(tmp_path) == project_identity(tmp_path)
    assert len(project_identity(tmp_path)) == 64
