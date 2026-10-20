import json

from wrld_video_studio.domain.jobs import JobEvent
from wrld_video_studio.infrastructure.event_sink import JsonlJobEventSink


def test_jsonl_events_are_correlated_and_do_not_leak_private_command_paths(tmp_path):
    sink = JsonlJobEventSink(tmp_path / "events")
    event = JobEvent(
        timestamp="2026-10-20T12:00:00Z",
        job_id="job/with separators",
        attempt_id="attempt:one",
        phase="render",
        event="ffmpeg_command",
        elapsed_ms=12,
        command=("<tool:ffmpeg.exe>", "-i", "<path>", "proof/partial.mp4"),
    )

    sink.emit(event)

    records = list((tmp_path / "events").glob("*.jsonl"))
    assert len(records) == 1
    payload = json.loads(records[0].read_text(encoding="utf-8"))
    assert payload["job_id"] == event.job_id
    assert payload["attempt_id"] == event.attempt_id
    assert "C:\\Users" not in records[0].read_text(encoding="utf-8")
    assert payload["command"][2] == "<path>"