import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest

from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.interfaces.cli.video_export import (
    _run_worker,
    _submit_after_reconciliation,
    project_identity,
    run_video_export,
)


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


def test_cli_worker_executes_and_reports_exact_submitted_attempt():
    calls = []
    snapshot = SimpleNamespace(job_id="job-target", attempt_id="attempt-target")
    status = SimpleNamespace(
        job_id="job-target",
        attempt_id="attempt-target",
        status=SimpleNamespace(value="completed"),
    )

    class Worker:
        def run_next(self, job_id, attempt_id):
            calls.append((job_id, attempt_id))
            return snapshot, status

    result = _run_worker(Worker(), "job-target", "attempt-target")

    assert calls == [("job-target", "attempt-target")]
    assert result == (snapshot, status)


def test_cli_reconciles_interrupted_attempts_before_digest_submission(tmp_path):
    calls = []
    submitted = object()

    class Worker:
        def reconcile(self):
            calls.append("reconcile")

    class Exports:
        def submit(self, project, request):
            calls.append(("submit", project, request))
            return submitted

    request = object()
    result = _submit_after_reconciliation(Worker(), Exports(), tmp_path, request)

    assert calls == ["reconcile", ("submit", tmp_path, request)]
    assert result is submitted


def test_cli_worker_rejects_mismatched_worker_result():
    snapshot = SimpleNamespace(job_id="job-other", attempt_id="attempt-other")
    status = SimpleNamespace(
        job_id="job-other",
        attempt_id="attempt-other",
        status=SimpleNamespace(value="completed"),
    )

    class Worker:
        def run_next(self, _job_id, _attempt_id):
            return snapshot, status

    with pytest.raises(MediaInfrastructureError) as caught:
        _run_worker(Worker(), "job-target", "attempt-target")

    assert caught.value.code == "WORKER_FAILED"
