from datetime import datetime, timezone

import pytest

from wrld_video_studio.domain.canonical_json import canonical_json_bytes, canonical_sha256
from wrld_video_studio.domain.jobs import (
    InputFingerprint,
    JobState,
    JobStatus,
    create_snapshot,
)


def test_canonical_json_is_stable_across_mapping_order():
    assert canonical_json_bytes({"b": [2, 1], "a": 1}) == canonical_json_bytes(
        {"a": 1, "b": [2, 1]}
    )


@pytest.mark.parametrize(
    "value",
    [
        {"nan": float("nan")},
        {"positive_inf": float("inf")},
        {"negative_inf": float("-inf")},
        {1: "non-string key"},
        {"tuple": (1, 2)},
        {"set": {1, 2}},
        {"object": object()},
        {"surrogate": "\ud800"},
    ],
)
def test_canonical_json_rejects_non_json_values(value):
    with pytest.raises((TypeError, ValueError, UnicodeError)):
        canonical_json_bytes(value)


def test_snapshot_digest_changes_for_input_request_or_renderer():
    base = dict(
        job_id="job-1",
        attempt_id="attempt-1",
        created_at="2026-10-20T12:00:00Z",
        renderer_version="proof-1",
        request={"kind": "synthetic-proof", "tone_hz": 440},
        inputs=(InputFingerprint("tone.wav", "a" * 64),),
    )
    original = create_snapshot(**base)
    changed_input = create_snapshot(**{**base, "inputs": (InputFingerprint("tone.wav", "b" * 64),)})
    changed_request = create_snapshot(**{**base, "request": {"kind": "synthetic-proof", "tone_hz": 880}})
    changed_renderer = create_snapshot(**{**base, "renderer_version": "proof-2"})

    assert len(original.request_digest) == 64
    assert len(original.snapshot_digest) == 64
    assert changed_input.request_digest != original.request_digest
    assert changed_request.request_digest != original.request_digest
    assert changed_renderer.request_digest != original.request_digest


def test_snapshot_request_is_detached_from_callers_and_property_results():
    request = {"kind": "synthetic-proof", "settings": {"tone_hz": 440}}
    snapshot = create_snapshot(
        job_id="job-1",
        attempt_id="attempt-1",
        created_at="2026-10-20T12:00:00Z",
        renderer_version="proof-1",
        request=request,
        inputs=(),
    )
    digest = snapshot.snapshot_digest
    request["settings"]["tone_hz"] = 880
    exposed = snapshot.request
    exposed["settings"]["tone_hz"] = 220

    assert snapshot.request["settings"]["tone_hz"] == 440
    assert snapshot.snapshot_digest == digest


def test_attempts_preserve_request_digest_but_have_distinct_snapshot_identity():
    common = dict(
        job_id="job-1",
        created_at="2026-10-20T12:00:00Z",
        renderer_version="proof-1",
        request={"kind": "synthetic-proof"},
        inputs=(),
    )
    first = create_snapshot(attempt_id="attempt-1", **common)
    second = create_snapshot(attempt_id="attempt-2", **common)

    assert first.request_digest == second.request_digest
    assert first.snapshot_digest != second.snapshot_digest


def test_state_transition_table_and_revision():
    snapshot = create_snapshot(
        job_id="job-1",
        attempt_id="attempt-1",
        created_at="2026-10-20T12:00:00Z",
        renderer_version="proof-1",
        request={},
        inputs=(),
    )
    status = JobStatus.queued(snapshot)
    running = status.transition(JobState.RUNNING)
    validating = running.transition(JobState.VALIDATING, progress_percent=75)
    completed = validating.transition(JobState.COMPLETED, progress_percent=100)

    assert completed.revision == 3
    assert completed.status is JobState.COMPLETED
    with pytest.raises(ValueError, match="Illegal job transition"):
        completed.transition(JobState.RUNNING)
    with pytest.raises(ValueError, match="cannot regress"):
        validating.transition(JobState.CANCEL_REQUESTED, progress_percent=25)


def test_unknown_progress_stays_null_and_heartbeat_uses_injected_time():
    snapshot = create_snapshot(
        job_id="job-1",
        attempt_id="attempt-1",
        created_at="2026-10-20T12:00:00Z",
        renderer_version="proof-1",
        request={},
        inputs=(),
    )
    status = JobStatus.queued(snapshot)
    running = status.transition(JobState.RUNNING)
    instant = datetime(2026, 10, 20, 12, 1, tzinfo=timezone.utc)
    beat = running.heartbeat(instant)

    assert beat.progress_percent is None
    assert beat.last_heartbeat_at == "2026-10-20T12:01:00.000Z"


def test_attempt_snapshot_and_status_conform_to_wu2_schemas(schema_dir):
    import json

    from jsonschema import Draft202012Validator, FormatChecker

    snapshot_schema = json.loads(
        (schema_dir / "render-job-snapshot-v1.schema.json").read_text(encoding="utf-8")
    )
    status_schema = json.loads(
        (schema_dir / "render-job-status-v1.schema.json").read_text(encoding="utf-8")
    )
    snapshot = create_snapshot(
        job_id="job-1",
        attempt_id="attempt-1",
        created_at="2026-10-20T12:00:00Z",
        renderer_version="proof-1",
        request={"kind": "synthetic-proof"},
        inputs=(InputFingerprint("tone.wav", "a" * 64),),
    )
    Draft202012Validator(snapshot_schema, format_checker=FormatChecker()).validate(snapshot.to_dict())
    Draft202012Validator(status_schema, format_checker=FormatChecker()).validate(
        JobStatus.queued(snapshot).to_dict()
    )
