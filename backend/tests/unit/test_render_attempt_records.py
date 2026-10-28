import json
import threading
from pathlib import Path

from wrld_video_studio.domain.render_progress import RenderPhase, RenderProgress
from wrld_video_studio.infrastructure.render_attempt_records import (
    JsonRenderDiagnosticStore,
    JsonRenderProgressStore,
)


def test_progress_store_round_trips_versioned_attempt_state(tmp_path, schema_dir):
    store = JsonRenderProgressStore(
        tmp_path / "progress", schema_dir / "render-progress-v1.schema.json"
    )
    progress = RenderProgress(
        job_id="job-1",
        attempt_id="attempt-1",
        phase=RenderPhase.ENCODING,
        phase_progress_percent=99.994,
        current_track=None,
        total_tracks=12,
        processed_duration_seconds=599.96,
        total_duration_seconds=600.0,
        elapsed_seconds=605.0,
        eta_seconds=None,
        last_progress_at="2026-10-25T12:00:00Z",
        last_heartbeat_at="2026-10-25T12:00:00Z",
    )

    store.save(progress)

    assert store.load("job-1", "attempt-1") == progress
    assert store.reference("job-1", "attempt-1").startswith("progress/")
    assert "job-1" not in store.reference("job-1", "attempt-1")


def test_diagnostic_store_uses_private_hashed_reference(tmp_path, schema_dir):
    store = JsonRenderDiagnosticStore(
        tmp_path / "diagnostics", schema_dir / "render-diagnostic-v1.schema.json"
    )
    diagnostic = {
        "contract_version": "wrld-render-diagnostic/1.0",
        "job_id": "job-1",
        "attempt_id": "attempt-1",
        "request_digest": "a" * 64,
        "failure_phase": "probing_output",
        "error": {
            "code": "OUTPUT_INVALID",
            "message": "Output video color transfer check failed.",
            "predicate": "video color transfer",
            "expected": "bt709",
            "actual": None,
        },
        "ffmpeg_command": ["<tool:ffmpeg.exe>", "-i", "<path>"],
        "ffmpeg_stderr_tail": "bounded",
        "toolchain": {"ffmpeg": {"version": "9.0.2"}, "ffprobe": {"version": "9.0.2"}},
        "probe": {"streams": [{"color_transfer": None}]},
        "cleanup": {
            "outcome": "succeeded",
            "error_code": None,
            "started_at": "2026-10-25T12:00:01Z",
            "finished_at": "2026-10-25T12:00:01Z",
        },
        "failed_at": "2026-10-25T12:00:01Z",
    }

    reference = store.save(diagnostic)

    assert reference.startswith("diagnostics/")
    assert "job-1" not in reference and "attempt-1" not in reference
    stored = json.loads((tmp_path / reference).read_text(encoding="utf-8"))
    assert stored["error"]["predicate"] == "video color transfer"
    assert stored["cleanup"]["outcome"] == "succeeded"


def test_diagnostic_store_falls_back_when_primary_location_is_unwritable(
    tmp_path, schema_dir, monkeypatch
):
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"
    store = JsonRenderDiagnosticStore(
        primary,
        schema_dir / "render-diagnostic-v1.schema.json",
        fallback_root=fallback,
    )
    diagnostic = _diagnostic("job-1", "attempt-1")
    original = JsonRenderDiagnosticStore._write_unique

    def fail_primary(path, value):
        if primary in path.parents:
            raise OSError("simulated path failure")
        return original(path, value)

    monkeypatch.setattr(JsonRenderDiagnosticStore, "_write_unique", staticmethod(fail_primary))

    reference = store.save(diagnostic)

    assert reference.startswith("diagnostics-fallback/")
    assert (fallback / Path(reference).relative_to("diagnostics-fallback")).is_file()


def test_diagnostic_store_keeps_concurrent_attempts_distinct(tmp_path, schema_dir):
    store = JsonRenderDiagnosticStore(
        tmp_path / "diagnostics", schema_dir / "render-diagnostic-v1.schema.json"
    )
    references = []
    errors = []

    def writer(attempt):
        try:
            references.append(store.save(_diagnostic("job-1", attempt)))
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=writer, args=(f"attempt-{index}",)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(set(references)) == 8


def _diagnostic(job_id, attempt_id):
    return {
        "contract_version": "wrld-render-diagnostic/1.0",
        "job_id": job_id,
        "attempt_id": attempt_id,
        "request_digest": "a" * 64,
        "failure_phase": "probing_output",
        "error": {
            "code": "OUTPUT_INVALID",
            "message": "Invalid output.",
            "predicate": None,
            "expected": None,
            "actual": None,
        },
        "ffmpeg_command": [],
        "ffmpeg_stderr_tail": "",
        "toolchain": {},
        "probe": None,
        "cleanup": {
            "outcome": "succeeded",
            "error_code": None,
            "started_at": "2026-10-25T12:00:01Z",
            "finished_at": "2026-10-25T12:00:01Z",
        },
        "failed_at": "2026-10-25T12:00:01Z",
    }


def test_progress_store_serializes_cli_reads_with_worker_writes(tmp_path, schema_dir):
    store = JsonRenderProgressStore(
        tmp_path / "progress", schema_dir / "render-progress-v1.schema.json"
    )
    base = RenderProgress(
        job_id="job-1",
        attempt_id="attempt-1",
        phase=RenderPhase.ENCODING,
        phase_progress_percent=0.0,
        current_track=None,
        total_tracks=1,
        processed_duration_seconds=0.0,
        total_duration_seconds=1.0,
        elapsed_seconds=0.0,
        eta_seconds=None,
        last_progress_at="2026-10-25T12:00:00Z",
    )
    store.save(base)
    errors = []

    def writer():
        try:
            for value in range(101):
                store.save(
                    base.updated(
                        phase_progress_percent=float(value),
                        processed_duration_seconds=value / 100,
                    )
                )
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=writer)
    thread.start()
    while thread.is_alive():
        loaded = store.load("job-1", "attempt-1")
        assert loaded is not None
    thread.join()

    assert errors == []
    assert store.load("job-1", "attempt-1").phase_progress_percent == 100.0
