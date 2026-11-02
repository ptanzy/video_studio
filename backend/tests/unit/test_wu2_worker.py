import threading
from pathlib import Path

import pytest

from wrld_video_studio.application.media_jobs import MediaJobs, RenderWorker
from wrld_video_studio.application.render_coordination import ProcessLocalRenderAdmission
from wrld_video_studio.domain.jobs import JobState, MediaProbe, MediaStream
from wrld_video_studio.domain.media_errors import (
    IndeterminateMediaCommitError,
    MediaInfrastructureError,
)
from wrld_video_studio.infrastructure.artifact_store import FilesystemArtifactStore
from wrld_video_studio.infrastructure.job_repository import JsonJobRepository


def make_request(output="proof/fake.mp4"):
    return {
        "kind": "synthetic-proof",
        "inputs": ["input.dat"],
        "output_relative_path": output,
        "duration_seconds": 1.0,
        "duration_tolerance_seconds": 0.30,
        "width": 320,
        "height": 180,
        "frame_rate": 25,
        "tone_hz": 440,
        "video_codec": "h264",
        "audio_codec": "aac",
        "pixel_format": "yuv420p",
    }


class FakeProber:
    def probe(self, path):
        if not Path(path).is_file():
            raise MediaInfrastructureError("ASSET_NOT_FOUND", "missing input")
        return MediaProbe(str(path), "fake-probe", 1.0, (MediaStream(0, "audio", "pcm_s16le"),))


class FakeEncoder:
    def __init__(self, started=None, wait_for_cancel=False, error=None):
        self.started = started or threading.Event()
        self.wait_for_cancel = wait_for_cancel
        self.error = error

    def encode(self, plan, audio_input, staged_output, cancel_event=None, heartbeat=None, progress=None):
        self.started.set()
        if heartbeat is not None:
            heartbeat()
        if progress is not None:
            progress(40)
        if self.wait_for_cancel and cancel_event is not None:
            cancel_event.wait(timeout=5)
        if self.wait_for_cancel and cancel_event is not None and cancel_event.is_set():
            raise MediaInfrastructureError("PROCESS_CANCELLED", "cancelled")
        if self.error is not None:
            raise self.error
        staged_output.write_bytes(b"verified fake artifact")


class FakeVerifier:
    def __init__(self, reject=False):
        self.reject = reject

    def verify(self, path, expected):
        if self.reject or not Path(path).is_file():
            raise MediaInfrastructureError("OUTPUT_INVALID", "not verified")
        return MediaProbe(
            str(path),
            "fake-probe",
            expected["duration_seconds"],
            (
                MediaStream(
                    0,
                    "video",
                    expected["video_codec"],
                    width=expected["width"],
                    height=expected["height"],
                    frame_rate=expected["frame_rate"],
                    pixel_format=expected["pixel_format"],
                ),
                MediaStream(1, "audio", expected["audio_codec"]),
            ),
            "mp4",
            {"comment": f"wrld_snapshot:{expected['snapshot_digest']}"},
        )


def setup(
    tmp_path,
    schema_dir,
    *,
    encoder=None,
    verifier=None,
    repository=None,
    admission=None,
):
    source_root = tmp_path / "sources"
    source_root.mkdir(exist_ok=True)
    (source_root / "input.dat").write_bytes(b"stable source")
    repository = repository or JsonJobRepository(
        tmp_path / "jobs",
        schema_dir / "render-job-snapshot-v1.schema.json",
        schema_dir / "render-job-status-v1.schema.json",
    )
    artifacts = FilesystemArtifactStore(tmp_path / "output")
    worker = RenderWorker(
        repository,
        FakeProber(),
        encoder or FakeEncoder(),
        verifier or FakeVerifier(),
        artifacts,
        source_root,
        admission=admission or ProcessLocalRenderAdmission(),
    )
    jobs = MediaJobs(repository)
    return source_root, repository, artifacts, worker, jobs


def test_worker_cancel_request_waits_for_owned_encoder_to_acknowledge(tmp_path, schema_dir):
    started = threading.Event()
    source_root, repository, artifacts, worker, jobs = setup(
        tmp_path, schema_dir, encoder=FakeEncoder(started, wait_for_cancel=True)
    )
    snapshot, _ = jobs.submit(make_request(), source_root, "synthetic-proof-1")
    result_box = []
    thread = threading.Thread(target=lambda: result_box.append(worker.run_next()))
    thread.start()
    assert started.wait(timeout=5)

    requested = worker.request_cancel(snapshot.job_id, snapshot.attempt_id)

    thread.join(timeout=10)
    assert not thread.is_alive()
    assert requested.status is JobState.CANCEL_REQUESTED
    assert result_box[0][1].status is JobState.CANCELLED
    assert not (tmp_path / "output" / "proof" / "fake.mp4").exists()


def test_worker_cancel_request_while_waiting_for_shared_admission_never_encodes(
    tmp_path, schema_dir
):
    admission = ProcessLocalRenderAdmission()
    preview_lease = admission.acquire_preview()
    encoder = FakeEncoder()
    source_root, _repository, _artifacts, worker, jobs = setup(
        tmp_path,
        schema_dir,
        encoder=encoder,
        admission=admission,
    )
    snapshot, _ = jobs.submit(make_request(), source_root, "synthetic-proof-1")
    result_box = []
    thread = threading.Thread(target=lambda: result_box.append(worker.run_next()))
    thread.start()
    deadline = threading.Event()
    for _ in range(500):
        if admission.waiting_counts == (1, 0):
            break
        deadline.wait(0.01)
    assert admission.waiting_counts == (1, 0)

    requested = worker.request_cancel(snapshot.job_id, snapshot.attempt_id)
    thread.join(timeout=10)
    preview_lease.close()

    assert not thread.is_alive()
    assert requested.status is JobState.CANCEL_REQUESTED
    assert result_box[0][1].status is JobState.CANCELLED
    assert not encoder.started.is_set()
    assert admission.active_kind is None


def test_cancellation_cas_race_during_validating_is_acknowledged(tmp_path, schema_dir):
    source_root, base, artifacts, _worker, jobs = setup(tmp_path, schema_dir)

    class CancelAtValidatingWrite:
        def __getattr__(self, name):
            return getattr(base, name)

        def update_status(self, status, expected_revision):
            if status.status is JobState.VALIDATING:
                current = base.get_attempt(status.job_id, status.attempt_id)[1]
                requested = current.transition(JobState.CANCEL_REQUESTED)
                base.update_status(requested, current.revision)
            return base.update_status(status, expected_revision)

    snapshot, _ = jobs.submit(make_request(), source_root, "synthetic-proof-1")
    worker = RenderWorker(
        CancelAtValidatingWrite(), FakeProber(), FakeEncoder(), FakeVerifier(), artifacts, source_root,
        admission=ProcessLocalRenderAdmission(),
    )

    result = worker.run_next()

    assert result is not None
    assert result[1].status is JobState.CANCELLED
    assert not (tmp_path / "output" / "proof" / "fake.mp4").exists()


def test_cancel_from_separate_worker_before_publication_prevents_promotion(tmp_path, schema_dir):
    verifying = threading.Event()
    continue_verification = threading.Event()

    class BlockingVerifier(FakeVerifier):
        def verify(self, path, expected):
            verifying.set()
            assert continue_verification.wait(timeout=5)
            return super().verify(path, expected)

    source_root, repository, artifacts, _worker, jobs = setup(tmp_path, schema_dir)
    snapshot, _ = jobs.submit(make_request(), source_root, "synthetic-proof-1")
    worker = RenderWorker(
        repository, FakeProber(), FakeEncoder(), BlockingVerifier(), artifacts, source_root,
        admission=ProcessLocalRenderAdmission(),
    )
    result_box = []
    worker_thread = threading.Thread(target=lambda: result_box.append(worker.run_next()))
    worker_thread.start()
    assert verifying.wait(timeout=5)

    cancelling_worker = RenderWorker(
        repository, FakeProber(), FakeEncoder(), FakeVerifier(), artifacts, source_root,
        admission=ProcessLocalRenderAdmission(),
    )
    requested = cancelling_worker.request_cancel(snapshot.job_id, snapshot.attempt_id)
    continue_verification.set()
    worker_thread.join(timeout=10)

    assert not worker_thread.is_alive()
    assert requested.status is JobState.CANCEL_REQUESTED
    assert result_box[0][1].status is JobState.CANCELLED
    assert not (tmp_path / "output" / "proof" / "fake.mp4").exists()


def test_cancel_from_separate_worker_waits_for_committed_promotion(tmp_path, schema_dir):
    promoting = threading.Event()
    continue_promotion = threading.Event()
    cancel_started = threading.Event()
    cancel_finished = threading.Event()
    cancel_result = []

    class BlockingArtifacts(FilesystemArtifactStore):
        def promote(self, staged, relative_path):
            promoting.set()
            assert continue_promotion.wait(timeout=5)
            return super().promote(staged, relative_path)

    source_root, repository, _artifacts, _worker, jobs = setup(tmp_path, schema_dir)
    artifacts = BlockingArtifacts(tmp_path / "output")
    snapshot, _ = jobs.submit(make_request(), source_root, "synthetic-proof-1")
    worker = RenderWorker(
        repository, FakeProber(), FakeEncoder(), FakeVerifier(), artifacts, source_root,
        admission=ProcessLocalRenderAdmission(),
    )
    result_box = []
    worker_thread = threading.Thread(target=lambda: result_box.append(worker.run_next()))
    worker_thread.start()
    assert promoting.wait(timeout=5)

    cancelling_worker = RenderWorker(
        repository, FakeProber(), FakeEncoder(), FakeVerifier(), artifacts, source_root,
        admission=ProcessLocalRenderAdmission(),
    )

    def cancel():
        cancel_started.set()
        cancel_result.append(cancelling_worker.request_cancel(snapshot.job_id, snapshot.attempt_id))
        cancel_finished.set()

    cancel_thread = threading.Thread(target=cancel)
    cancel_thread.start()
    try:
        assert cancel_started.wait(timeout=5)
        assert not cancel_finished.wait(timeout=0.2)
    finally:
        continue_promotion.set()
    worker_thread.join(timeout=10)
    cancel_thread.join(timeout=10)

    assert not worker_thread.is_alive()
    assert not cancel_thread.is_alive()
    assert result_box[0][1].status is JobState.COMPLETED
    assert cancel_result[0].status is JobState.COMPLETED


def test_queued_cancellation_is_acknowledged_without_starting_worker(tmp_path, schema_dir):
    source_root, _repository, _artifacts, worker, jobs = setup(tmp_path, schema_dir)
    snapshot, _ = jobs.submit(make_request(), source_root, "synthetic-proof-1")

    cancelled = worker.request_cancel(snapshot.job_id, snapshot.attempt_id)

    assert cancelled.status is JobState.CANCELLED
    assert worker.run_next() is None


def test_retry_is_explicit_new_attempt_and_preserves_request_digest(tmp_path, schema_dir):
    source_root, repository, _artifacts, _worker, jobs = setup(tmp_path, schema_dir)
    original, queued = jobs.submit(make_request(), source_root, "synthetic-proof-1")
    cancelled = queued.transition(JobState.CANCELLED)
    repository.update_status(cancelled, queued.revision)

    retried, retry_status = jobs.retry(original.job_id, source_root)

    assert retried.job_id == original.job_id
    assert retried.attempt_id != original.attempt_id
    assert retried.request_digest == original.request_digest
    assert retried.snapshot_digest != original.snapshot_digest
    assert retry_status.status is JobState.QUEUED


def test_changed_source_prevents_explicit_retry(tmp_path, schema_dir):
    source_root, repository, _artifacts, _worker, jobs = setup(tmp_path, schema_dir)
    original, queued = jobs.submit(make_request(), source_root, "synthetic-proof-1")
    repository.update_status(queued.transition(JobState.CANCELLED), queued.revision)
    (source_root / "input.dat").write_bytes(b"changed source")

    with pytest.raises(MediaInfrastructureError) as caught:
        jobs.retry(original.job_id, source_root)
    assert caught.value.code == "SOURCE_CHANGED"


def test_source_change_during_output_verification_prevents_promotion(tmp_path, schema_dir):
    source_root, repository, artifacts, _worker, jobs = setup(tmp_path, schema_dir)
    source = source_root / "input.dat"

    class MutatingVerifier(FakeVerifier):
        def verify(self, path, expected):
            result = super().verify(path, expected)
            if ".wrld-staging" in str(path):
                source.write_bytes(b"changed during verification")
            return result

    snapshot, _ = jobs.submit(make_request(), source_root, "synthetic-proof-1")
    worker = RenderWorker(
        repository,
        FakeProber(),
        FakeEncoder(),
        MutatingVerifier(),
        artifacts,
        source_root,
        admission=ProcessLocalRenderAdmission(),
    )

    result = worker.run_next()

    assert result is not None and result[1].status is JobState.FAILED
    assert result[1].error["code"] == "SOURCE_CHANGED"
    assert not (tmp_path / "output" / "proof" / "fake.mp4").exists()


def test_restart_reconciles_verified_promoted_final_without_rerender(tmp_path, schema_dir):
    source_root, repository, artifacts, worker, jobs = setup(tmp_path, schema_dir)
    snapshot, queued = jobs.submit(make_request(), source_root, "synthetic-proof-1")
    running = queued.transition(JobState.RUNNING)
    repository.update_status(running, queued.revision)
    plan = worker._plan(snapshot)
    final = artifacts.resolve_final(plan.output_relative_path)
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(b"verified fake artifact")

    recovered = worker.reconcile()

    assert len(recovered) == 1
    assert recovered[0][1].status is JobState.COMPLETED
    assert recovered[0][1].revision == running.revision + 2


def test_restart_completes_cancel_requested_attempt_with_receipted_promotion(tmp_path, schema_dir):
    source_root, repository, artifacts, worker, jobs = setup(tmp_path, schema_dir)
    snapshot, queued = jobs.submit(make_request(), source_root, "synthetic-proof-1")
    running = queued.transition(JobState.RUNNING)
    repository.update_status(running, queued.revision)
    staged = artifacts.stage_path(snapshot.job_id, snapshot.attempt_id, "proof/fake.mp4")
    staged.write_bytes(b"verified fake artifact")
    final = artifacts.promote(staged, "proof/fake.mp4")
    cancel_worker = RenderWorker(
        repository, FakeProber(), FakeEncoder(), FakeVerifier(), artifacts, source_root,
        admission=ProcessLocalRenderAdmission(),
    )
    requested = cancel_worker.request_cancel(snapshot.job_id, snapshot.attempt_id)

    recovered = worker.reconcile()

    assert requested.status is JobState.CANCEL_REQUESTED
    assert recovered[0][1].status is JobState.COMPLETED
    assert artifacts.has_promotion_record(snapshot.job_id, snapshot.attempt_id, final)


def test_restart_fails_cancel_requested_attempt_with_unreceipted_final(tmp_path, schema_dir):
    source_root, repository, artifacts, worker, jobs = setup(tmp_path, schema_dir)
    snapshot, queued = jobs.submit(make_request(), source_root, "synthetic-proof-1")
    running = queued.transition(JobState.RUNNING)
    repository.update_status(running, queued.revision)
    final = artifacts.resolve_final("proof/fake.mp4")
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(b"verified fake artifact")
    cancel_worker = RenderWorker(
        repository, FakeProber(), FakeEncoder(), FakeVerifier(), artifacts, source_root,
        admission=ProcessLocalRenderAdmission(),
    )
    cancel_worker.request_cancel(snapshot.job_id, snapshot.attempt_id)

    recovered = worker.reconcile()

    assert recovered[0][1].status is JobState.FAILED
    assert recovered[0][1].error["message"] == "PROMOTION_ORDER_UNKNOWN"
    assert final.read_bytes() == b"verified fake artifact"


def test_restart_marks_missing_final_failed_and_preserves_invalid_final(tmp_path, schema_dir):
    source_root, repository, artifacts, worker, jobs = setup(
        tmp_path, schema_dir, verifier=FakeVerifier(reject=True)
    )
    snapshot, queued = jobs.submit(make_request(), source_root, "synthetic-proof-1")
    running = queued.transition(JobState.RUNNING)
    repository.update_status(running, queued.revision)
    final = artifacts.resolve_final(worker._plan(snapshot).output_relative_path)
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(b"preserve evidence")

    recovered = worker.reconcile()

    assert recovered[0][1].status is JobState.FAILED
    assert final.read_bytes() == b"preserve evidence"


def test_restart_with_missing_final_marks_running_attempt_failed(tmp_path, schema_dir):
    source_root, repository, _artifacts, worker, jobs = setup(tmp_path, schema_dir)
    snapshot, queued = jobs.submit(make_request(), source_root, "synthetic-proof-1")
    repository.update_status(queued.transition(JobState.RUNNING), queued.revision)

    recovered = worker.reconcile()

    assert recovered[0][1].status is JobState.FAILED
    assert recovered[0][1].error["code"] == "RECOVERABLE_INTERRUPTION"
    assert not (tmp_path / "output" / "proof" / "fake.mp4").exists()


def test_run_next_reconciles_stale_attempt_before_claiming_queued_job(tmp_path, schema_dir):
    source_root, repository, _artifacts, worker, jobs = setup(tmp_path, schema_dir)
    stale_snapshot, stale_queued = jobs.submit(
        make_request("proof/stale.mp4"), source_root, "synthetic-proof-1"
    )
    repository.update_status(stale_queued.transition(JobState.RUNNING), stale_queued.revision)
    queued_snapshot, _ = jobs.submit(
        make_request("proof/next.mp4"), source_root, "synthetic-proof-1", force=True
    )

    result = worker.run_next()

    assert repository.get_attempt(stale_snapshot.job_id, stale_snapshot.attempt_id)[1].status is JobState.FAILED
    assert result is not None and result[0].attempt_id == queued_snapshot.attempt_id
    assert result[1].status is JobState.COMPLETED


def test_run_next_target_executes_submitted_attempt_not_older_queued_job(tmp_path, schema_dir):
    source_root, repository, _artifacts, worker, jobs = setup(tmp_path, schema_dir)
    older, _ = jobs.submit(
        make_request("proof/older.mp4"), source_root, "synthetic-proof-1"
    )
    target, _ = jobs.submit(
        make_request("proof/target.mp4"),
        source_root,
        "synthetic-proof-1",
        force=True,
    )

    result = worker.run_next(target.job_id, target.attempt_id)

    assert result is not None
    assert (result[0].job_id, result[0].attempt_id) == (
        target.job_id,
        target.attempt_id,
    )
    assert result[1].status is JobState.COMPLETED
    assert repository.get_attempt(older.job_id, older.attempt_id)[1].status is JobState.QUEUED


def test_run_next_target_requires_complete_identity(tmp_path, schema_dir):
    _source_root, _repository, _artifacts, worker, _jobs = setup(tmp_path, schema_dir)

    with pytest.raises(MediaInfrastructureError) as caught:
        worker.run_next("job-only", None)

    assert caught.value.code == "INVALID_JOB"


def test_reconcile_is_rejected_while_worker_is_active(tmp_path, schema_dir):
    started = threading.Event()
    source_root, repository, artifacts, _worker, jobs = setup(
        tmp_path, schema_dir, encoder=FakeEncoder(started, wait_for_cancel=True)
    )
    snapshot, _ = jobs.submit(make_request(), source_root, "synthetic-proof-1")
    worker = RenderWorker(
        repository, FakeProber(), FakeEncoder(started, wait_for_cancel=True), FakeVerifier(), artifacts,
        source_root, admission=ProcessLocalRenderAdmission()
    )
    worker_thread = threading.Thread(target=worker.run_next)
    worker_thread.start()
    assert started.wait(timeout=5)

    with pytest.raises(MediaInfrastructureError) as caught:
        RenderWorker(
            repository, FakeProber(), FakeEncoder(), FakeVerifier(), artifacts, source_root,
            admission=ProcessLocalRenderAdmission(),
        ).reconcile()
    assert caught.value.code == "WORKER_ALREADY_ACTIVE"
    worker.request_cancel(snapshot.job_id, snapshot.attempt_id)
    worker_thread.join(timeout=10)
    assert not worker_thread.is_alive()


def test_nonzero_synthetic_encoder_failure_leaves_final_absent(tmp_path, schema_dir):
    source_root, _repository, _artifacts, worker, jobs = setup(
        tmp_path,
        schema_dir,
        encoder=FakeEncoder(error=MediaInfrastructureError("PROCESS_FAILED", "exit 7")),
    )
    snapshot, _ = jobs.submit(make_request("proof/nonzero.mp4"), source_root, "synthetic-proof-1")

    result = worker.run_next()

    assert result is not None and result[1].status is JobState.FAILED
    assert result[1].error["code"] == "PROCESS_FAILED"
    assert not (tmp_path / "output" / "proof" / "nonzero.mp4").exists()


def test_post_promotion_status_failure_is_indeterminate_then_reconciled(tmp_path, schema_dir):
    source_root, repository, artifacts, _worker, jobs = setup(tmp_path, schema_dir)
    snapshot, queued = jobs.submit(make_request(), source_root, "synthetic-proof-1")

    class FailTerminalWrite:
        root = repository.root
        failed_once = False

        def __getattr__(self, name):
            return getattr(repository, name)

        def update_status(self, status, expected_revision):
            if status.status is JobState.COMPLETED and not self.failed_once:
                self.failed_once = True
                raise IndeterminateMediaCommitError("injected terminal status failure")
            return repository.update_status(status, expected_revision)

    interrupted_worker = RenderWorker(
        repository=FailTerminalWrite(),
        prober=FakeProber(),
        encoder=FakeEncoder(),
        verifier=FakeVerifier(),
        artifacts=artifacts,
        source_root=source_root,
        admission=ProcessLocalRenderAdmission(),
    )
    with pytest.raises(IndeterminateMediaCommitError):
        interrupted_worker.run_next()
    assert repository.get_attempt(snapshot.job_id, snapshot.attempt_id)[1].status is JobState.VALIDATING

    recovered = interrupted_worker.run_next()
    assert recovered is None
    assert repository.get_attempt(snapshot.job_id, snapshot.attempt_id)[1].status is JobState.COMPLETED


def test_pre_replace_completion_write_failure_after_promotion_is_indeterminate(tmp_path, schema_dir):
    source_root, repository, artifacts, _worker, jobs = setup(tmp_path, schema_dir)
    snapshot, _ = jobs.submit(make_request(), source_root, "synthetic-proof-1")

    class FailCompletionBeforeReplace:
        root = repository.root
        failed_once = False

        def __getattr__(self, name):
            return getattr(repository, name)

        def update_status(self, status, expected_revision):
            if status.status is JobState.COMPLETED and not self.failed_once:
                self.failed_once = True
                raise MediaInfrastructureError("STORAGE_ERROR", "injected before replace")
            return repository.update_status(status, expected_revision)

    worker = RenderWorker(
        FailCompletionBeforeReplace(), FakeProber(), FakeEncoder(), FakeVerifier(), artifacts, source_root,
        admission=ProcessLocalRenderAdmission(),
    )
    with pytest.raises(IndeterminateMediaCommitError):
        worker.run_next()
    final = tmp_path / "output" / "proof" / "fake.mp4"
    assert final.is_file()
    assert repository.get_attempt(snapshot.job_id, snapshot.attempt_id)[1].status is JobState.VALIDATING

    recovered = RenderWorker(
        repository, FakeProber(), FakeEncoder(), FakeVerifier(), artifacts, source_root,
        admission=ProcessLocalRenderAdmission(),
    ).reconcile()
    assert recovered[0][1].status is JobState.COMPLETED
    assert final.is_file()
