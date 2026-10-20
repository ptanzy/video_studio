import math
import threading
import struct
import wave
from pathlib import Path

import pytest

from wrld_video_studio.application.media_jobs import MediaJobs, RenderWorker
from wrld_video_studio.domain.jobs import JobState
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.infrastructure.artifact_store import FilesystemArtifactStore
from wrld_video_studio.infrastructure.artifact_verifier import FFmpegArtifactVerifier
from wrld_video_studio.infrastructure.event_sink import JsonlJobEventSink
from wrld_video_studio.infrastructure.ffmpeg_adapter import SyntheticMediaEncoder
from wrld_video_studio.infrastructure.ffprobe_adapter import FFprobeAdapter
from wrld_video_studio.infrastructure.job_repository import JsonJobRepository
from wrld_video_studio.infrastructure.media_tools import MediaToolchain
from wrld_video_studio.infrastructure.process_runner import SubprocessRunner


pytestmark = pytest.mark.integration_ffmpeg


def _write_tone(path: Path, frequency: int = 440, duration: float = 1.0) -> None:
    sample_rate = 44100
    count = int(sample_rate * duration)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        frames = bytearray()
        for index in range(count):
            sample = int(12000 * math.sin(2 * math.pi * frequency * index / sample_rate))
            frames.extend(struct.pack("<h", sample))
        output.writeframes(frames)


def _services(tmp_path, schema_dir, source_root):
    runner = SubprocessRunner()
    toolchain = MediaToolchain(runner)
    try:
        ffmpeg = toolchain.resolve("ffmpeg")
        ffprobe = toolchain.resolve("ffprobe")
    except MediaInfrastructureError as error:
        pytest.skip(f"FFmpeg integration tools unavailable: {error.code}: {error.message}")
    repository = JsonJobRepository(
        tmp_path / "job-state",
        schema_dir / "render-job-snapshot-v1.schema.json",
        schema_dir / "render-job-status-v1.schema.json",
    )
    prober = FFprobeAdapter(toolchain, runner)
    verifier = FFmpegArtifactVerifier(prober, toolchain, runner)
    artifacts = FilesystemArtifactStore(tmp_path / "outputs")
    worker = RenderWorker(
        repository,
        prober,
        SyntheticMediaEncoder(toolchain, runner),
        verifier,
        artifacts,
        source_root,
        event_sink=JsonlJobEventSink(tmp_path / "events"),
    )
    return repository, worker, prober, ffmpeg, ffprobe


def test_generated_tone_probes_encodes_verifies_promotes_and_reuses(tmp_path, schema_dir):
    source_root = tmp_path / "source"
    source_root.mkdir()
    tone = source_root / "tone.wav"
    _write_tone(tone)
    repository, worker, prober, ffmpeg, ffprobe = _services(tmp_path, schema_dir, source_root)
    assert ffmpeg.path.is_absolute() and ffprobe.path.is_absolute()
    source_probe = prober.probe(tone)
    assert source_probe.duration_seconds is not None and source_probe.duration_seconds > 0
    assert any(stream.codec_type == "audio" for stream in source_probe.streams)

    jobs = MediaJobs(repository)
    request = {
        "kind": "synthetic-proof",
        "inputs": ["tone.wav"],
        "output_relative_path": "proof/synthetic.mp4",
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
    snapshot, queued = jobs.submit(request, source_root, "synthetic-proof-1")

    completed = worker.run_next()

    assert completed is not None
    rendered_snapshot, final_status = completed
    assert rendered_snapshot.job_id == snapshot.job_id
    assert queued.status is JobState.QUEUED
    assert final_status.status is JobState.COMPLETED
    final_path = tmp_path / "outputs" / "proof" / "synthetic.mp4"
    assert final_path.is_file() and final_path.stat().st_size > 0
    output_probe = prober.probe(final_path)
    assert {stream.codec_type for stream in output_probe.streams} >= {"video", "audio"}
    assert output_probe.format_tags["comment"] == f"wrld_snapshot:{snapshot.snapshot_digest}"

    duplicate, duplicate_status = jobs.submit(request, source_root, "synthetic-proof-1")
    assert duplicate.job_id == snapshot.job_id
    assert duplicate.attempt_id == snapshot.attempt_id
    assert duplicate_status.status is JobState.COMPLETED
    assert worker.run_next() is None


def test_changed_source_fails_before_encode_or_promotion(tmp_path, schema_dir):
    source_root = tmp_path / "source"
    source_root.mkdir()
    tone = source_root / "tone.wav"
    _write_tone(tone, 440)
    repository, worker, _prober, _ffmpeg, _ffprobe = _services(tmp_path, schema_dir, source_root)
    request = {
        "kind": "synthetic-proof",
        "inputs": ["tone.wav"],
        "output_relative_path": "proof/changed.mp4",
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
    snapshot, _ = MediaJobs(repository).submit(request, source_root, "synthetic-proof-1")
    _write_tone(tone, 880)

    result = worker.run_next()

    assert result is not None and result[1].status is JobState.FAILED
    assert result[1].error["code"] == "SOURCE_CHANGED"
    assert not (tmp_path / "outputs" / "proof" / "changed.mp4").exists()


def test_existing_different_snapshot_output_is_never_overwritten(tmp_path, schema_dir):
    source_root = tmp_path / "source"
    source_root.mkdir()
    _write_tone(source_root / "tone.wav")
    repository, worker, _prober, _ffmpeg, _ffprobe = _services(tmp_path, schema_dir, source_root)
    output = tmp_path / "outputs" / "proof" / "collision.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"existing unrelated artifact")
    request = {
        "kind": "synthetic-proof",
        "inputs": ["tone.wav"],
        "output_relative_path": "proof/collision.mp4",
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
    MediaJobs(repository).submit(request, source_root, "synthetic-proof-1")

    result = worker.run_next()

    assert result is not None and result[1].status is JobState.FAILED
    assert result[1].error["code"] in {"PROBE_FAILED", "PROBE_INVALID", "OUTPUT_PROVENANCE_MISMATCH"}
    assert output.read_bytes() == b"existing unrelated artifact"


def test_inflight_ffmpeg_cancellation_is_acknowledged_and_leaves_no_final(tmp_path, schema_dir):
    source_root = tmp_path / "source"
    source_root.mkdir()
    _write_tone(source_root / "tone.wav")
    repository, worker, _prober, _ffmpeg, _ffprobe = _services(tmp_path, schema_dir, source_root)
    request = {
        "kind": "synthetic-proof",
        "inputs": ["tone.wav"],
        "output_relative_path": "proof/cancelled.mp4",
        "duration_seconds": 8.0,
        "duration_tolerance_seconds": 0.30,
        "width": 1920,
        "height": 1080,
        "frame_rate": 30,
        "tone_hz": 440,
        "video_codec": "h264",
        "audio_codec": "aac",
        "pixel_format": "yuv420p",
    }
    snapshot, _ = MediaJobs(repository).submit(request, source_root, "synthetic-proof-1")
    outcomes = []
    worker_thread = threading.Thread(target=lambda: outcomes.append(worker.run_next()))
    worker_thread.start()
    try:
        deadline = __import__("time").monotonic() + 10
        running = False
        while __import__("time").monotonic() < deadline:
            status = repository.get_attempt(snapshot.job_id, snapshot.attempt_id)[1]
            if status.status is JobState.RUNNING:
                running = True
                break
            __import__("time").sleep(0.01)
        assert running, "worker never claimed the synthetic attempt"
        cancel_status = worker.request_cancel(snapshot.job_id, snapshot.attempt_id)
        assert cancel_status.status is JobState.CANCEL_REQUESTED
    finally:
        worker_thread.join(timeout=20)
    assert not worker_thread.is_alive(), "worker did not reap the cancelled FFmpeg process"
    final_status = repository.get_attempt(snapshot.job_id, snapshot.attempt_id)[1]
    assert final_status.status is JobState.CANCELLED
    assert not (tmp_path / "outputs" / "proof" / "cancelled.mp4").exists()


def test_corrupt_input_fails_without_promoting_or_mutating_source(tmp_path, schema_dir):
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = source_root / "bad.wav"
    source.write_bytes(b"corrupt audio fixture")
    original = source.read_bytes()
    repository, worker, _prober, _ffmpeg, _ffprobe = _services(tmp_path, schema_dir, source_root)
    request = {
        "kind": "synthetic-proof",
        "inputs": ["bad.wav"],
        "output_relative_path": "proof/corrupt-input.mp4",
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
    snapshot, _ = MediaJobs(repository).submit(request, source_root, "synthetic-proof-1")

    result = worker.run_next()

    assert result is not None and result[1].status is JobState.FAILED
    assert result[1].error["code"] == "PROBE_FAILED"
    assert source.read_bytes() == original
    assert not (tmp_path / "outputs" / "proof" / "corrupt-input.mp4").exists()