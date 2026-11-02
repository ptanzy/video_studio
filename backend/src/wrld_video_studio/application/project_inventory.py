from __future__ import annotations

import copy
import os
import stat
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from wrld_video_studio.application.ports.media import MediaProber
from wrld_video_studio.application.ports.wu4 import ProjectResolverPort
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.wu4 import InventoryScanPolicy, PROJECT_INVENTORY_VERSION, WU4Error, utc_now


_AUDIO = {".wav", ".mp3", ".flac", ".m4a"}
_IMAGE = {".png", ".jpg", ".jpeg", ".webp"}
_VIDEO = {".mp4"}
_EXCLUDED_DIRS = {"output", ".wrld-staging", ".wrld-cache", ".git"}
_EXCLUDED_FILES = {"thumbs.db", "desktop.ini", ".ds_store"}
_WAV_CODECS = {"pcm_u8", "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le"}
_IMAGE_MAX_BYTES = 256 * 1024 * 1024
_IMAGE_MAX_SIDE = 32_768
_IMAGE_MAX_PIXELS = 50_000_000


def _filesystem_key(value: str) -> str:
    return os.path.normcase(value)


def _support(status: str, reason: str) -> dict[str, str]:
    return {"status": status, "reason": reason}


def _base_capabilities() -> dict[str, dict[str, str]]:
    return {name: _support("unsupported", "not_supported") for name in ("server_stream", "browser_audition", "thumbnail", "inspection", "preview", "render")}


class ProjectInventoryService:
    def __init__(self, catalogs: Any, resolver: ProjectResolverPort, store: Any, prober: MediaProber, policy: InventoryScanPolicy) -> None:
        self.catalogs, self.resolver, self.store, self.prober, self.policy = catalogs, resolver, store, prober, policy

    def read(self, project_id: str) -> dict[str, Any]:
        self.catalogs.resolve(project_id)
        return self.store.read(project_id)

    def scan(self, project_id: str, scan_id: str, cancel: threading.Event, progress: Callable[[int, int], None]) -> dict[str, Any]:
        _entry, root = self.catalogs.resolve(project_id)
        previous = self.store.read(project_id)
        previous_by_path: dict[str, dict[str, Any]] = {}
        previous_ids: set[str] = set()
        for item in previous["assets"]:
            key = _filesystem_key(item["relative_path"])
            if key in previous_by_path or item["asset_id"] in previous_ids:
                raise WU4Error(
                    "ASSET_ID_COLLISION",
                    "The existing inventory contains colliding asset identities and requires review.",
                )
            previous_by_path[key] = item
            previous_ids.add(item["asset_id"])
        seen: set[str] = set()
        assets: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        started = time.monotonic()
        visited = 0

        def check() -> None:
            if cancel.is_set():
                raise WU4Error("SCAN_CANCELLED", "The inventory scan was cancelled.")
            if time.monotonic() - started > self.policy.max_seconds:
                raise WU4Error("SCAN_WALL_TIME_EXCEEDED", "The inventory scan exceeded its configured time limit.")

        stack: list[tuple[Path, int]] = [(root, 0)]
        while stack:
            directory, depth = stack.pop()
            check()
            if depth > self.policy.max_depth:
                raise WU4Error("SCAN_DEPTH_LIMIT_EXCEEDED", "The inventory scan exceeded its configured directory depth.")
            try:
                entries = sorted(os.scandir(directory), key=lambda item: item.name.casefold(), reverse=True)
            except OSError:
                diagnostics.append(self._diagnostic("DIRECTORY_UNREADABLE", "A directory could not be read.", directory.relative_to(root).as_posix() or None))
                continue
            for entry in entries:
                check()
                visited += 1
                if visited > self.policy.max_entries:
                    raise WU4Error("SCAN_ENTRY_LIMIT_EXCEEDED", "The inventory scan exceeded its configured entry limit.")
                progress(visited, len(assets))
                relative = Path(entry.path).relative_to(root).as_posix()
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError:
                    diagnostics.append(self._diagnostic("RESOURCE_UNREADABLE", "A project entry could not be inspected.", relative))
                    continue
                attributes = getattr(metadata, "st_file_attributes", 0)
                linked = stat.S_ISLNK(metadata.st_mode) or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
                if linked:
                    diagnostics.append(self._diagnostic("REPARSE_POINT_SKIPPED", "Links and reparse points are not scanned.", relative))
                    continue
                if stat.S_ISDIR(metadata.st_mode):
                    if _filesystem_key(entry.name) in {_filesystem_key(item) for item in _EXCLUDED_DIRS}:
                        continue
                    if depth + 1 > self.policy.max_depth:
                        raise WU4Error("SCAN_DEPTH_LIMIT_EXCEEDED", "The inventory scan exceeded its configured directory depth.")
                    stack.append((Path(entry.path), depth + 1))
                    continue
                if not stat.S_ISREG(metadata.st_mode) or _filesystem_key(entry.name) in {_filesystem_key(item) for item in _EXCLUDED_FILES}:
                    continue
                suffix = Path(entry.name).suffix.casefold()
                if suffix not in _AUDIO | _IMAGE | _VIDEO:
                    continue
                key = _filesystem_key(relative)
                seen.add(key)
                prior = previous_by_path.get(key)
                unchanged = prior is not None and prior["presence"] == "present" and prior["byte_length"] == metadata.st_size and prior["modified_ns"] == metadata.st_mtime_ns and prior.get("sha256")
                sha = prior["sha256"] if unchanged else self._hash(root, relative, cancel)
                state = "carried_forward" if unchanged else "verified"
                asset = self._asset(relative, suffix, metadata.st_size, metadata.st_mtime_ns, sha, state, prior)
                actual_path = Path(entry.path)
                if suffix in _IMAGE and metadata.st_size > _IMAGE_MAX_BYTES:
                    asset["probe_status"] = "failed"
                    asset["diagnostics"].append(self._diagnostic("IMAGE_DECODE_LIMIT_EXCEEDED", "The image exceeds the approved encoded-size limit.", relative))
                else:
                    self._probe(asset, actual_path, suffix)
                assets.append(asset)

        for key, prior in previous_by_path.items():
            if key not in seen:
                missing = copy.deepcopy(prior)
                missing["presence"] = "missing"
                missing["capabilities"] = _base_capabilities()
                missing["diagnostics"] = [self._diagnostic("ASSET_MISSING", "The previously inventoried asset is missing.", missing["relative_path"])]
                assets.append(missing)
        by_digest: dict[str, list[dict[str, Any]]] = {}
        for asset in assets:
            if asset["presence"] == "present" and asset.get("sha256"):
                by_digest.setdefault(asset["sha256"], []).append(asset)
        for matches in by_digest.values():
            if len(matches) > 1:
                for asset in matches:
                    asset["diagnostics"].append(self._diagnostic("DUPLICATE_CONTENT", "Another inventoried asset has identical verified content; identities remain separate.", asset["relative_path"]))
        asset_ids = [item["asset_id"] for item in assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise WU4Error(
                "ASSET_ID_COLLISION",
                "The candidate inventory contains colliding asset identities and was not published.",
            )
        assets.sort(key=lambda item: item["relative_path"].casefold())
        counts = {"audio": 0, "image": 0, "video": 0, "unknown": 0, "missing": 0}
        for asset in assets:
            counts[asset["kind"]] += 1
            if asset["presence"] == "missing": counts["missing"] += 1
        candidate = {
            "contract_version": PROJECT_INVENTORY_VERSION, "project_id": project_id,
            "inventory_revision": previous["inventory_revision"], "scan_id": scan_id,
            "completed_at": utc_now(), "policy_version": "inventory-policy/1.0",
            "assets": assets, "diagnostics": diagnostics, "counts": counts,
        }
        published = self.store.publish(project_id, previous["inventory_revision"], candidate)
        self.catalogs.set_inventory_revision(project_id, published["inventory_revision"])
        progress(visited, len(assets))
        return published

    def verify_asset(self, project_id: str, asset_id: str) -> tuple[dict[str, Any], Path, str]:
        inventory = self.read(project_id)
        asset = next((item for item in inventory["assets"] if item["asset_id"] == asset_id), None)
        if asset is None or asset["presence"] != "present":
            raise WU4Error("ASSET_NOT_FOUND", "The requested project asset is unavailable.")
        _entry, root = self.catalogs.resolve(project_id)
        path = self.resolver.resolve_project_file(root, asset["relative_path"])
        digest = self._hash(root, asset["relative_path"])
        if asset.get("sha256") != digest:
            raise WU4Error("SOURCE_CHANGED", "The project asset changed after inventory publication.")
        return asset, path, digest

    def open_asset(self, project_id: str, asset_id: str):
        asset, _path, digest = self.verify_asset(project_id, asset_id)
        _entry, root = self.catalogs.resolve(project_id)
        return self.resolver.open_project_file(root, asset["relative_path"]), asset, digest

    def relink(self, project_id: str, asset_id: str, relative_path: str) -> dict[str, Any]:
        previous = self.read(project_id)
        original = next((item for item in previous["assets"] if item["asset_id"] == asset_id), None)
        if original is None or original["presence"] != "missing":
            raise WU4Error("ASSET_RELINK_INVALID", "Only a missing inventoried asset can be relinked explicitly.")
        _entry, root = self.catalogs.resolve(project_id)
        path = self.resolver.resolve_project_file(root, relative_path)
        metadata = path.stat()
        suffix = path.suffix.casefold()
        if suffix not in _AUDIO | _IMAGE | _VIDEO:
            raise WU4Error("ASSET_RELINK_INVALID", "The replacement is not an approved media type.")
        replacement_kind = "audio" if suffix in _AUDIO else "image" if suffix in _IMAGE else "video"
        if replacement_kind != original["kind"]:
            raise WU4Error("ASSET_RELINK_INVALID", "The replacement media kind does not match the missing asset.")
        if any(item["presence"] == "present" and _filesystem_key(item["relative_path"]) == _filesystem_key(relative_path) for item in previous["assets"]):
            raise WU4Error("ASSET_RELINK_INVALID", "The replacement is already represented by a present asset.")
        digest = self._hash(root, relative_path)
        if original.get("sha256") and digest != original["sha256"]:
            raise WU4Error("ASSET_RELINK_INVALID", "The replacement content does not match the missing asset. Scan it as a new asset instead.")
        replacement = self._asset(relative_path, suffix, metadata.st_size, metadata.st_mtime_ns, digest, "verified", original)
        self._probe(replacement, path, suffix)
        assets = [replacement if item["asset_id"] == asset_id else copy.deepcopy(item) for item in previous["assets"]]
        candidate = {**previous, "scan_id": previous.get("scan_id"), "completed_at": utc_now(), "assets": assets}
        candidate.pop("inventory_revision", None)
        published = self.store.publish(project_id, previous["inventory_revision"], candidate)
        self.catalogs.set_inventory_revision(project_id, published["inventory_revision"])
        return replacement

    def _hash(self, root: Path, relative: str, cancel: threading.Event | None = None) -> str:
        path = self.resolver.resolve_project_file(root, relative)
        try:
            before = path.stat()
        except OSError as error:
            raise WU4Error("RESOURCE_NOT_FOUND", "The project asset could not be inspected safely.") from error
        with self.resolver.open_project_file(root, relative) as resource:
            import hashlib
            hasher = hashlib.sha256()
            while True:
                if cancel is not None and cancel.is_set():
                    raise WU4Error("SCAN_CANCELLED", "The inventory scan was cancelled.")
                chunk = resource.read(1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
            digest = hasher.hexdigest()
            handle_size = resource.size
        try:
            after = path.stat()
        except OSError as error:
            raise WU4Error("ASSET_CHANGED_DURING_VERIFICATION", "The project asset changed during verification.") from error
        before_observation = (before.st_size, before.st_mtime_ns, getattr(before, "st_ino", None))
        after_observation = (after.st_size, after.st_mtime_ns, getattr(after, "st_ino", None))
        if before_observation != after_observation or handle_size != before.st_size:
            raise WU4Error("ASSET_CHANGED_DURING_VERIFICATION", "The project asset changed during verification.")
        return digest

    @staticmethod
    def _diagnostic(code: str, message: str, relative: str | None) -> dict[str, Any]:
        return {"code": code, "message": message, "relative_path": relative}

    @staticmethod
    def _asset(relative: str, suffix: str, size: int, modified_ns: int, sha: str, state: str, prior: dict[str, Any] | None) -> dict[str, Any]:
        kind = "audio" if suffix in _AUDIO else "image" if suffix in _IMAGE else "video" if suffix in _VIDEO else "unknown"
        return {
            "asset_id": prior["asset_id"] if prior else f"asset-{uuid.uuid4()}", "relative_path": relative,
            "kind": kind, "presence": "present", "byte_length": size, "modified_ns": modified_ns,
            "sha256": sha, "verification_state": state, "media": {}, "probe_status": "not_probed",
            "capabilities": _base_capabilities(), "diagnostics": [],
        }

    def _probe(self, asset: dict[str, Any], path: Path, suffix: str) -> None:
        try:
            probe = self.prober.probe(path)
        except MediaInfrastructureError as error:
            asset["probe_status"] = "failed"
            code = "MEDIA_PROBE_TIMEOUT" if error.code == "PROBE_TIMEOUT" else "MEDIA_MALFORMED"
            asset["diagnostics"].append(self._diagnostic(code, "The media file could not be inspected safely.", asset["relative_path"]))
            return
        asset["probe_status"] = "ok"
        audio = [item for item in probe.streams if item.codec_type == "audio"]
        visual = [item for item in probe.streams if item.codec_type == "video"]
        asset["media"] = {
            "format_name": probe.format_name, "duration_seconds": probe.duration_seconds,
            "audio_codec": audio[0].codec_name if audio else None, "sample_rate": audio[0].sample_rate if audio else None,
            "channels": audio[0].channels if audio else None, "video_codec": visual[0].codec_name if visual else None,
            "width": visual[0].width if visual else None, "height": visual[0].height if visual else None,
            "frame_rate": visual[0].frame_rate if visual else None,
        }
        caps = _base_capabilities()
        if suffix in _AUDIO:
            codec = audio[0].codec_name if len(audio) == 1 else None
            ordinary_video = [item for item in visual if not item.attached_picture]
            allowed = (suffix == ".wav" and codec in _WAV_CODECS) or (suffix == ".mp3" and codec == "mp3") or (suffix == ".flac" and codec == "flac") or (suffix == ".m4a" and codec == "aac" and not ordinary_video)
            if allowed and probe.duration_seconds:
                caps["server_stream"] = _support("supported", "approved_audio")
                caps["browser_audition"] = _support("indeterminate", "browser_runtime_check")
                caps["render"] = _support("indeterminate" if suffix == ".wav" else "unsupported", "requires_approved_manifest" if suffix == ".wav" else "unsupported_source_format")
            else:
                asset["diagnostics"].append(self._diagnostic("MEDIA_UNSUPPORTED", "The audio container or codec is not in the approved allowlist.", asset["relative_path"]))
        elif suffix in _IMAGE:
            stream = visual[0] if visual else None
            expected_codec = {".png": "png", ".jpg": "mjpeg", ".jpeg": "mjpeg", ".webp": "webp"}[suffix]
            single_frame = len(visual) == 1 and stream is not None and stream.frame_count == 1
            safe = stream is not None and stream.codec_name == expected_codec and single_frame and stream.width and stream.height and stream.width <= _IMAGE_MAX_SIDE and stream.height <= _IMAGE_MAX_SIDE and stream.width * stream.height <= _IMAGE_MAX_PIXELS
            if safe:
                caps["thumbnail"] = _support("supported", "approved_image")
                caps["inspection"] = _support("supported", "approved_image")
                caps["render"] = _support("indeterminate" if suffix in {".png", ".jpg", ".jpeg"} else "unsupported", "requires_approved_manifest" if suffix != ".webp" else "unsupported_source_format")
            else:
                asset["diagnostics"].append(self._diagnostic("IMAGE_DECODE_LIMIT_EXCEEDED", "The image dimensions exceed approved limits or are unavailable.", asset["relative_path"]))
        elif suffix == ".mp4":
            if not visual:
                asset["diagnostics"].append(self._diagnostic("MEDIA_UNSUPPORTED", "The MP4 has no video stream.", asset["relative_path"]))
        asset["capabilities"] = caps


__all__ = ["ProjectInventoryService"]
