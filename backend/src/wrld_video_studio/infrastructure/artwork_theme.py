from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any

from wrld_video_studio.application.ports.media import ProcessRunner
from wrld_video_studio.domain.artwork_theme import ArtworkThemeContrastError, resolve_artwork_theme
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.player_overlay import ResolvedTheme, ThemeSettings
from wrld_video_studio.infrastructure.media_tools import MediaToolchain


class FFmpegArtworkThemeResolver:
    def __init__(self, toolchain: MediaToolchain, runner: ProcessRunner) -> None:
        self.toolchain = toolchain
        self.runner = runner

    def resolve(
        self,
        artwork: Path,
        settings: ThemeSettings,
        *,
        footer_opacity: float,
        cancel_event: Any = None,
    ) -> ResolvedTheme:
        ffmpeg = self.toolchain.resolve("ffmpeg")
        try:
            digest = self._sha256(artwork)
            with tempfile.TemporaryDirectory(prefix="wrld-player-palette-") as directory:
                output = Path(directory) / "palette.ppm"
                result = self.runner.run(
                    [
                        str(ffmpeg.path), "-hide_banner", "-nostdin", "-v", "error", "-xerror",
                        "-i", str(artwork), "-frames:v", "1",
                        "-vf", "scale=32:32:force_original_aspect_ratio=decrease:flags=area,pad=32:32:(ow-iw)/2:(oh-ih)/2:black,format=rgb24",
                        "-f", "image2", "-vcodec", "ppm", "-y", str(output),
                    ],
                    timeout_seconds=30.0,
                    cancel_event=cancel_event,
                )
                if result.cancelled:
                    raise MediaInfrastructureError("PROCESS_CANCELLED", "Artwork theme analysis was cancelled.")
                if result.timed_out or result.returncode != 0:
                    raise MediaInfrastructureError(
                        "THEME_ANALYSIS_FAILED",
                        "Artwork palette extraction failed.",
                        {"stderr_tail": self.runner.sanitize_diagnostic(result.stderr_tail)},
                    )
                pixels = self._ppm_pixels(output.read_bytes())
                return resolve_artwork_theme(pixels, digest, settings, footer_opacity=footer_opacity)
        except MediaInfrastructureError:
            raise
        except ArtworkThemeContrastError as error:
            raise MediaInfrastructureError(
                "THEME_CONTRAST_INVALID",
                "A manually configured player text color does not meet the required contrast.",
            ) from error
        except OSError as error:
            raise MediaInfrastructureError("THEME_ANALYSIS_FAILED", "Artwork palette analysis could not access its files.") from error

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _ppm_pixels(data: bytes) -> tuple[tuple[int, int, int], ...]:
        index = 0
        tokens: list[bytes] = []
        while len(tokens) < 4:
            while index < len(data) and data[index:index + 1].isspace():
                index += 1
            if index < len(data) and data[index:index + 1] == b"#":
                index = data.find(b"\n", index)
                if index < 0:
                    raise ValueError("invalid PPM")
                continue
            end = index
            while end < len(data) and not data[end:end + 1].isspace():
                end += 1
            tokens.append(data[index:end])
            index = end
        if tokens != [b"P6", b"32", b"32", b"255"]:
            raise ValueError("unexpected palette image")
        if index >= len(data) or not data[index:index + 1].isspace():
            raise ValueError("invalid PPM header terminator")
        index += 1
        payload = data[index:]
        if len(payload) != 32 * 32 * 3:
            raise ValueError("palette image is truncated")
        return tuple(tuple(payload[offset:offset + 3]) for offset in range(0, len(payload), 3))  # type: ignore[return-value]
