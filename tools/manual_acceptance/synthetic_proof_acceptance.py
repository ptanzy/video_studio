"""Human acceptance harness for the existing WU2 synthetic-proof renderer.

Run this script from an ordinary Windows PowerShell terminal, not from Codex.
It deliberately uses the same application and infrastructure objects as the
real-media WU2 integration test. It does not construct an independent FFmpeg
render command or weaken the Windows Job Object ownership policy.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from wrld_video_studio.application.media_jobs import MediaJobs, RenderWorker
from wrld_video_studio.application.render_coordination import ProcessLocalRenderAdmission
from wrld_video_studio.domain.jobs import JobState, MediaProbe, MediaStream
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.infrastructure.artifact_store import FilesystemArtifactStore
from wrld_video_studio.infrastructure.artifact_verifier import FFmpegArtifactVerifier
from wrld_video_studio.infrastructure.event_sink import JsonlJobEventSink
from wrld_video_studio.infrastructure.ffmpeg_adapter import SyntheticMediaEncoder
from wrld_video_studio.infrastructure.ffprobe_adapter import FFprobeAdapter
from wrld_video_studio.infrastructure.job_repository import JsonJobRepository
from wrld_video_studio.infrastructure.media_tools import MediaToolchain
from wrld_video_studio.infrastructure.process_runner import SubprocessRunner


DEFAULT_AUDIO = Path(
    r"C:\Users\ptanz\job_search\WORLD_MUSIC\WRLD-FI\Albums\Echoes of Asia - Album 1"
    r"\Moonlight Over Gyeongju.wav"
)
DEFAULT_FFMPEG = Path(
    r"C:\Users\ptanz\AppData\Local\Programs\FFmpeg"
    r"\ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe"
)
DEFAULT_FFPROBE = Path(
    r"C:\Users\ptanz\AppData\Local\Programs\FFmpeg"
    r"\ffmpeg-9.0.2-essentials_build\bin\ffprobe.exe"
)
OUTPUT_FILENAME = "moonlight-over-gyeongju-synthetic-proof.mp4"
RENDERER_VERSION = "synthetic-proof-1"


class AcceptanceFailure(RuntimeError):
    """A failure with an identified acceptance-test stage."""


def _arguments(repository_root: Path) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render and verify one WU2 synthetic-proof MP4 through the existing application."
    )
    parser.add_argument("--audio", type=Path, default=DEFAULT_AUDIO)
    parser.add_argument("--ffmpeg", type=Path, default=DEFAULT_FFMPEG)
    parser.add_argument("--ffprobe", type=Path, default=DEFAULT_FFPROBE)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=repository_root.parent / "WRLD_Video_Studio_Acceptance",
        help="Parent directory for a new timestamped run directory; must be outside the repository.",
    )
    return parser.parse_args()


def _resolved_existing_file(path: Path, label: str) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as error:
        raise AcceptanceFailure(f"{label} does not exist or cannot be resolved: {path}") from error
    if not resolved.is_file():
        raise AcceptanceFailure(f"{label} is not a file: {resolved}")
    return resolved


def _run_directory(repository_root: Path, output_root: Path) -> Path:
    resolved_root = output_root.expanduser().resolve(strict=False)
    if resolved_root == repository_root or resolved_root.is_relative_to(repository_root):
        raise AcceptanceFailure(
            f"Acceptance output must be outside the repository: {resolved_root}"
        )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_root = resolved_root / f"synthetic-proof-{stamp}-{uuid.uuid4().hex[:8]}"
    run_root.mkdir(parents=True, exist_ok=False)
    return run_root


def _stream_dict(stream: MediaStream) -> dict[str, Any]:
    return {
        "index": stream.index,
        "codec_type": stream.codec_type,
        "codec_name": stream.codec_name,
        "sample_rate": stream.sample_rate,
        "channels": stream.channels,
        "width": stream.width,
        "height": stream.height,
        "frame_rate": stream.frame_rate,
        "duration_seconds": stream.duration_seconds,
        "pixel_format": stream.pixel_format,
    }


def _probe_dict(probe: MediaProbe) -> dict[str, Any]:
    return {
        "format_name": probe.format_name,
        "duration_seconds": probe.duration_seconds,
        "format_tags": dict(probe.format_tags),
        "streams": [_stream_dict(stream) for stream in probe.streams],
    }


def _full_decode(output_path: Path, runner: SubprocessRunner, ffmpeg_path: Path) -> None:
    # Verification only: rendering has already completed through RenderWorker.
    # Decode both output streams from the beginning through EOF without writing media.
    result = runner.run(
        [
            str(ffmpeg_path),
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-i",
            str(output_path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-f",
            "null",
            "-",
        ],
        timeout_seconds=300.0,
    )
    if result.cancelled or result.timed_out or result.returncode != 0:
        diagnostic = runner.sanitize_diagnostic(result.stderr_tail)
        raise AcceptanceFailure(
            "Full decode-to-EOF verification failed: "
            f"returncode={result.returncode}, timed_out={result.timed_out}, "
            f"cancelled={result.cancelled}, stderr_tail={diagnostic!r}"
        )


def _print_human_summary(summary: dict[str, Any]) -> None:
    output_probe = summary["output_probe"]
    video = next(
        stream for stream in output_probe["streams"] if stream["codec_type"] == "video"
    )
    audio = next(
        stream for stream in output_probe["streams"] if stream["codec_type"] == "audio"
    )
    print("\nSYNTHETIC-PROOF ACCEPTANCE: AUTOMATED CHECKS PASSED")
    print(f"Job result:       {summary['final_status']}")
    print(f"MP4 path:         {summary['output_path']}")
    print(f"File size:        {summary['output_size_bytes']:,} bytes")
    print(f"Container:        {output_probe['format_name']}")
    print(f"Duration:         {output_probe['duration_seconds']:.6f} seconds")
    print(f"Video:            {video['codec_name']} / {video['pixel_format']}")
    print(f"Resolution:       {video['width']}x{video['height']}")
    print(f"Frame rate:       {video['frame_rate']:.6f} fps")
    print(
        "Audio:            "
        f"{audio['codec_name']} / {audio['sample_rate']} Hz / {audio['channels']} channels"
    )
    print("Full decode:      passed from beginning through EOF")
    print(f"Result JSON:      {summary['result_json_path']}")
    print("Human playback:   PENDING")
    print("\nOpen in the Windows default media player:")
    print(f"  Invoke-Item -LiteralPath '{summary['output_path']}'")
    print("Open in VLC (default 64-bit installation):")
    print(
        "  & \"$env:ProgramFiles\\VideoLAN\\VLC\\vlc.exe\" "
        f"\"{summary['output_path']}\""
    )


def main() -> int:
    repository_root = Path(__file__).resolve().parents[2]
    args = _arguments(repository_root)
    stage = "argument validation"
    run_root: Path | None = None

    try:
        audio_path = _resolved_existing_file(args.audio, "Audio input")
        ffmpeg_path = _resolved_existing_file(args.ffmpeg, "FFmpeg executable")
        ffprobe_path = _resolved_existing_file(args.ffprobe, "FFprobe executable")
        schema_dir = repository_root / "contracts" / "schemas"
        _resolved_existing_file(
            schema_dir / "render-job-snapshot-v1.schema.json", "Snapshot schema"
        )
        _resolved_existing_file(
            schema_dir / "render-job-status-v1.schema.json", "Status schema"
        )

        # Use the application's supported process-local executable configuration.
        os.environ["WRLD_FFMPEG_PATH"] = str(ffmpeg_path)
        os.environ["WRLD_FFPROBE_PATH"] = str(ffprobe_path)

        stage = "media tool resolution"
        runner = SubprocessRunner()
        toolchain = MediaToolchain(runner)
        ffmpeg = toolchain.resolve("ffmpeg")
        ffprobe = toolchain.resolve("ffprobe")

        stage = "source FFprobe"
        prober = FFprobeAdapter(toolchain, runner)
        source_probe = prober.probe(audio_path)
        if source_probe.duration_seconds is None or source_probe.duration_seconds <= 0:
            raise AcceptanceFailure("Source FFprobe did not return a positive duration.")
        if not any(stream.codec_type == "audio" for stream in source_probe.streams):
            raise AcceptanceFailure("Source FFprobe did not return an audio stream.")

        stage = "acceptance directory creation"
        run_root = _run_directory(repository_root, args.output_root)
        repository = JsonJobRepository(
            run_root / "job-state",
            schema_dir / "render-job-snapshot-v1.schema.json",
            schema_dir / "render-job-status-v1.schema.json",
        )
        artifacts = FilesystemArtifactStore(run_root / "artifacts")
        verifier = FFmpegArtifactVerifier(prober, toolchain, runner)
        encoder = SyntheticMediaEncoder(toolchain, runner)
        worker = RenderWorker(
            repository,
            prober,
            encoder,
            verifier,
            artifacts,
            audio_path.parent,
            admission=ProcessLocalRenderAdmission(),
            event_sink=JsonlJobEventSink(run_root / "events"),
        )

        request = {
            "kind": "synthetic-proof",
            "inputs": [audio_path.name],
            "output_relative_path": f"proof/{OUTPUT_FILENAME}",
            "duration_seconds": source_probe.duration_seconds,
            "duration_tolerance_seconds": 0.30,
            "width": 320,
            "height": 180,
            "frame_rate": 25,
            "tone_hz": 440,
            "video_codec": "h264",
            "audio_codec": "aac",
            "pixel_format": "yuv420p",
        }

        stage = "job submission"
        snapshot, queued = MediaJobs(repository).submit(
            request, audio_path.parent, RENDERER_VERSION
        )

        stage = "RenderWorker execution"
        completed = worker.run_next()
        if completed is None:
            raise AcceptanceFailure("RenderWorker did not claim the queued job.")
        rendered_snapshot, final_status = completed
        if rendered_snapshot.job_id != snapshot.job_id:
            raise AcceptanceFailure("RenderWorker returned a different job identity.")
        if final_status.status is not JobState.COMPLETED:
            raise AcceptanceFailure(
                f"RenderWorker ended in {final_status.status.value}: {final_status.error!r}"
            )

        output_path = run_root / "artifacts" / "proof" / OUTPUT_FILENAME
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            raise AcceptanceFailure("Completed job did not publish a non-empty MP4.")

        stage = "final FFprobe"
        output_probe = prober.probe(output_path)

        stage = "full decode-to-EOF verification"
        _full_decode(output_path, runner, ffmpeg.path)

        stage = "result reporting"
        result_json_path = run_root / "automated-result.json"
        summary = {
            "automated_status": "passed",
            "human_playback_status": "pending",
            "run_root": str(run_root),
            "output_path": str(output_path),
            "output_size_bytes": output_path.stat().st_size,
            "result_json_path": str(result_json_path),
            "job_id": snapshot.job_id,
            "attempt_id": snapshot.attempt_id,
            "queued_status": queued.status.value,
            "final_status": final_status.status.value,
            "snapshot_digest": snapshot.snapshot_digest,
            "source_path": str(audio_path),
            "source_probe": _probe_dict(source_probe),
            "output_probe": _probe_dict(output_probe),
            "ffmpeg_path": str(ffmpeg.path),
            "ffmpeg_version": ffmpeg.version,
            "ffprobe_path": str(ffprobe.path),
            "ffprobe_version": ffprobe.version,
            "full_decode_to_eof": "passed",
            "encoder_sanitized_command": list(encoder.last_sanitized_command or ()),
        }
        result_json_path.write_text(
            json.dumps(summary, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _print_human_summary(summary)
        return 0
    except MediaInfrastructureError as error:
        print(f"SYNTHETIC-PROOF ACCEPTANCE FAILED during {stage}", file=sys.stderr)
        print(f"Application error code: {error.code}", file=sys.stderr)
        print(f"Message: {error.message}", file=sys.stderr)
        print(f"Details: {dict(error.details)!r}", file=sys.stderr)
        if run_root is not None:
            print(f"Run directory: {run_root}", file=sys.stderr)
        traceback.print_exc()
        return 1
    except Exception as error:
        print(f"SYNTHETIC-PROOF ACCEPTANCE FAILED during {stage}", file=sys.stderr)
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        if run_root is not None:
            print(f"Run directory: {run_root}", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
