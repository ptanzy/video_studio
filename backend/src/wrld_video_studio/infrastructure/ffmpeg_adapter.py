from __future__ import annotations

from pathlib import Path

from wrld_video_studio.domain.jobs import RenderPlan
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.infrastructure.media_tools import MediaToolchain
from wrld_video_studio.infrastructure.progress import FFmpegProgressParser
from wrld_video_studio.application.ports.media import ProcessRunner


class SyntheticMediaEncoder:
    """Encoder for the WU2 infrastructure proof only; not an album renderer."""

    def __init__(self, toolchain: MediaToolchain, runner: ProcessRunner) -> None:
        self.toolchain = toolchain
        self.runner = runner
        self.last_sanitized_command: tuple[str, ...] | None = None

    def encode(
        self,
        plan: RenderPlan,
        audio_input: Path,
        staged_output: Path,
        cancel_event=None,
        heartbeat=None,
        progress=None,
    ) -> None:
        if plan.snapshot.request.get("kind") != "synthetic-proof":
            raise MediaInfrastructureError(
                "INVALID_RENDER_PLAN", "WU2 encoder accepts only synthetic proof plans."
            )
        if (plan.video_codec, plan.audio_codec, plan.pixel_format) != ("h264", "aac", "yuv420p"):
            raise MediaInfrastructureError(
                "INVALID_RENDER_PLAN", "Synthetic proof supports only the declared H.264/AAC test profile."
            )
        tool = self.toolchain.resolve("ffmpeg")
        staged_output.parent.mkdir(parents=True, exist_ok=True)
        args = [
            str(tool.path),
            "-hide_banner", "-nostdin", "-v", "error", "-xerror", "-nostats",
            "-progress", "pipe:1",
            "-f", "lavfi", "-i",
            f"color=c=black:s={plan.width}x{plan.height}:r={plan.frame_rate}:d={plan.duration_seconds}",
            "-i", str(audio_input),
            "-map", "0:v:0", "-map", "1:a:0",
            "-t", str(plan.duration_seconds),
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k",
            "-metadata", f"comment=wrld_snapshot:{plan.snapshot.snapshot_digest}",
            "-movflags", "+faststart",
            "-y", str(staged_output),
        ]
        parser = FFmpegProgressParser(plan.duration_seconds)
        pending = ""

        def parse_progress(chunk: str) -> None:
            nonlocal pending
            pending += chunk
            lines = pending.splitlines(keepends=True)
            pending = ""
            if lines and not lines[-1].endswith(("\n", "\r")):
                pending = lines.pop()
            for line in lines:
                update = parser.feed_line(line)
                if update is not None and progress is not None and update.progress_percent is not None:
                    progress(update.progress_percent)

        result = self.runner.run(
            args,
            timeout_seconds=60.0,
            cancel_event=cancel_event,
            heartbeat=heartbeat,
            progress_callback=parse_progress,
        )
        self.last_sanitized_command = result.sanitized_argv
        if result.cancelled:
            raise MediaInfrastructureError("PROCESS_CANCELLED", "Synthetic encode was cancelled.")
        if result.timed_out:
            raise MediaInfrastructureError(
                "PROCESS_TIMEOUT",
                "Synthetic encode exceeded its time limit.",
                {"stderr_tail": self.runner.sanitize_diagnostic(result.stderr_tail)},
            )
        if result.returncode != 0:
            raise MediaInfrastructureError(
                "PROCESS_FAILED",
                "Synthetic encoder returned a nonzero exit code.",
                {
                    "stderr_tail": self.runner.sanitize_diagnostic(result.stderr_tail),
                    "command": list(result.sanitized_argv),
                },
            )
