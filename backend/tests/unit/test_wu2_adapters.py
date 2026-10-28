import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.jobs import ProcessExecution
from wrld_video_studio.infrastructure.ffprobe_adapter import FFprobeAdapter
from wrld_video_studio.infrastructure.media_tools import MediaToolchain
from wrld_video_studio.infrastructure.process_runner import SubprocessRunner
from wrld_video_studio.infrastructure.progress import FFmpegProgressParser


class FakeRunner:
    def __init__(self, result=None):
        self.result = result or ProcessExecution(0, "ffprobe version test", "")
        self.argv = []

    def run(self, argv, timeout_seconds, cancel_event=None, **kwargs):
        self.argv.append(argv)
        return self.result

    @staticmethod
    def sanitize_diagnostic(text):
        return SubprocessRunner.sanitize_diagnostic(text)


def test_tool_discovery_uses_configured_absolute_path_and_reports_version(tmp_path, monkeypatch):
    executable = tmp_path / "ffprobe.exe"
    executable.write_bytes(b"fixture executable path")
    monkeypatch.setenv("WRLD_FFPROBE_PATH", str(executable))
    runner = FakeRunner(ProcessExecution(0, "ffprobe version 7.fixture", ""))

    tool = MediaToolchain(runner).resolve("ffprobe")

    assert tool.path == executable
    assert tool.version == "ffprobe version 7.fixture"
    assert runner.argv[0][1] == "-version"


def test_tool_discovery_rejects_relative_configured_path(monkeypatch):
    monkeypatch.setenv("WRLD_FFMPEG_PATH", "relative/ffmpeg.exe")
    with pytest.raises(MediaInfrastructureError) as caught:
        MediaToolchain(FakeRunner()).resolve("ffmpeg")
    assert caught.value.code == "INVALID_TOOL_PATH"


def test_tool_discovery_reports_missing_executable(monkeypatch):
    monkeypatch.delenv("WRLD_FFMPEG_PATH", raising=False)
    monkeypatch.setattr("wrld_video_studio.infrastructure.media_tools.shutil.which", lambda _name: None)
    with pytest.raises(MediaInfrastructureError) as caught:
        MediaToolchain(FakeRunner()).resolve("ffmpeg")
    assert caught.value.code == "MEDIA_TOOL_MISSING"


def test_ffprobe_parses_known_and_unknown_stream_fields(tmp_path):
    adapter = FFprobeAdapter.__new__(FFprobeAdapter)
    probe = adapter._parse(
        tmp_path / "tone.wav",
        "ffprobe 7.fixture",
        {
            "format": {"format_name": "wav", "duration": "1.25", "tags": {"comment": "tag"}},
            "streams": [
                {
                    "index": 0,
                    "codec_type": "audio",
                    "codec_name": "pcm_s16le",
                    "sample_rate": "44100",
                    "channels": 2,
                    "duration": "1.25",
                }
            ],
        },
    )

    assert probe.duration_seconds == 1.25
    assert probe.streams[0].sample_rate == 44100
    assert probe.streams[0].width is None
    assert probe.format_tags == {"comment": "tag"}


@pytest.mark.parametrize("payload", ["{broken", "NaN", "[]"])
def test_ffprobe_rejects_malformed_or_non_object_output(tmp_path, payload):
    runner = FakeRunner(ProcessExecution(0, payload, ""))
    toolchain = MediaToolchain(runner)
    toolchain.resolve = lambda _name: type("Tool", (), {"path": Path("ffprobe"), "version": "v"})()
    source = tmp_path / "tone.wav"
    source.write_bytes(b"not actually probed by fake")
    with pytest.raises(MediaInfrastructureError) as caught:
        FFprobeAdapter(toolchain, runner).probe(source)
    assert caught.value.code == "PROBE_INVALID"


def test_ffprobe_failure_keeps_bounded_redacted_stderr(tmp_path):
    private_path = str(tmp_path / "private" / "source.wav")
    runner = FakeRunner(ProcessExecution(1, "", f"cannot read {private_path}"))
    toolchain = MediaToolchain(runner)
    toolchain.resolve = lambda _name: type("Tool", (), {"path": Path("ffprobe"), "version": "v"})()
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")

    with pytest.raises(MediaInfrastructureError) as caught:
        FFprobeAdapter(toolchain, runner).probe(source)

    diagnostic = caught.value.details["stderr_tail"]
    assert "cannot read" in diagnostic
    assert private_path not in diagnostic
    assert "<path>" in diagnostic


def test_ffmpeg_failure_keeps_bounded_redacted_stderr(tmp_path):
    from wrld_video_studio.domain.jobs import RenderPlan, create_snapshot
    from wrld_video_studio.infrastructure.ffmpeg_adapter import SyntheticMediaEncoder

    private_path = str(tmp_path / "private" / "source.wav")
    runner = FakeRunner(ProcessExecution(7, "", f"failed input {private_path}"))
    toolchain = type("Toolchain", (), {
        "resolve": lambda _self, _name: type("Tool", (), {"path": Path("ffmpeg"), "version": "v"})()
    })()
    snapshot = create_snapshot(
        job_id="job-1",
        attempt_id="attempt-1",
        created_at="2026-10-20T12:00:00Z",
        renderer_version="synthetic-proof-1",
        request={"kind": "synthetic-proof"},
        inputs=(),
    )
    plan = RenderPlan(snapshot, "out.mp4", 1, 320, 180, 25, 440, 0.3, "h264", "aac", "yuv420p")

    with pytest.raises(MediaInfrastructureError) as caught:
        SyntheticMediaEncoder(toolchain, runner).encode(plan, Path("in.wav"), Path("out.mp4"))

    diagnostic = caught.value.details["stderr_tail"]
    assert "failed input" in diagnostic
    assert private_path not in diagnostic
    assert "<path>" in diagnostic


def test_process_runner_uses_bounded_output_and_returns_nonzero_code():
    runner = SubprocessRunner(output_limit=1024, stderr_limit=64)
    result = runner.run(
        [getattr(sys, "_base_executable", sys.executable), "-c", "import sys; print('x' * 100000); print('e' * 1000, file=sys.stderr); sys.exit(7)"],
        timeout_seconds=10,
    )
    assert result.returncode == 7
    assert len(result.stdout.encode("utf-8")) <= 1024
    assert len(result.stderr_tail.encode("utf-8")) <= 64


def test_process_runner_uses_validated_working_directory(tmp_path):
    work = tmp_path / "attempt-owned"
    work.mkdir()
    result = SubprocessRunner().run(
        [getattr(sys, "_base_executable", sys.executable), "-c", "from pathlib import Path; print(Path.cwd().name)"],
        timeout_seconds=10,
        working_directory=work,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "attempt-owned"


def test_process_runner_rejects_missing_working_directory(tmp_path):
    with pytest.raises(MediaInfrastructureError) as failure:
        SubprocessRunner().run(
            [getattr(sys, "_base_executable", sys.executable), "-c", "print('never')"],
            timeout_seconds=10,
            working_directory=tmp_path / "missing",
        )
    assert failure.value.code == "INVALID_COMMAND"


def test_process_runner_times_out_and_reaps_owned_child():
    result = SubprocessRunner(grace_seconds=0.1).run(
        [getattr(sys, "_base_executable", sys.executable), "-c", "import time; time.sleep(30)"], timeout_seconds=0.1
    )
    assert result.timed_out
    assert result.returncode != 0


def test_process_runner_cancels_and_reaps_owned_child():
    cancellation = threading.Event()
    timer = threading.Timer(0.2, cancellation.set)
    timer.start()
    try:
        result = SubprocessRunner(grace_seconds=0.2).run(
            [getattr(sys, "_base_executable", sys.executable), "-c", "import time; time.sleep(30)"],
            timeout_seconds=10,
            cancel_event=cancellation,
        )
    finally:
        timer.cancel()
    assert result.cancelled
    assert result.returncode != 0


def test_process_runner_emits_periodic_heartbeat_while_owned_process_runs():
    heartbeats = []
    result = SubprocessRunner(heartbeat_interval_seconds=0.02).run(
        [getattr(sys, "_base_executable", sys.executable), "-c", "import time; time.sleep(0.15)"],
        timeout_seconds=2,
        heartbeat=lambda: heartbeats.append(True),
    )
    assert result.returncode == 0
    assert len(heartbeats) >= 2


def test_process_runner_reaps_process_when_heartbeat_callback_raises(tmp_path):
    marker = tmp_path / "child-survived.txt"
    spawned = tmp_path / "grandchild-spawned.txt"
    grandchild = (
        "import pathlib,time; time.sleep(0.5); "
        f"pathlib.Path({str(marker)!r}).write_text('alive')"
    )
    child = (
        "import pathlib,subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{grandchild!r}]); "
        f"pathlib.Path({str(spawned)!r}).write_text('yes'); "
        "time.sleep(30)"
    )

    def fail_heartbeat():
        deadline = time.monotonic() + 3
        while not spawned.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert spawned.exists()
        raise RuntimeError("injected heartbeat persistence failure")

    runner = SubprocessRunner(grace_seconds=0.1, heartbeat_interval_seconds=0.01)
    with pytest.raises(RuntimeError, match="injected heartbeat"):
        runner.run(
            [getattr(sys, "_base_executable", sys.executable), "-c", child],
            timeout_seconds=5,
            heartbeat=fail_heartbeat,
        )
        assert spawned.exists()
    time.sleep(0.7)
    assert not marker.exists()


def test_process_runner_reaps_process_when_progress_callback_raises(tmp_path):
    marker = tmp_path / "progress-child-survived.txt"
    grandchild = (
        "import pathlib,time; time.sleep(0.5); "
        f"pathlib.Path({str(marker)!r}).write_text('alive')"
    )
    child = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{grandchild!r}]); "
        "print('progress=continue',flush=True); time.sleep(30)"
    )

    def fail_progress(_chunk):
        raise RuntimeError("injected progress persistence failure")

    runner = SubprocessRunner(grace_seconds=0.1)
    with pytest.raises(RuntimeError, match="injected progress"):
        runner.run(
            [getattr(sys, "_base_executable", sys.executable), "-c", child],
            timeout_seconds=5,
            progress_callback=fail_progress,
        )
    time.sleep(0.7)
    assert not marker.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group descendant semantics")
def test_process_runner_kills_descendant_after_parent_exits(tmp_path):
    marker = tmp_path / "descendant-survived.txt"
    grandchild = (
        "import pathlib,time; time.sleep(0.35); "
        f"pathlib.Path({str(marker)!r}).write_text('alive')"
    )
    child = (
        "import subprocess,sys; "
        f"subprocess.Popen([sys.executable,'-c',{grandchild!r}]); "
        "print('parent-exit',flush=True)"
    )
    started = time.monotonic()

    result = SubprocessRunner(grace_seconds=0.2).run(
        [getattr(sys, "_base_executable", sys.executable), "-c", child],
        timeout_seconds=5,
    )

    assert result.stdout.strip() == "parent-exit"
    assert time.monotonic() - started < 3
    time.sleep(0.45)
    assert not marker.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object descendant semantics")
def test_process_runner_kills_windows_descendant_after_parent_exits(tmp_path):
    marker = tmp_path / "windows-descendant-survived.txt"
    grandchild_code = (
        "import pathlib,time; time.sleep(0.35); pathlib.Path("
        + repr(str(marker))
        + ").write_text('alive')"
    )
    child = (
        "import subprocess,sys; "
        f"subprocess.Popen([sys.executable,'-c',{grandchild_code!r}]); "
        "print('parent-exit',flush=True)"
    )
    started = time.monotonic()

    result = SubprocessRunner(grace_seconds=0.2).run(
        [getattr(sys, "_base_executable", sys.executable), "-c", child],
        timeout_seconds=5,
    )

    assert result.stdout.strip() == "parent-exit"
    assert time.monotonic() - started < 3
    time.sleep(0.45)
    assert not marker.exists()


def test_process_runner_redacts_absolute_paths_from_recorded_argv():
    executable = getattr(sys, "_base_executable", sys.executable)
    private_path = str(Path.cwd() / "private" / "source.wav")
    result = SubprocessRunner().run(
        [executable, "-c", "print('ok')", private_path], timeout_seconds=5
    )
    assert result.sanitized_argv[0].startswith("<tool:")
    assert private_path not in " ".join(result.sanitized_argv)
    assert "<path>" in result.sanitized_argv


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object process-tree semantics")
def test_process_runner_cancellation_reaps_owned_descendant():
    import win32api
    import win32con
    import win32event

    cancellation = threading.Event()
    timer = threading.Timer(0.5, cancellation.set)
    child_code = "import subprocess,sys,time; child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); print(child.pid,flush=True); time.sleep(30)"
    timer.start()
    try:
        result = SubprocessRunner(grace_seconds=0.25).run(
            [getattr(sys, "_base_executable", sys.executable), "-c", child_code],
            timeout_seconds=10,
            cancel_event=cancellation,
        )
    finally:
        timer.cancel()
    assert result.cancelled
    descendant_pid = int(result.stdout.strip())
    try:
        handle = win32api.OpenProcess(win32con.SYNCHRONIZE, False, descendant_pid)
    except win32api.error:
        return
    try:
        assert win32event.WaitForSingleObject(handle, 5000) == win32event.WAIT_OBJECT_0
    finally:
        win32api.CloseHandle(handle)


def test_progress_parser_keeps_unknown_null_and_monotonic_known_values():
    unknown = FFmpegProgressParser(None)
    for line in ("out_time_us=500000", "progress=continue"):
        update = unknown.feed_line(line)
    assert update is not None and update.progress_percent is None

    parser = FFmpegProgressParser(2.0)
    first = parser.feed_line("out_time_us=1000000")
    first = parser.feed_line("progress=continue")
    assert first is not None and first.progress_percent == 50
    parser.feed_line("out_time_us=500000")
    regressed = parser.feed_line("progress=continue")
    assert regressed is not None and regressed.progress_percent == 50
    parser.feed_line("out_time_us=3000000")
    ended = parser.feed_line("progress=end")
    assert ended is not None and ended.progress_percent == 100 and ended.ended


def test_progress_parser_marks_end_complete_when_timestamp_rounds_short():
    parser = FFmpegProgressParser(60.0)
    parser.feed_line("out_time_us=59996000")
    ended = parser.feed_line("progress=end")
    assert ended is not None and ended.progress_percent == 100 and ended.ended
