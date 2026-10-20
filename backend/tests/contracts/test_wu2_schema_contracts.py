import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from wrld_video_studio.domain.jobs import InputFingerprint, JobStatus, create_snapshot


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_snapshot_and_status_schemas_accept_generated_attempt(schema_dir):
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
        renderer_version="synthetic-proof-1",
        request={"kind": "synthetic-proof"},
        inputs=(InputFingerprint("audio/tone.wav", "a" * 64),),
    )
    Draft202012Validator(snapshot_schema, format_checker=FormatChecker()).validate(snapshot.to_dict())
    Draft202012Validator(status_schema, format_checker=FormatChecker()).validate(
        JobStatus.queued(snapshot).to_dict()
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.update(schema_version="9.0"),
        lambda data: data.update(request_digest="not-a-digest"),
            lambda data: data.update(request=[]),
            lambda data: data.update(inputs=[{"relative_path": "audio.wav"}]),
        lambda data: data.update(extra_field=True),
    ],
)
def test_snapshot_schema_rejects_invalid_contract_payloads(schema_dir, mutate):
    schema = json.loads(
        (schema_dir / "render-job-snapshot-v1.schema.json").read_text(encoding="utf-8")
    )
    data = create_snapshot(
        job_id="job-1",
        attempt_id="attempt-1",
        created_at="2026-10-20T12:00:00Z",
        renderer_version="synthetic-proof-1",
        request={"kind": "synthetic-proof"},
        inputs=(),
    ).to_dict()
    mutate(data)
    with pytest.raises((ValidationError, ValueError)):
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(data)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.update(status="partial"),
        lambda data: data.update(revision=-1),
        lambda data: data.update(snapshot_digest="bad"),
        lambda data: data.update(progress_percent=101),
        lambda data: data.update(unknown=True),
    ],
)
def test_status_schema_rejects_invalid_contract_payloads(schema_dir, mutate):
    schema = json.loads(
        (schema_dir / "render-job-status-v1.schema.json").read_text(encoding="utf-8")
    )
    snapshot = create_snapshot(
        job_id="job-1",
        attempt_id="attempt-1",
        created_at="2026-10-20T12:00:00Z",
        renderer_version="synthetic-proof-1",
        request={},
        inputs=(),
    )
    data = JobStatus.queued(snapshot).to_dict()
    mutate(data)
    with pytest.raises(ValidationError):
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(data)


@pytest.mark.parametrize(
    ("fixture_name", "schema_name", "valid"),
    [
        ("wu2-snapshot-valid.json", "render-job-snapshot-v1.schema.json", True),
        ("wu2-snapshot-invalid.json", "render-job-snapshot-v1.schema.json", False),
        ("wu2-status-valid.json", "render-job-status-v1.schema.json", True),
        ("wu2-status-invalid.json", "render-job-status-v1.schema.json", False),
    ],
)
def test_wu2_on_disk_json_contract_fixtures(schema_dir, fixture_name, schema_name, valid):
    fixture_path = FIXTURE_DIR / fixture_name
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    round_tripped = json.loads(encoded, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    assert round_tripped == payload

    schema = json.loads((schema_dir / schema_name).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    if valid:
        validator.validate(payload)
    else:
        with pytest.raises(ValidationError):
            validator.validate(payload)
