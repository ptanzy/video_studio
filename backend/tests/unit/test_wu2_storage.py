import threading
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import queue

import pytest

from wrld_video_studio.domain.jobs import (
    InputFingerprint,
    JobState,
    JobStatus,
    create_snapshot,
)
from wrld_video_studio.domain.media_errors import (
    IndeterminateMediaCommitError,
    MediaInfrastructureError,
)
from wrld_video_studio.infrastructure.artifact_store import FilesystemArtifactStore
from wrld_video_studio.infrastructure.job_repository import JsonJobRepository


def make_pair(job_id, attempt_id="attempt-1", now="2026-10-20T12:00:00Z"):
    snapshot = create_snapshot(
        job_id=job_id,
        attempt_id=attempt_id,
        created_at=now,
        renderer_version="synthetic-proof-1",
        request={"kind": "synthetic-proof", "tone_hz": 440},
        inputs=(InputFingerprint("tone.wav", "a" * 64),),
    )
    return snapshot, JobStatus.queued(snapshot)


def make_repo(tmp_path, schema_dir, **kwargs):
    return JsonJobRepository(
        tmp_path / "jobs",
        schema_dir / "render-job-snapshot-v1.schema.json",
        schema_dir / "render-job-status-v1.schema.json",
        **kwargs,
    )


def _probe_worker_lock(root, snapshot_schema, status_schema, result_queue):
    repository = JsonJobRepository(root, snapshot_schema, status_schema)
    try:
        with repository.worker_lock():
            result_queue.put("acquired")
    except MediaInfrastructureError as error:
        result_queue.put(error.code)


def _hold_worker_lock(root, snapshot_schema, status_schema, result_queue, release_event):
    repository = JsonJobRepository(root, snapshot_schema, status_schema)
    with repository.worker_lock():
        result_queue.put("acquired")
        release_event.wait(timeout=60)


def _probe_publication_lock(root, snapshot_schema, status_schema, job_id, attempt_id, result_queue):
    repository = JsonJobRepository(root, snapshot_schema, status_schema)
    with repository.publication_lock(job_id, attempt_id):
        result_queue.put("acquired")


def _probe_writer_lock(root, snapshot_schema, status_schema, result_queue):
    repository = JsonJobRepository(root, snapshot_schema, status_schema)
    try:
        with repository._writer_guard():
            result_queue.put("acquired")
    except MediaInfrastructureError as error:
        result_queue.put(error.code)


def test_repository_persists_and_reloads_snapshot_and_status(tmp_path, schema_dir):
    repository = make_repo(tmp_path, schema_dir)
    snapshot, status = make_pair("job-1")
    repository.create(snapshot, status)

    loaded_snapshot, loaded_status = JsonJobRepository(
        tmp_path / "jobs",
        schema_dir / "render-job-snapshot-v1.schema.json",
        schema_dir / "render-job-status-v1.schema.json",
    ).get("job-1")

    assert loaded_snapshot.to_dict() == snapshot.to_dict()
    assert loaded_status.to_dict() == status.to_dict()


def test_repository_revision_cas_and_stale_write_rejection(tmp_path, schema_dir):
    repository = make_repo(tmp_path, schema_dir)
    snapshot, status = make_pair("job-1")
    repository.create(snapshot, status)
    running = status.transition(JobState.RUNNING)
    repository.update_status(running, expected_revision=0)

    with pytest.raises(MediaInfrastructureError) as caught:
        repository.update_status(status.transition(JobState.CANCELLED), expected_revision=0)
    assert caught.value.code == "REVISION_CONFLICT"
    assert repository.get("job-1")[1].status is JobState.RUNNING


def test_request_digest_lookup_returns_existing_compatible_job(tmp_path, schema_dir):
    repository = make_repo(tmp_path, schema_dir)
    snapshot, status = make_pair("job-1")
    repository.create(snapshot, status)

    found = repository.find_by_request_digest(snapshot.request_digest)

    assert found is not None
    assert found[0].job_id == "job-1"
    assert found[0].request_digest == snapshot.request_digest


def test_retry_attempt_keeps_original_snapshot_and_request_digest(tmp_path, schema_dir):
    repository = make_repo(tmp_path, schema_dir)
    original, queued = make_pair("job-1")
    repository.create(original, queued)
    failed = queued.transition(JobState.CANCELLED)
    repository.update_status(failed, expected_revision=0)
    retry, retry_status = make_pair(
        "job-1", "attempt-2", "2026-10-20T12:02:00Z"
    )
    repository.create(retry, retry_status)

    assert repository.get_attempt("job-1", "attempt-1")[0].snapshot_digest == original.snapshot_digest
    assert retry.request_digest == original.request_digest
    assert retry.snapshot_digest != original.snapshot_digest
    assert repository.get("job-1")[0].attempt_id == "attempt-2"


def test_concurrent_claims_return_at_most_one_active_job(tmp_path, schema_dir):
    repository = make_repo(tmp_path, schema_dir)
    for job_id in ("job-1", "job-2", "job-3"):
        snapshot, status = make_pair(job_id)
        repository.create(snapshot, status)
    barrier = threading.Barrier(3)

    def claim():
        barrier.wait()
        return repository.claim_next()

    with ThreadPoolExecutor(max_workers=3) as executor:
        claimed = list(executor.map(lambda _: claim(), range(3)))

    assert sum(item is not None for item in claimed) == 1
    states = [repository.get(job_id)[1].status for job_id in ("job-1", "job-2", "job-3")]
    assert states.count(JobState.RUNNING) == 1


def test_worker_lock_excludes_a_second_process(tmp_path, schema_dir):
    repository = make_repo(tmp_path, schema_dir)
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    with repository.worker_lock():
        process = context.Process(
            target=_probe_worker_lock,
            args=(
                repository.root,
                schema_dir / "render-job-snapshot-v1.schema.json",
                schema_dir / "render-job-status-v1.schema.json",
                result_queue,
            ),
        )
        process.start()
        process.join(timeout=10)
    assert not process.is_alive()
    assert process.exitcode == 0
    assert result_queue.get(timeout=2) == "WORKER_ALREADY_ACTIVE"


def test_worker_lock_is_released_when_owner_process_is_terminated(tmp_path, schema_dir):
    repository = make_repo(tmp_path, schema_dir)
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    release_event = context.Event()
    owner = context.Process(
        target=_hold_worker_lock,
        args=(
            repository.root,
            schema_dir / "render-job-snapshot-v1.schema.json",
            schema_dir / "render-job-status-v1.schema.json",
            result_queue,
            release_event,
        ),
    )
    owner.start()
    assert result_queue.get(timeout=10) == "acquired"
    owner.terminate()
    owner.join(timeout=10)
    assert not owner.is_alive()

    contender = context.Process(
        target=_probe_worker_lock,
        args=(
            repository.root,
            schema_dir / "render-job-snapshot-v1.schema.json",
            schema_dir / "render-job-status-v1.schema.json",
            result_queue,
        ),
    )
    contender.start()
    contender.join(timeout=10)

    assert not contender.is_alive()
    assert contender.exitcode == 0
    assert result_queue.get(timeout=2) == "acquired"


def test_publication_lock_excludes_a_second_process(tmp_path, schema_dir):
    repository = make_repo(tmp_path, schema_dir)
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    with repository.publication_lock("job-1", "attempt-1"):
        process = context.Process(
            target=_probe_publication_lock,
            args=(
                repository.root,
                schema_dir / "render-job-snapshot-v1.schema.json",
                schema_dir / "render-job-status-v1.schema.json",
                "job-1",
                "attempt-1",
                result_queue,
            ),
        )
        process.start()
        with pytest.raises(queue.Empty):
            result_queue.get(timeout=0.5)
    process.join(timeout=10)
    assert not process.is_alive()
    assert process.exitcode == 0
    assert result_queue.get(timeout=2) == "acquired"


def test_repository_writer_guard_excludes_a_second_process(tmp_path, schema_dir):
    repository = make_repo(tmp_path, schema_dir)
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    with repository._writer_guard():
        process = context.Process(
            target=_probe_writer_lock,
            args=(
                repository.root,
                schema_dir / "render-job-snapshot-v1.schema.json",
                schema_dir / "render-job-status-v1.schema.json",
                result_queue,
            ),
        )
        process.start()
        process.join(timeout=10)
    assert not process.is_alive()
    assert process.exitcode == 0
    assert result_queue.get(timeout=2) == "REPOSITORY_BUSY"


def test_repository_pre_replace_failure_keeps_prior_status(tmp_path, schema_dir):
    repository = make_repo(tmp_path, schema_dir)
    snapshot, status = make_pair("job-1")
    repository.create(snapshot, status)

    def fail_replace(_source, _destination):
        raise OSError("injected failure before replace")

    failing = make_repo(tmp_path, schema_dir, replace=fail_replace)
    with pytest.raises(MediaInfrastructureError) as caught:
        failing.update_status(status.transition(JobState.RUNNING), expected_revision=0)
    assert caught.value.code == "STORAGE_ERROR"
    assert repository.get("job-1")[1].revision == 0
    assert repository.get("job-1")[1].status is JobState.QUEUED


def test_repository_post_replace_failure_is_indeterminate(tmp_path, schema_dir):
    repository = make_repo(tmp_path, schema_dir)
    snapshot, status = make_pair("job-1")
    repository.create(snapshot, status)

    def fail_sync(_directory):
        raise OSError("injected directory sync failure")

    failing = make_repo(tmp_path, schema_dir, sync_directory=fail_sync)
    with pytest.raises(IndeterminateMediaCommitError):
        failing.update_status(status.transition(JobState.RUNNING), expected_revision=0)
    assert repository.get("job-1")[1].status is JobState.RUNNING


def test_artifact_store_rejects_traversal_absolute_and_reserved_paths(tmp_path):
    store = FilesystemArtifactStore(tmp_path / "outputs")
    for path in ("../outside.mp4", str(tmp_path / "outside.mp4"), ".wrld-staging/escape.mp4"):
        with pytest.raises(MediaInfrastructureError) as caught:
            store.resolve_final(path)
        assert caught.value.code == "INVALID_OUTPUT_PATH"


def test_artifact_store_rejects_symlink_escape(tmp_path):
    output = tmp_path / "outputs"
    outside = tmp_path / "outside"
    output.mkdir()
    outside.mkdir()
    link = output / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"directory symlinks unavailable: {error}")

    store = FilesystemArtifactStore(output)
    with pytest.raises(MediaInfrastructureError) as caught:
        store.resolve_final("linked/escape.mp4")
    assert caught.value.code == "INVALID_OUTPUT_PATH"


def test_artifact_store_stages_promotes_and_cleans_exact_attempt_file(tmp_path):
    store = FilesystemArtifactStore(tmp_path / "outputs")
    staged = store.stage_path("job-1", "attempt-1", "proof/output.mp4")
    staged.write_bytes(b"synthetic")
    final = store.promote(staged, "proof/output.mp4")
    assert final.read_bytes() == b"synthetic"

    other = store.stage_path("job-1", "attempt-2", "proof/output.mp4")
    other.write_bytes(b"owned staging")
    store.cleanup_owned("job-1", "attempt-2")
    assert final.exists()
    assert not other.exists()


def test_artifact_cleanup_preserves_unregistered_attempt_files(tmp_path):
    output_root = tmp_path / "outputs"
    store = FilesystemArtifactStore(output_root)
    owned = store.stage_path("job-1", "attempt-1", "proof/output.mp4")
    owned.write_bytes(b"owned")
    unowned = owned.parent / "foreign.partial.mp4"
    unowned.write_bytes(b"not owned")

    FilesystemArtifactStore(output_root).cleanup_owned("job-1", "attempt-1")

    assert not owned.exists()
    assert unowned.read_bytes() == b"not owned"


def test_artifact_store_rejects_staging_root_symlink_escape(tmp_path):
    output = tmp_path / "outputs"
    outside = tmp_path / "outside-staging"
    output.mkdir()
    outside.mkdir()
    try:
        (output / ".wrld-staging").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"directory symlinks unavailable: {error}")
    store = FilesystemArtifactStore(output)

    with pytest.raises(MediaInfrastructureError) as caught:
        store.stage_path("job", "attempt", "proof/output.mp4")
    assert caught.value.code == "INVALID_OUTPUT_PATH"
