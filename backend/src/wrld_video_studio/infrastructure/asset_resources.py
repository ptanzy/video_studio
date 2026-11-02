from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from wrld_video_studio.domain.wu4 import WU4Error


_AUDIO_MIME = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac", ".m4a": "audio/mp4"}
_IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
_THUMBNAILS = {"small": 256, "large": 1024}


class AssetResourceService:
    def __init__(self, inventories: Any, toolchain: Any, runner: Any, cache_root: Path, *, max_cache_bytes: int = 512 * 1024 * 1024, max_entries: int = 5_000) -> None:
        self.inventories, self.toolchain, self.runner = inventories, toolchain, runner
        self.cache_root, self.max_cache_bytes, self.max_entries = cache_root, max_cache_bytes, max_entries
        self._lock = threading.RLock()

    def open_audio(self, project_id: str, asset_id: str):
        resource, asset, digest = self.inventories.open_asset(project_id, asset_id)
        suffix = Path(asset["relative_path"]).suffix.casefold()
        if asset["kind"] != "audio" or asset["capabilities"]["server_stream"]["status"] != "supported" or suffix not in _AUDIO_MIME:
            resource.close(); raise WU4Error("ASSET_CAPABILITY_UNAVAILABLE", "The asset is not approved for audio streaming.")
        return resource, {"size": resource.size, "etag": f'"sha256-{digest}"', "content_type": _AUDIO_MIME[suffix]}

    def open_image(self, project_id: str, asset_id: str):
        resource, asset, digest = self.inventories.open_asset(project_id, asset_id)
        suffix = Path(asset["relative_path"]).suffix.casefold()
        if asset["kind"] != "image" or asset["capabilities"]["inspection"]["status"] != "supported" or suffix not in _IMAGE_MIME:
            resource.close(); raise WU4Error("ASSET_CAPABILITY_UNAVAILABLE", "The asset is not approved for image inspection.")
        return resource, {"size": resource.size, "etag": f'"sha256-{digest}"', "content_type": _IMAGE_MIME[suffix]}

    def thumbnail(self, project_id: str, asset_id: str, variant: str) -> tuple[bytes, str]:
        if variant not in _THUMBNAILS:
            raise WU4Error("THUMBNAIL_VARIANT_INVALID", "The thumbnail variant is unsupported.")
        asset, source, digest = self.inventories.verify_asset(project_id, asset_id)
        if asset["kind"] != "image" or asset["capabilities"]["thumbnail"]["status"] != "supported":
            raise WU4Error("ASSET_CAPABILITY_UNAVAILABLE", "The asset cannot produce a thumbnail.")
        tool = self.toolchain.resolve("ffmpeg")
        key = hashlib.sha256(f"{digest}\0{variant}\0{tool.version}\0thumbnail-v1".encode()).hexdigest()
        target = self.cache_root / key[:2] / f"{key}.png"
        with self._lock:
            if target.is_file():
                data = target.read_bytes()
                if self._valid_png(data):
                    os.utime(target, None)
                    return data, f'"sha256-{hashlib.sha256(data).hexdigest()}"'
                target.unlink(missing_ok=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_text = tempfile.mkstemp(prefix=f".{key}.", suffix=".png", dir=target.parent)
            os.close(descriptor); os.unlink(temporary_text)
            temporary = Path(temporary_text)
            size = _THUMBNAILS[variant]
            try:
                result = self.runner.run([
                    str(tool.path), "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(source),
                    "-frames:v", "1", "-vf", f"scale=w='min(iw,{size})':h='min(ih,{size})':force_original_aspect_ratio=decrease",
                    "-map_metadata", "-1", "-f", "image2", "-c:v", "png", str(temporary),
                ], timeout_seconds=30.0)
                if result.returncode != 0 or result.timed_out or not temporary.is_file():
                    raise WU4Error("THUMBNAIL_INVALID", "The image thumbnail could not be generated.")
                data = temporary.read_bytes()
                if len(data) > 16 * 1024 * 1024 or not self._valid_png(data):
                    raise WU4Error("THUMBNAIL_INVALID", "The generated thumbnail is invalid or too large.")
                os.replace(temporary, target)
                self._evict()
                return data, f'"sha256-{hashlib.sha256(data).hexdigest()}"'
            finally:
                temporary.unlink(missing_ok=True)

    def _evict(self) -> None:
        files = sorted((path for path in self.cache_root.rglob("*.png") if path.is_file()), key=lambda path: path.stat().st_mtime_ns)
        total = sum(path.stat().st_size for path in files)
        while files and (len(files) > self.max_entries or total > self.max_cache_bytes):
            path = files.pop(0); size = path.stat().st_size; path.unlink(missing_ok=True); total -= size

    @staticmethod
    def _valid_png(data: bytes) -> bool:
        return len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n")


__all__ = ["AssetResourceService"]
