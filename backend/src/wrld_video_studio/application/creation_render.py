from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Mapping

from wrld_video_studio.domain.canonical_json import canonical_sha256
from wrld_video_studio.domain.creation_render import (
    RENDERER_CONTRACT_VERSION,
    RENDERER_ID,
    RENDERER_VERSION,
    CreationRenderExcerpt,
    CreationRenderExecutionPlan,
    CreationRenderManifest,
    CreationRenderRequest,
    effects_from_visual_configuration,
)
from wrld_video_studio.domain.jobs import utc_timestamp
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.video_export import ExportTarget, VideoTrack
from wrld_video_studio.domain.wu4 import WU4Error


SAMPLE_RATE = 48_000
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
STABLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PROFILES: dict[str, dict[str, Any]] = {
    "album": {"profile_id": "wrld-album-1080p30-v1", "width": 1920, "height": 1080},
    "single": {"profile_id": "wrld-single-1080p30-v1", "width": 1920, "height": 1080},
    "short": {"profile_id": "wrld-short-1080x1920p30-v1", "width": 1080, "height": 1920},
}
PROFILE_CONSTANTS = {
    "frame_rate": 30, "pixel_format": "yuv420p", "video_codec": "h264",
    "video_profile": "High", "video_encoder": "libx264", "video_preset": "medium",
    "video_crf": 18, "color_space": "bt709", "color_transfer": "bt709",
    "color_primaries": "bt709", "audio_codec": "aac", "audio_profile": "LC",
    "audio_bitrate": 192000, "audio_sample_rate": SAMPLE_RATE, "audio_channels": 2,
    "channel_layout": "stereo", "container": "mp4", "faststart": True,
    "duration_tolerance_seconds": 0.25, "full_decode_verification": True,
}
RECOVERY_CONTRACT_VERSION = "wrld-creation-render-recovery-request/1.0"
RECOVERY_PREFLIGHT_VERSION = "wrld-creation-render-recovery-preflight/1.0"
RECOVERY_RECORD_RESERVE_BYTES = 1024 * 1024


class CreationRenderService:
    def __init__(self, runtime: Any, state_root: Path, toolchain: Any, prober: Any, renderer: Any, verifier: Any) -> None:
        self.runtime = runtime
        self.root = state_root / "creation-render"
        self.root.mkdir(parents=True, exist_ok=True)
        self.toolchain = toolchain
        self.prober, self.renderer, self.verifier = prober, renderer, verifier
        self._guard = threading.Condition()
        self._queue: deque[str] = deque()
        self._cancel: dict[str, threading.Event] = {}
        self._closed = False
        self._recover()
        self._thread = threading.Thread(target=self._work, name="wrld-creation-render-worker", daemon=True)
        self._thread.start()

    def close(self) -> None:
        with self._guard:
            self._closed = True
            for event in self._cancel.values():
                event.set()
            self._guard.notify_all()
        self._thread.join(timeout=30)

    def targets(self, project_id: str) -> dict[str, Any]:
        state = self._state(project_id)
        artifacts = self._artifact_index(project_id)
        result = []
        for kind, collection, key in (("album", state["albums"], "album_plan_id"), ("single", state["singles"], "single_id"), ("short", state["shorts"], "short_id")):
            for item in collection:
                identity = str(item[key])
                target = {"kind": kind, "composition_id": identity}
                latest = next((value for value in reversed(artifacts) if value["target"] == target), None)
                result.append({
                    "target": target,
                    "label": str(item.get("label") or identity),
                    "status": item["status"],
                    "profile_id": PROFILES[kind]["profile_id"],
                    "preflight_required": True,
                    "latest_artifact": latest,
                })
        return {"contract_version": "wrld-creation-render-targets/1.0", "project_id": project_id, "creation_basis": {"contract_version": "wrld-creation-state/4.0", "revision": state["revision"], "state_digest": state["state_digest"]}, "targets": result}

    def preflight(self, project_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        self._validate_request(request, "preflight")
        request_fingerprint = self._request_fingerprint(request)
        try:
            plan = self._plan(project_id, request, strict_basis=True)
        except WU4Error as error:
            if error.code in {"PROJECT_NOT_FOUND", "PROJECT_REMOVED", "PROJECT_UNAVAILABLE", "PROJECT_RELINK_REQUIRED", "PROJECT_PATH_INVALID"}:
                raise
            return {"contract_version": "wrld-creation-render-preflight/1.0", "status": "blocked", "request_fingerprint": request_fingerprint, "plan": None, "diagnostics": [self._diagnostic(error.code, error.message, request.get("target"), error.details)], "existing_artifact": None, "report_revision": self._artifact_revision(project_id)}
        capacity = self._render_capacity(project_id, plan)
        if not capacity["sufficient"]:
            return {"contract_version": "wrld-creation-render-preflight/1.0", "status": "blocked", "request_fingerprint": request_fingerprint, "plan": plan, "diagnostics": [self._diagnostic("RENDER_FAILED", "Available staging capacity is below the conservative render estimate.", request["target"], capacity)], "existing_artifact": None, "report_revision": self._artifact_revision(project_id)}
        existing = self._artifact_for_path(project_id, plan["output"]["relative_path"])
        _entry, project_root = self.runtime.catalogs.resolve(project_id)
        output_path = self._contained(project_root, plan["output"]["relative_path"])
        if output_path.is_file() and existing is None:
            return {"contract_version": "wrld-creation-render-preflight/1.0", "status": "blocked", "request_fingerprint": request_fingerprint, "plan": None, "diagnostics": [self._diagnostic("OUTPUT_EXISTS", "An unregistered output already occupies the target path and cannot be replaced automatically.", request["target"], {"relative_path": plan["output"]["relative_path"]})], "existing_artifact": None, "report_revision": self._artifact_revision(project_id)}
        if existing is not None and existing["plan_fingerprint"] != plan["plan_fingerprint"]:
            if not self._artifact_file_is_current(project_id, existing):
                return {"contract_version": "wrld-creation-render-preflight/1.0", "status": "blocked", "request_fingerprint": request_fingerprint, "plan": None, "diagnostics": [self._diagnostic("OUTPUT_INVALID", "The registered output is missing or changed on disk.", request["target"], {"artifact_id": existing["artifact_id"]})], "existing_artifact": existing, "report_revision": self._artifact_revision(project_id)}
            try:
                self._validate_replacement(project_id, request, existing)
            except WU4Error as error:
                if request["output_action"] == "replace_verified":
                    return {"contract_version": "wrld-creation-render-preflight/1.0", "status": "blocked", "request_fingerprint": request_fingerprint, "plan": None, "diagnostics": [self._diagnostic(error.code, error.message, request["target"], error.details)], "existing_artifact": existing, "report_revision": self._artifact_revision(project_id)}
                status = "replacement_required"
            else:
                status = "ready"
            diagnostics = [self._diagnostic("OUTPUT_EXISTS", "A different verified artifact already occupies the target path.", request["target"], {"artifact_id": existing["artifact_id"]})]
        else:
            status, diagnostics = "ready", []
        return {"contract_version": "wrld-creation-render-preflight/1.0", "status": status, "request_fingerprint": request_fingerprint, "plan": plan, "diagnostics": diagnostics, "existing_artifact": existing, "report_revision": self._artifact_revision(project_id)}

    def recovery_preflight(self, project_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        self._validate_recovery_request(request, "preflight")
        try:
            plan, candidate = self._recovery_candidate(project_id, request)
        except WU4Error as error:
            code = "RECOVERY_JOB_NOT_FOUND" if error.code == "RESOURCE_NOT_FOUND" else error.code
            allowed = {"RECOVERY_JOB_NOT_FOUND", "RECOVERY_PROJECT_MISMATCH", "RECOVERY_ATTEMPT_MISMATCH", "RECOVERY_JOB_NOT_FAILED", "RECOVERY_PLAN_STALE", "RECOVERY_PROFILE_MISMATCH", "RECOVERY_RENDERER_MISMATCH", "RECOVERY_STAGING_MISSING", "RECOVERY_STAGING_INCOMPLETE", "RECOVERY_STAGING_CHANGED", "RECOVERY_PROVENANCE_MISMATCH", "RECOVERY_RECEIPT_STALE", "RECOVERY_PUBLICATION_VOLUME_MISMATCH", "RECOVERY_DISK_SPACE_INSUFFICIENT", "OUTPUT_EXISTS", "OUTPUT_REPLACEMENT_STALE", "RECOVERY_INDETERMINATE"}
            if code not in allowed: code = "RECOVERY_PLAN_STALE"
            return {"contract_version": RECOVERY_PREFLIGHT_VERSION, "status": "blocked", "recovery_fingerprint": None, "plan": None, "candidate": None, "diagnostics": [self._recovery_diagnostic(code, error.message, error.details)], "existing_artifact": None, "report_revision": self._artifact_revision(project_id)}
        existing = self._artifact_for_path(project_id, plan["output"]["relative_path"])
        _entry, project_root = self.runtime.catalogs.resolve(project_id)
        final = self._contained(project_root, plan["output"]["relative_path"])
        if final.is_file() and existing is None:
            return {"contract_version": RECOVERY_PREFLIGHT_VERSION, "status": "blocked", "recovery_fingerprint": None, "plan": plan, "candidate": candidate, "diagnostics": [self._recovery_diagnostic("OUTPUT_EXISTS", "An unregistered output occupies the recovery destination.", {})], "existing_artifact": None, "report_revision": self._artifact_revision(project_id)}
        if existing is not None and existing["plan_fingerprint"] == plan["plan_fingerprint"]:
            return {"contract_version": RECOVERY_PREFLIGHT_VERSION, "status": "blocked", "recovery_fingerprint": None, "plan": plan, "candidate": candidate, "diagnostics": [self._recovery_diagnostic("OUTPUT_EXISTS", "A matching verified artifact already exists; staged recovery is unnecessary.", {"artifact_id": existing["artifact_id"]})], "existing_artifact": existing, "report_revision": self._artifact_revision(project_id)}
        if existing is not None:
            status = "replacement_required"
            diagnostics = [self._recovery_diagnostic("OUTPUT_EXISTS", "A different verified artifact occupies the recovery destination.", {"artifact_id": existing["artifact_id"]})]
        else:
            status, diagnostics = "ready", []
        fingerprint = canonical_sha256(candidate)
        return {"contract_version": RECOVERY_PREFLIGHT_VERSION, "status": status, "recovery_fingerprint": fingerprint, "plan": plan, "candidate": candidate, "diagnostics": diagnostics, "existing_artifact": existing, "report_revision": self._artifact_revision(project_id)}

    def submit_recovery(self, project_id: str, request: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        self._validate_recovery_request(request, "submit")
        submission = str(request["submission_id"])
        for job in self.list_jobs(project_id):
            if job["submission_id"] == submission:
                record = self._load_record(job["job_id"])
                if record.get("recovery_fingerprint") != request["expected_recovery_fingerprint"]:
                    raise WU4Error("REVISION_CONFLICT", "The submission identity was already used for a different recovery request.")
                return job, False
        plan, candidate = self._recovery_candidate(project_id, request)
        fingerprint = canonical_sha256(candidate)
        if fingerprint != request["expected_recovery_fingerprint"]:
            raise WU4Error("RECOVERY_RECEIPT_STALE", "The staged recovery receipt is stale.", {"actual_recovery_fingerprint": fingerprint})
        existing = self._artifact_for_path(project_id, plan["output"]["relative_path"])
        if existing is not None:
            self._validate_replacement(project_id, request, existing)
        elif request["output_action"] == "replace_verified":
            raise WU4Error("OUTPUT_REPLACEMENT_STALE", "The replacement authorization is stale.")
        job_id, attempt_id, now = str(uuid.uuid4()), str(uuid.uuid4()), utc_timestamp()
        job = self._job_document(project_id, request, plan, job_id, attempt_id, now)
        job["retry_of_attempt_id"] = request["failed_attempt_id"]
        record = {"job": job, "request": copy.deepcopy(dict(request)), "plan": plan, "result": None, "recovery": candidate, "recovery_fingerprint": fingerprint, "publication": {"state": "none", "artifact": None}}
        self._save_record(job_id, record)
        with self._guard:
            self._queue.append(job_id); self._cancel[job_id] = threading.Event(); self._guard.notify_all()
        return self._with_queue_position(job), True

    def submit(self, project_id: str, request: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        self._validate_request(request, "submit")
        submission = str(request["submission_id"])
        for job in self.list_jobs(project_id):
            if job["submission_id"] == submission:
                if job["request_fingerprint"] != self._request_fingerprint(request):
                    raise WU4Error("REVISION_CONFLICT", "The submission identity was already used for a different render request.")
                return job, False
        plan = self._plan(project_id, request, strict_basis=False)
        if plan["plan_fingerprint"] != request["expected_plan_fingerprint"]:
            raise WU4Error("PLAN_STALE", "The render plan changed after preflight.", {"expected_plan_fingerprint": request["expected_plan_fingerprint"], "actual_plan_fingerprint": plan["plan_fingerprint"]})
        capacity = self._render_capacity(project_id, plan)
        if not capacity["sufficient"]: raise WU4Error("RENDER_FAILED", "Available staging capacity is below the conservative render estimate.", capacity)
        for job in self.list_jobs(project_id):
            if job["plan_fingerprint"] == plan["plan_fingerprint"] and job["state"] in {"queued", "running", "cancel_requested", "succeeded"}:
                return job, False
        existing = self._artifact_for_path(project_id, plan["output"]["relative_path"])
        _entry, project_root = self.runtime.catalogs.resolve(project_id)
        final = self._contained(project_root, plan["output"]["relative_path"])
        if final.is_file() and existing is None:
            raise WU4Error("OUTPUT_EXISTS", "An unregistered output already occupies the target path.")
        if existing is not None:
            if existing["plan_fingerprint"] == plan["plan_fingerprint"] and request["output_action"] == "reuse_verified_or_fail":
                self._fresh_verify_artifact(project_id, existing)
                job = self._reused_job(project_id, request, plan, existing)
                return job, False
            self._validate_replacement(project_id, request, existing)
        job_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
        now = utc_timestamp()
        job = self._job_document(project_id, request, plan, job_id, attempt_id, now)
        record = {"job": job, "request": copy.deepcopy(dict(request)), "plan": plan, "result": None, "publication": {"state": "none", "artifact": None}}
        self._save_record(job_id, record)
        with self._guard:
            self._queue.append(job_id)
            self._cancel[job_id] = threading.Event()
            self._guard.notify_all()
        return self._with_queue_position(job), True

    def list_jobs(self, project_id: str) -> list[dict[str, Any]]:
        jobs = [self._with_queue_position(record["job"]) for record in self._records() if record["job"]["project_id"] == project_id]
        return sorted(jobs, key=lambda item: (item["created_at"], item["job_id"]), reverse=True)

    def get_job(self, project_id: str, job_id: str) -> dict[str, Any]:
        record = self._load_record(job_id)
        if record["job"]["project_id"] != project_id:
            raise WU4Error("PROJECT_NOT_FOUND", "The render job is not part of this project.")
        return self._with_queue_position(record["job"])

    def result(self, project_id: str, job_id: str) -> dict[str, Any]:
        record = self._load_record(job_id)
        if record["job"]["project_id"] != project_id:
            raise WU4Error("PROJECT_NOT_FOUND", "The render job is not part of this project.")
        if record["result"] is None:
            raise WU4Error("RENDER_NOT_COMPLETE", "The render job does not have a terminal result.")
        return record["result"]

    def cancel(self, project_id: str, job_id: str) -> dict[str, Any]:
        record = self._load_record(job_id)
        job = record["job"]
        if job["project_id"] != project_id:
            raise WU4Error("PROJECT_NOT_FOUND", "The render job is not part of this project.")
        if job["state"] == "queued":
            with self._guard:
                try: self._queue.remove(job_id)
                except ValueError: pass
            job.update({"state": "cancelled", "phase": "completed", "finished_at": utc_timestamp(), "updated_at": utc_timestamp(), "result_available": True})
            record["result"] = self._terminal_result(record, "cancelled", [self._diagnostic("PROCESS_CANCELLED", "Rendering was cancelled before execution.", job["target"], {})])
            self._save_record(job_id, record)
            return job
        if job["state"] == "running":
            job.update({"state": "cancel_requested", "updated_at": utc_timestamp()})
            self._save_record(job_id, record)
            self._cancel.setdefault(job_id, threading.Event()).set()
            return job
        if job["state"] == "cancelled": return job
        raise WU4Error("RENDER_NOT_CANCELLABLE", "The render job is already terminal.")

    def artifact(self, project_id: str, artifact_id: str) -> dict[str, Any]:
        found = next((item for item in self._artifact_index(project_id) if item["artifact_id"] == artifact_id), None)
        if found is None: raise WU4Error("RESOURCE_NOT_FOUND", "The verified render artifact was not found.")
        return found

    def artifact_path(self, project_id: str, artifact_id: str) -> Path:
        artifact = self.artifact(project_id, artifact_id)
        _entry, root = self.runtime.catalogs.resolve(project_id)
        path = self._contained(root, artifact["relative_path"])
        if not path.is_file() or self._sha256(path) != artifact["sha256"]:
            raise WU4Error("OUTPUT_INVALID", "The verified render artifact is missing or changed on disk.")
        return path

    def history_storage(self, project_id: str) -> dict[str, int]:
        _entry, root = self.runtime.catalogs.resolve(project_id)
        history = root / "output" / ".wrld-history"
        files = [item for item in history.rglob("*.mp4") if item.is_file()] if history.is_dir() else []
        return {"file_count": len(files), "byte_size": sum(item.stat().st_size for item in files)}

    def _plan(self, project_id: str, request: Mapping[str, Any], *, strict_basis: bool) -> dict[str, Any]:
        _entry, root = self.runtime.catalogs.resolve(project_id)
        state = self._state(project_id)
        if strict_basis and (state["revision"] != request["expected_creation_revision"] or state["state_digest"] != request["expected_creation_state_digest"]):
            raise WU4Error("CREATION_STATE_STALE", "Creation changed before render preflight.")
        target = request["target"]
        kind, identity = str(target["kind"]), str(target["composition_id"])
        key = {"album": "album_plan_id", "single": "single_id", "short": "short_id"}[kind]
        item = next((value for value in state[kind + "s"] if value[key] == identity), None)
        if item is None: raise WU4Error("COMPOSITION_NOT_FOUND", "The requested Creation composition does not exist.")
        if item["status"] != "active": raise WU4Error("COMPOSITION_ARCHIVED", "Archived compositions cannot be rendered.")
        expected_profile = PROFILES[kind]["profile_id"]
        if request["profile_id"] != expected_profile: raise WU4Error("PROFILE_TARGET_MISMATCH", "The selected render profile does not match the composition type.")
        visual = copy.deepcopy(item["visual_configuration"])
        if visual["background_image"] is None: raise WU4Error("VISUAL_SOURCE_REQUIRED", "The composition requires a background image.")
        inventory = self.runtime.inventories.read(project_id)
        assets = {value["asset_id"]: value for value in inventory["assets"]}
        excluded = set(self.runtime.preferences.get(project_id)["excluded_asset_ids"])
        sources: list[dict[str, Any]] = []
        assignments = item["assignments"] if kind == "album" else [{"assignment_id": None, "asset_id": item["asset_id"], "expected_sha256": item["expected_sha256"]}]
        for sequence, assignment in enumerate(assignments, start=1):
            asset = self._asset(assets, excluded, assignment["asset_id"], assignment["expected_sha256"], "audio")
            duration = asset.get("media", {}).get("duration_seconds")
            if not isinstance(duration, (int, float)) or duration <= 0: raise WU4Error("RECORDING_UNSUPPORTED", "The recording duration is unavailable.", {"asset_id": asset["asset_id"]})
            available = round(float(duration) * SAMPLE_RATE)
            start = int(item["start_sample"]) if kind == "short" else 0
            count = int(item["sample_count"]) if kind == "short" else available
            if start < 0 or count <= 0 or start + count > available: raise WU4Error("EXCERPT_OUT_OF_RANGE", "The saved Short excerpt exceeds the recording.", {"asset_id": asset["asset_id"]})
            sources.append({"asset_id": asset["asset_id"], "expected_sha256": assignment["expected_sha256"], "observed_sha256": asset["sha256"], "relative_path": asset["relative_path"], "mime_type": self._mime(asset["relative_path"]), "sequence": sequence, "assignment_id": assignment.get("assignment_id"), "source_start_sample": start, "sample_count": count, "available_sample_count": available})
        background_ref = visual["background_image"]
        background = self._asset(assets, excluded, background_ref["asset_id"], background_ref["expected_sha256"], "image")
        entries, cursor = [], 0
        for source in sources:
            entries.append({"sequence": source["sequence"], "assignment_id": source["assignment_id"], "asset_id": source["asset_id"], "asset_sha256": source["observed_sha256"], "source_start_sample": source["source_start_sample"], "output_start_sample": cursor, "sample_count": source["sample_count"], "output_end_sample": cursor + source["sample_count"]})
            cursor += source["sample_count"]
        public_sources = [{key: value for key, value in source.items() if key != "available_sample_count"} for source in sources]
        timeline_body = {"sample_rate": SAMPLE_RATE, "total_samples": cursor, "entries": entries}
        timeline = {"contract_version": "wrld-creation-render-timeline/1.0", "timeline_id": "timeline-" + canonical_sha256(timeline_body), **timeline_body, "duration_seconds": cursor / SAMPLE_RATE}
        profile = {**PROFILES[kind], **PROFILE_CONSTANTS}
        background_source = {"asset_id": background["asset_id"], "expected_sha256": background_ref["expected_sha256"], "observed_sha256": background["sha256"], "relative_path": background["relative_path"], "mime_type": self._mime(background["relative_path"])}
        composition_fingerprint = canonical_sha256(self._composition(kind, item))
        source_set_fingerprint = canonical_sha256([{"kind": "audio", "asset_id": value["asset_id"], "observed_sha256": value["observed_sha256"]} for value in public_sources] + [{"kind": "background_image", "asset_id": background["asset_id"], "observed_sha256": background["sha256"]}])
        output_dir = {"album": "album", "single": "tracks", "short": "shorts"}[kind]
        artifact_kind = {"album": "album_video", "single": "single_video", "short": "short_video"}[kind]
        try: ffmpeg = self.toolchain.resolve("ffmpeg")
        except MediaInfrastructureError as error: raise WU4Error("FFMPEG_UNAVAILABLE", "FFmpeg is unavailable for Creation rendering.", error.details) from error
        try: ffprobe = self.toolchain.resolve("ffprobe")
        except MediaInfrastructureError as error: raise WU4Error("FFPROBE_UNAVAILABLE", "FFprobe is unavailable for Creation rendering.", error.details) from error
        plan: dict[str, Any] = {"contract_version": "wrld-creation-render-plan/1.0", "plan_id": "", "plan_fingerprint": "", "request_fingerprint": self._request_fingerprint(request), "project_id": project_id, "target": copy.deepcopy(target), "creation_basis": {"contract_version": "wrld-creation-state/4.0", "revision": state["revision"], "state_digest": state["state_digest"], "composition_fingerprint": composition_fingerprint}, "profile": profile, "visual_configuration": visual, "visual_configuration_fingerprint": canonical_sha256(visual), "audio_sources": public_sources, "background_source": background_source, "timeline": timeline, "output": {"artifact_kind": artifact_kind, "relative_path": f"output/{output_dir}/{identity}.mp4"}, "dependencies": [{"kind": "audio", "asset_id": value["asset_id"], "sha256": value["observed_sha256"]} for value in public_sources] + [{"kind": "background_image", "asset_id": background["asset_id"], "sha256": background["sha256"]}], "source_set_fingerprint": source_set_fingerprint, "renderer": {"renderer_id": RENDERER_ID, "contract_version": RENDERER_CONTRACT_VERSION, "renderer_version": RENDERER_VERSION, "ffmpeg_version": ffmpeg.version, "ffprobe_version": ffprobe.version}}
        fingerprint_value = copy.deepcopy(plan)
        for field in ("plan_id", "plan_fingerprint", "request_fingerprint"): fingerprint_value.pop(field)
        fingerprint_value["creation_basis"].pop("revision"); fingerprint_value["creation_basis"].pop("state_digest")
        plan["plan_fingerprint"] = canonical_sha256(fingerprint_value)
        plan["plan_id"] = "plan-" + plan["plan_fingerprint"]
        return plan

    def _execute(self, record: dict[str, Any], cancel: threading.Event) -> None:
        job, plan = record["job"], record["plan"]
        project_id, job_id = job["project_id"], job["job_id"]
        _entry, project_root = self.runtime.catalogs.resolve(project_id)
        stage = self.root / "staging" / job_id / job["attempt_id"]
        stage.mkdir(parents=True, exist_ok=True)
        fresh = self._load_record(job_id); fresh["job"].update({"phase": "snapshotting_sources", "updated_at": utc_timestamp(), "last_heartbeat_at": utc_timestamp()}); self._save_record(job_id, fresh)
        live_sources = tuple(self._contained(project_root, value["relative_path"]) for value in plan["audio_sources"])
        live_background = self._contained(project_root, plan["background_source"]["relative_path"])
        snapshot_root = stage / "sources"; snapshot_root.mkdir(parents=True, exist_ok=True)
        sources_list: list[Path] = []
        for index, (source, expected) in enumerate(zip(live_sources, plan["audio_sources"], strict=True)):
            if cancel.is_set(): raise RuntimeError("Rendering was cancelled during source snapshotting.")
            snapshot = snapshot_root / f"audio-{index}{source.suffix.casefold()}"
            shutil.copyfile(source, snapshot)
            if self._sha256(snapshot) != expected["observed_sha256"]: raise WU4Error("SOURCE_CHANGED_DURING_RENDER", "A recording changed while the render was being prepared.", {"asset_id": expected["asset_id"]})
            sources_list.append(snapshot)
        background = snapshot_root / f"background{live_background.suffix.casefold()}"
        shutil.copyfile(live_background, background)
        if self._sha256(background) != plan["background_source"]["observed_sha256"]: raise WU4Error("SOURCE_CHANGED_DURING_RENDER", "The background image changed while the render was being prepared.", {"asset_id": plan["background_source"]["asset_id"]})
        sources = tuple(sources_list)
        tracks = tuple(VideoTrack(value["asset_id"], value["sequence"], value["asset_id"], value["relative_path"]) for value in plan["audio_sources"])
        total_available = sum(round(float(self.prober.probe(path).duration_seconds or 0) * SAMPLE_RATE) for path in sources)
        if plan["target"]["kind"] == "short": excerpt = CreationRenderExcerpt(plan["audio_sources"][0]["source_start_sample"], plan["audio_sources"][0]["sample_count"])
        else: excerpt = CreationRenderExcerpt(0, total_available)
        visual = plan["visual_configuration"]
        request = CreationRenderRequest(ExportTarget("album"), effects_from_visual_configuration(plan["target"], visual), excerpt, visual, plan["profile"]["width"], plan["profile"]["height"])
        execution = CreationRenderExecutionPlan(CreationRenderManifest(plan["background_source"]["relative_path"]), request, tracks, plan["output"]["relative_path"].removeprefix("output/"), plan["output"]["artifact_kind"])
        output = stage / "output.mp4"
        progress_file = stage / "effects.sendcmd"
        execution_started = time.monotonic()
        def progress(value: Mapping[str, Any]) -> None:
            fresh = self._load_record(job_id); current = fresh["job"]
            current["phase"] = str(value.get("phase", current["phase"])); current["updated_at"] = utc_timestamp(); current["last_heartbeat_at"] = current["updated_at"]
            current["progress"]["phase_percent"] = value.get("phase_progress_percent")
            current["progress"]["processed_samples"] = None if value.get("processed_duration_seconds") is None else round(float(value["processed_duration_seconds"]) * SAMPLE_RATE)
            current["progress"]["current_source"] = value.get("current_track")
            current["progress"]["elapsed_seconds"] = max(0.0, time.monotonic() - execution_started)
            processed = current["progress"]["processed_samples"]
            total = current["progress"]["total_samples"]
            current["progress"]["eta_seconds"] = (current["progress"]["elapsed_seconds"] * (total - processed) / processed) if isinstance(processed, int) and 0 < processed < total else (0 if processed == total else None)
            self._save_record(job_id, fresh)
        def phase(value: str) -> None:
            fresh = self._load_record(job_id); current = fresh["job"]
            current.update({"phase": value, "updated_at": utc_timestamp(), "last_heartbeat_at": utc_timestamp()})
            self._save_record(job_id, fresh)
        def heartbeat() -> None:
            fresh = self._load_record(job_id); now = utc_timestamp()
            fresh["job"].update({"updated_at": now, "last_heartbeat_at": now})
            self._save_record(job_id, fresh)
        rendered = self.renderer.render(execution, sources, background, output, tuple(stage / f"source-{i}.pcm" for i in range(len(sources))), stage / "combined.pcm", plan["plan_fingerprint"], cancel_event=cancel, progress=progress, effect_control_path=progress_file, source_sample_counts=tuple(round(float(self.prober.probe(path).duration_seconds or 0) * SAMPLE_RATE) for path in sources))
        expected = {"video_codec": "h264", "audio_codec": "aac", "pixel_format": "yuv420p", "width": plan["profile"]["width"], "height": plan["profile"]["height"], "frame_rate": 30, "audio_sample_rate": SAMPLE_RATE, "audio_channels": 2, "video_profile": "High", "audio_profile": "LC", "color_space": "bt709", "color_transfer": "bt709", "color_primaries": "bt709", "duration_seconds": rendered.duration_seconds, "duration_tolerance_seconds": 0.25, "request_digest": plan["plan_fingerprint"], "faststart": True, "full_decode": True, "decode_timeout_seconds": max(600, rendered.duration_seconds * 4)}
        artifact = self._verify_and_publish(record, output, expected, cancel, phase, heartbeat)
        self._finish_success(job_id, artifact)

    def _execute_recovery(self, record: dict[str, Any], cancel: threading.Event) -> None:
        job, plan = record["job"], record["plan"]
        _plan, candidate = self._recovery_candidate(job["project_id"], record["request"])
        if canonical_sha256(candidate) != record["recovery_fingerprint"]:
            raise WU4Error("RECOVERY_RECEIPT_STALE", "The staged recovery receipt changed before verification.")
        output = self._recovery_stage_path(candidate["failed_job_id"], candidate["failed_attempt_id"])
        def phase(value: str) -> None:
            fresh = self._load_record(job["job_id"]); now = utc_timestamp()
            fresh["job"].update({"phase": value, "updated_at": now, "last_heartbeat_at": now}); self._save_record(job["job_id"], fresh)
        def heartbeat() -> None:
            fresh = self._load_record(job["job_id"]); now = utc_timestamp()
            fresh["job"].update({"updated_at": now, "last_heartbeat_at": now}); self._save_record(job["job_id"], fresh)
        expected = {"video_codec": "h264", "audio_codec": "aac", "pixel_format": "yuv420p", "width": plan["profile"]["width"], "height": plan["profile"]["height"], "frame_rate": 30, "audio_sample_rate": SAMPLE_RATE, "audio_channels": 2, "video_profile": "High", "audio_profile": "LC", "color_space": "bt709", "color_transfer": "bt709", "color_primaries": "bt709", "duration_seconds": plan["timeline"]["duration_seconds"], "duration_tolerance_seconds": 0.25, "request_digest": plan["plan_fingerprint"], "faststart": True, "full_decode": True, "decode_timeout_seconds": max(600, float(plan["timeline"]["duration_seconds"]) * 4)}
        artifact = self._verify_and_publish(record, output, expected, cancel, phase, heartbeat, expected_staged_sha256=candidate["staged_sha256"])
        self._finish_success(job["job_id"], artifact)

    def _verify_and_publish(self, record: Mapping[str, Any], output: Path, expected: Mapping[str, Any], cancel: threading.Event, phase: Any, heartbeat: Any, *, expected_staged_sha256: str | None = None) -> dict[str, Any]:
        job, plan = record["job"], record["plan"]
        probe = self.verifier.verify(output, expected, cancel_event=cancel, heartbeat=heartbeat, phase_callback=phase)
        digest = self._sha256(output)
        if expected_staged_sha256 is not None and digest != expected_staged_sha256:
            raise WU4Error("RECOVERY_STAGING_CHANGED", "The staged recovery file changed during verification.")
        now = utc_timestamp()
        artifact = {"contract_version": "wrld-creation-render-artifact/1.0", "artifact_id": "", "project_id": job["project_id"], "target": plan["target"], "kind": plan["output"]["artifact_kind"], "plan_fingerprint": plan["plan_fingerprint"], "profile_id": plan["profile"]["profile_id"], "renderer_id": RENDERER_ID, "renderer_version": RENDERER_VERSION, "relative_path": plan["output"]["relative_path"], "sha256": digest, "byte_size": output.stat().st_size, "media": {"container": "mp4", "video_codec": "h264", "video_profile": "High", "width": plan["profile"]["width"], "height": plan["profile"]["height"], "frame_rate": 30, "pixel_format": "yuv420p", "color_space": "bt709", "color_transfer": "bt709", "color_primaries": "bt709", "audio_codec": "aac", "audio_profile": "LC", "audio_sample_rate": SAMPLE_RATE, "audio_channels": 2, "channel_layout": "stereo", "duration_seconds": probe.duration_seconds}, "verification": {"status": "verified", "probe_passed": True, "full_decode_passed": True, "faststart_passed": True}, "created_at": now}
        artifact["artifact_id"] = "artifact-" + canonical_sha256({key: artifact[key] for key in ("project_id", "target", "plan_fingerprint", "relative_path", "sha256")})
        fresh = self._load_record(job["job_id"]); fresh["publication"] = {"state": "verified", "artifact": artifact}; self._save_record(job["job_id"], fresh)
        phase("publishing_artifact")
        _entry, project_root = self.runtime.catalogs.resolve(job["project_id"])
        final = self._contained(project_root, plan["output"]["relative_path"]); final.parent.mkdir(parents=True, exist_ok=True)
        existing = self._artifact_for_path(job["project_id"], plan["output"]["relative_path"])
        historical: Path | None = None
        if final.exists():
            self._validate_replacement(job["project_id"], record["request"], existing); assert existing is not None
            history = project_root / "output" / ".wrld-history" / existing["artifact_id"]; history.mkdir(parents=True, exist_ok=True)
            historical = history / f"{existing['sha256']}.mp4"; os.replace(final, historical)
        try:
            os.replace(output, final)
            self._publish_artifact(job["project_id"], artifact)
        except Exception:
            if final.is_file(): os.replace(final, output)
            if historical is not None and historical.is_file(): os.replace(historical, final)
            raise
        fresh = self._load_record(job["job_id"]); fresh["publication"] = {"state": "artifact_committed", "artifact": artifact}; self._save_record(job["job_id"], fresh)
        phase("publishing_report")
        return artifact

    def _finish_success(self, job_id: str, artifact: Mapping[str, Any]) -> None:
        fresh = self._load_record(job_id); now = utc_timestamp(); plan = fresh["plan"]
        fresh["job"].update({"state": "succeeded", "phase": "completed", "updated_at": now, "last_heartbeat_at": now, "finished_at": now, "result_available": True}); fresh["job"]["progress"].update({"phase_percent": 100.0, "processed_samples": plan["timeline"]["total_samples"], "eta_seconds": 0})
        fresh["result"] = self._terminal_result(fresh, "succeeded", [], [copy.deepcopy(dict(artifact))]); fresh["publication"] = {"state": "result_committed", "artifact": copy.deepcopy(dict(artifact))}; self._save_record(job_id, fresh)
        self._cleanup_success_staging(fresh)

    def _work(self) -> None:
        while True:
            with self._guard:
                while not self._queue and not self._closed: self._guard.wait()
                if self._closed: return
                job_id = self._queue.popleft(); cancel = self._cancel.setdefault(job_id, threading.Event())
            record = self._load_record(job_id); now = utc_timestamp(); record["job"].update({"state": "running", "phase": "preparing", "started_at": now, "updated_at": now, "last_heartbeat_at": now}); self._save_record(job_id, record)
            try:
                if record.get("recovery") is not None: self._execute_recovery(record, cancel)
                else: self._execute(record, cancel)
            except Exception as error:
                fresh = self._load_record(job_id); state = "cancelled" if cancel.is_set() else "failed"; now = utc_timestamp()
                committed = self._committed_artifact(fresh)
                if committed is not None:
                    self._finish_success(job_id, committed)
                    continue
                if cancel.is_set(): diagnostic = self._diagnostic("PROCESS_CANCELLED", "Rendering was cancelled.", fresh["job"]["target"], {})
                elif isinstance(error, WU4Error): diagnostic = self._diagnostic(error.code, error.message, fresh["job"]["target"], error.details)
                elif isinstance(error, MediaInfrastructureError): diagnostic = self._diagnostic("RENDER_FAILED", error.message, fresh["job"]["target"], {"infrastructure_code": error.code, **error.details})
                else: diagnostic = self._diagnostic("RENDER_FAILED", "Rendering failed.", fresh["job"]["target"], self._unexpected_error_details(error))
                fresh["job"].update({"state": state, "updated_at": now, "finished_at": now, "result_available": True, "diagnostic": diagnostic}); fresh["result"] = self._terminal_result(fresh, state, [diagnostic]); self._save_record(job_id, fresh)

    def _state(self, project_id: str) -> dict[str, Any]:
        state = self.runtime.creation.get(project_id)
        if state.get("contract_version") != "wrld-creation-state/4.0": raise WU4Error("CREATION_V4_REQUIRED", "Creation must be upgraded to v4 before rendering.")
        return state

    @staticmethod
    def _validate_request(request: Mapping[str, Any], mode: str) -> None:
        required = {"contract_version", "mode", "target", "expected_creation_revision", "expected_creation_state_digest", "profile_id", "expected_plan_fingerprint", "submission_id", "output_action", "replacement"}
        if set(request) != required or request.get("contract_version") != "wrld-creation-render-request/1.0" or request.get("mode") != mode: raise WU4Error("REQUEST_INVALID", "The Creation render request is invalid.")
        target = request.get("target")
        if not isinstance(target, Mapping) or set(target) != {"kind", "composition_id"} or target.get("kind") not in PROFILES or not isinstance(target.get("composition_id"), str) or not STABLE_ID_PATTERN.fullmatch(target["composition_id"]): raise WU4Error("REQUEST_INVALID", "The render target is invalid.")
        if type(request["expected_creation_revision"]) is not int or request["expected_creation_revision"] < 1 or not isinstance(request["expected_creation_state_digest"], str) or not SHA256_PATTERN.fullmatch(request["expected_creation_state_digest"]): raise WU4Error("REQUEST_INVALID", "The Creation basis is invalid.")
        if request["profile_id"] not in {value["profile_id"] for value in PROFILES.values()} or request["output_action"] not in {"reuse_verified_or_fail", "replace_verified"}: raise WU4Error("REQUEST_INVALID", "The render profile or output action is invalid.")
        replacement = request["replacement"]
        if request["output_action"] == "reuse_verified_or_fail" and replacement is not None: raise WU4Error("REQUEST_INVALID", "Reuse requests cannot carry replacement authorization.")
        if request["output_action"] == "replace_verified":
            if not isinstance(replacement, Mapping) or set(replacement) != {"artifact_id", "expected_sha256", "expected_report_revision"} or not isinstance(replacement["artifact_id"], str) or not re.fullmatch(r"artifact-[0-9a-f]{64}", replacement["artifact_id"]) or not isinstance(replacement["expected_sha256"], str) or not SHA256_PATTERN.fullmatch(replacement["expected_sha256"]) or type(replacement["expected_report_revision"]) is not int or replacement["expected_report_revision"] < 0: raise WU4Error("REQUEST_INVALID", "The replacement authorization is invalid.")
        if mode == "preflight" and (request["expected_plan_fingerprint"] is not None or request["submission_id"] is not None): raise WU4Error("REQUEST_INVALID", "Preflight cannot carry submission fields.")
        if mode == "submit":
            try: uuid.UUID(str(request["submission_id"]))
            except (ValueError, TypeError, AttributeError): raise WU4Error("REQUEST_INVALID", "Submission requires a UUID identity.") from None
            if not isinstance(request["expected_plan_fingerprint"], str) or not SHA256_PATTERN.fullmatch(request["expected_plan_fingerprint"]): raise WU4Error("REQUEST_INVALID", "Submission requires a valid plan fingerprint.")

    @staticmethod
    def _validate_recovery_request(request: Mapping[str, Any], mode: str) -> None:
        required = {"contract_version", "mode", "target", "failed_job_id", "failed_attempt_id", "expected_creation_revision", "expected_creation_state_digest", "profile_id", "expected_recovery_fingerprint", "submission_id", "output_action", "replacement"}
        if set(request) != required or request.get("contract_version") != RECOVERY_CONTRACT_VERSION or request.get("mode") != mode:
            raise WU4Error("REQUEST_INVALID", "The staged recovery request is invalid.")
        target = request.get("target")
        if not isinstance(target, Mapping) or set(target) != {"kind", "composition_id"} or target.get("kind") not in PROFILES or not isinstance(target.get("composition_id"), str) or not STABLE_ID_PATTERN.fullmatch(target["composition_id"]):
            raise WU4Error("REQUEST_INVALID", "The staged recovery target is invalid.")
        for field in ("failed_job_id", "failed_attempt_id"):
            try: uuid.UUID(str(request[field]))
            except (ValueError, TypeError, AttributeError): raise WU4Error("REQUEST_INVALID", "Recovery job and attempt identities must be UUIDs.") from None
        if type(request["expected_creation_revision"]) is not int or request["expected_creation_revision"] < 1 or not isinstance(request["expected_creation_state_digest"], str) or not SHA256_PATTERN.fullmatch(request["expected_creation_state_digest"]):
            raise WU4Error("REQUEST_INVALID", "The staged recovery Creation basis is invalid.")
        if request["profile_id"] not in {value["profile_id"] for value in PROFILES.values()} or request["output_action"] not in {"reuse_verified_or_fail", "replace_verified"}:
            raise WU4Error("REQUEST_INVALID", "The staged recovery profile or output action is invalid.")
        replacement = request["replacement"]
        if request["output_action"] == "reuse_verified_or_fail" and replacement is not None: raise WU4Error("REQUEST_INVALID", "Recovery reuse requests cannot carry replacement authorization.")
        if request["output_action"] == "replace_verified":
            if not isinstance(replacement, Mapping) or set(replacement) != {"artifact_id", "expected_sha256", "expected_report_revision"} or not isinstance(replacement["artifact_id"], str) or not re.fullmatch(r"artifact-[0-9a-f]{64}", replacement["artifact_id"]) or not isinstance(replacement["expected_sha256"], str) or not SHA256_PATTERN.fullmatch(replacement["expected_sha256"]) or type(replacement["expected_report_revision"]) is not int or replacement["expected_report_revision"] < 0: raise WU4Error("REQUEST_INVALID", "Recovery replacement authorization is invalid.")
        if mode == "preflight" and (request["expected_recovery_fingerprint"] is not None or request["submission_id"] is not None): raise WU4Error("REQUEST_INVALID", "Recovery preflight cannot carry submission fields.")
        if mode == "submit":
            try: uuid.UUID(str(request["submission_id"]))
            except (ValueError, TypeError, AttributeError): raise WU4Error("REQUEST_INVALID", "Recovery submission requires a UUID identity.") from None
            if not isinstance(request["expected_recovery_fingerprint"], str) or not SHA256_PATTERN.fullmatch(request["expected_recovery_fingerprint"]): raise WU4Error("REQUEST_INVALID", "Recovery submission requires a receipt fingerprint.")

    def _recovery_candidate(self, project_id: str, request: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        original = self._load_record(str(request["failed_job_id"]))
        job = original["job"]
        if job["project_id"] != project_id: raise WU4Error("RECOVERY_PROJECT_MISMATCH", "The failed render does not belong to this project.")
        if job["attempt_id"] != request["failed_attempt_id"]: raise WU4Error("RECOVERY_ATTEMPT_MISMATCH", "The failed attempt identity does not match the job.")
        if job["state"] != "failed" or original.get("result", {}).get("state") != "failed": raise WU4Error("RECOVERY_JOB_NOT_FAILED", "Only a terminal failed attempt can supply staged recovery media.")
        plan = self._plan(project_id, request, strict_basis=True)
        if plan["target"] != job["target"] or plan["plan_fingerprint"] != job["plan_fingerprint"] or original["plan"]["plan_fingerprint"] != plan["plan_fingerprint"]:
            raise WU4Error("RECOVERY_PLAN_STALE", "The current render plan no longer matches the failed attempt.")
        if original["plan"]["profile"]["profile_id"] != request["profile_id"] or original["plan"]["profile"] != plan["profile"]:
            raise WU4Error("RECOVERY_PROFILE_MISMATCH", "The failed output profile no longer matches the current plan.")
        renderer = original["plan"].get("renderer", {})
        if renderer.get("renderer_id") != RENDERER_ID or renderer.get("renderer_version") != RENDERER_VERSION:
            raise WU4Error("RECOVERY_RENDERER_MISMATCH", "The failed output renderer is not compatible with this recovery implementation.")
        staged = self._recovery_stage_path(job["job_id"], job["attempt_id"])
        if not staged.is_file() or staged.stat().st_size <= 0: raise WU4Error("RECOVERY_STAGING_MISSING", "The owned staged video is missing or empty.")
        _entry, project_root = self.runtime.catalogs.resolve(project_id)
        if staged.anchor.casefold() != project_root.anchor.casefold(): raise WU4Error("RECOVERY_PUBLICATION_VOLUME_MISMATCH", "Atomic staged recovery requires staging and project output on the same filesystem volume.")
        available = min(shutil.disk_usage(self.root).free, shutil.disk_usage(project_root).free)
        if available < RECOVERY_RECORD_RESERVE_BYTES: raise WU4Error("RECOVERY_DISK_SPACE_INSUFFICIENT", "Available capacity is below the conservative recovery record reserve.", {"estimated_required_bytes": RECOVERY_RECORD_RESERVE_BYTES, "available_bytes": available})
        try: probe = self.prober.probe(staged)
        except MediaInfrastructureError as error: raise WU4Error("RECOVERY_STAGING_INCOMPLETE", "The staged video is not a complete inspectable media file.", {"infrastructure_code": error.code}) from error
        if probe.format_tags.get("comment") != f"wrld_request:{plan['plan_fingerprint']}": raise WU4Error("RECOVERY_PROVENANCE_MISMATCH", "The staged video provenance does not match the render plan.")
        video = next((stream for stream in probe.streams if stream.codec_type == "video"), None)
        audio = next((stream for stream in probe.streams if stream.codec_type == "audio"), None)
        if video is None or audio is None or video.width != plan["profile"]["width"] or video.height != plan["profile"]["height"]:
            raise WU4Error("RECOVERY_PROFILE_MISMATCH", "The staged video does not match the planned media profile.")
        digest, byte_size = self._sha256(staged), staged.stat().st_size
        candidate = {"contract_version": "wrld-creation-render-recovery-candidate/1.0", "project_id": project_id, "failed_job_id": job["job_id"], "failed_attempt_id": job["attempt_id"], "plan_fingerprint": plan["plan_fingerprint"], "staged_sha256": digest, "staged_byte_size": byte_size, "output_relative_path": plan["output"]["relative_path"], "profile_id": plan["profile"]["profile_id"], "renderer_id": RENDERER_ID, "renderer_version": RENDERER_VERSION, "artifact_report_revision": self._artifact_revision(project_id)}
        return plan, candidate

    def _recovery_stage_path(self, job_id: str, attempt_id: str) -> Path:
        return self._contained(self.root / "staging", f"{job_id}/{attempt_id}/output.mp4")

    @staticmethod
    def _recovery_diagnostic(code: str, message: str, details: Mapping[str, Any]) -> dict[str, Any]:
        return {"severity": "error", "code": code, "message": message, "details": dict(details)}

    @staticmethod
    def _composition(kind: str, item: Mapping[str, Any]) -> dict[str, Any]:
        value: dict[str, Any] = {"kind": kind, "status": item["status"], "visual_configuration": item["visual_configuration"]}
        if kind == "album": value["assignments"] = item["assignments"]
        else:
            value.update({"asset_id": item["asset_id"], "expected_sha256": item["expected_sha256"]})
            if kind == "short": value.update({"start_sample": item["start_sample"], "sample_count": item["sample_count"]})
        return value

    @staticmethod
    def _asset(assets: Mapping[str, Any], excluded: set[str], asset_id: str, expected: str, kind: str) -> dict[str, Any]:
        asset = assets.get(asset_id)
        prefix = "VISUAL_SOURCE" if kind == "image" else "RECORDING"
        if asset is None or asset.get("presence") != "present": raise WU4Error(prefix + "_MISSING", "A referenced render source is missing.", {"asset_id": asset_id})
        if asset_id in excluded: raise WU4Error(prefix + "_EXCLUDED", "A referenced render source is excluded.", {"asset_id": asset_id})
        if asset.get("sha256") != expected: raise WU4Error(prefix + "_CHANGED", "A referenced render source changed.", {"asset_id": asset_id})
        if asset.get("kind") != kind or asset.get("probe_status") != "ok": raise WU4Error(prefix + "_UNSUPPORTED", "A referenced render source is unsupported.", {"asset_id": asset_id})
        if kind == "image" and asset.get("capabilities", {}).get("inspection", {}).get("status") != "supported": raise WU4Error("VISUAL_SOURCE_UNSUPPORTED", "The background image is not safely renderable.", {"asset_id": asset_id})
        return asset

    @staticmethod
    def _mime(path: str) -> str:
        suffix = Path(path).suffix.casefold(); return {".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac", ".m4a": "audio/mp4", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(suffix, "application/octet-stream")

    @staticmethod
    def _request_fingerprint(request: Mapping[str, Any]) -> str:
        return canonical_sha256({key: copy.deepcopy(value) for key, value in request.items() if key not in {"mode", "expected_plan_fingerprint", "submission_id", "replacement"}})

    @staticmethod
    def _diagnostic(code: str, message: str, target: Any, details: Mapping[str, Any]) -> dict[str, Any]:
        return {"severity": "error", "code": code, "message": message, "target": copy.deepcopy(target) if isinstance(target, Mapping) else None, "asset_id": details.get("asset_id"), "details": dict(details)}

    @staticmethod
    def _unexpected_error_details(error: BaseException) -> dict[str, Any]:
        reason = re.sub(r"(?i)[A-Z]:[\\/][^\r\n\"']+", "<path>", str(error))
        reason = re.sub(r"\\\\[^\r\n\"']+", "<path>", reason)
        return {"reason": reason}

    def _job_document(self, project_id: str, request: Mapping[str, Any], plan: Mapping[str, Any], job_id: str, attempt_id: str, now: str) -> dict[str, Any]:
        return {"contract_version": "wrld-creation-render-job/1.0", "job_id": job_id, "attempt_id": attempt_id, "submission_id": request["submission_id"], "project_id": project_id, "target": copy.deepcopy(request["target"]), "request_fingerprint": self._request_fingerprint(request), "plan_fingerprint": plan["plan_fingerprint"], "state": "queued", "phase": "queued", "progress": {"phase_percent": None, "processed_samples": None, "total_samples": plan["timeline"]["total_samples"], "current_source": None, "total_sources": len(plan["audio_sources"]), "elapsed_seconds": 0, "eta_seconds": None}, "queue_position": None, "created_at": now, "started_at": None, "updated_at": now, "last_heartbeat_at": None, "finished_at": None, "retry_of_attempt_id": None, "recovery": "none", "diagnostic": None, "result_available": False}

    def _terminal_result(self, record: Mapping[str, Any], state: str, diagnostics: list[dict[str, Any]], artifacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        job, plan = record["job"], record["plan"]
        return {"contract_version": "wrld-creation-render-result/1.0", "job_id": job["job_id"], "attempt_id": job["attempt_id"], "project_id": job["project_id"], "target": job["target"], "state": state, "plan_fingerprint": plan["plan_fingerprint"], "creation_basis": plan["creation_basis"], "profile_id": plan["profile"]["profile_id"], "renderer_id": RENDERER_ID, "renderer_version": RENDERER_VERSION, "timeline": plan["timeline"], "artifacts": artifacts or [], "diagnostics": diagnostics, "started_at": job["started_at"] or job["created_at"], "finished_at": job["finished_at"] or utc_timestamp()}

    def _reused_job(self, project_id: str, request: Mapping[str, Any], plan: Mapping[str, Any], artifact: Mapping[str, Any]) -> dict[str, Any]:
        now = utc_timestamp(); job = self._job_document(project_id, request, plan, str(uuid.uuid4()), str(uuid.uuid4()), now); job.update({"state": "succeeded", "phase": "completed", "started_at": now, "updated_at": now, "last_heartbeat_at": now, "finished_at": now, "result_available": True}); job["progress"].update({"phase_percent": 100.0, "processed_samples": plan["timeline"]["total_samples"], "eta_seconds": 0}); record = {"job": job, "request": copy.deepcopy(dict(request)), "plan": copy.deepcopy(dict(plan)), "result": None}; record["result"] = self._terminal_result(record, "succeeded", [], [copy.deepcopy(dict(artifact))]); self._save_record(job["job_id"], record); return job

    def _validate_replacement(self, project_id: str, request: Mapping[str, Any], existing: Mapping[str, Any] | None) -> None:
        if request.get("output_action") != "replace_verified" or existing is None: raise WU4Error("OUTPUT_EXISTS", "A completed output already exists.")
        receipt = request.get("replacement")
        if not isinstance(receipt, Mapping) or receipt.get("artifact_id") != existing["artifact_id"] or receipt.get("expected_sha256") != existing["sha256"] or receipt.get("expected_report_revision") != self._artifact_revision(project_id): raise WU4Error("OUTPUT_REPLACEMENT_STALE", "The replacement authorization is stale.")

    def _artifact_file(self, project_id: str) -> Path: return self.root / "artifacts" / f"{project_id}.json"
    def _artifact_document(self, project_id: str) -> dict[str, Any]:
        path = self._artifact_file(project_id)
        return self._read_json(path) if path.is_file() else {"revision": 0, "artifacts": []}
    def _artifact_index(self, project_id: str) -> list[dict[str, Any]]: return copy.deepcopy(self._artifact_document(project_id)["artifacts"])
    def _artifact_revision(self, project_id: str) -> int: return int(self._artifact_document(project_id)["revision"])
    def _artifact_for_path(self, project_id: str, path: str) -> dict[str, Any] | None: return next((item for item in self._artifact_index(project_id) if item["relative_path"].casefold() == path.casefold()), None)
    def _publish_artifact(self, project_id: str, artifact: Mapping[str, Any]) -> None:
        document = self._artifact_document(project_id); document["artifacts"] = [item for item in document["artifacts"] if item["relative_path"].casefold() != artifact["relative_path"].casefold()] + [copy.deepcopy(dict(artifact))]; document["revision"] += 1; self._atomic(self._artifact_file(project_id), document)

    def _record_path(self, job_id: str) -> Path: return self.root / "jobs" / f"{job_id}.json"
    def _save_record(self, job_id: str, record: Mapping[str, Any]) -> None: self._atomic(self._record_path(job_id), record)
    def _load_record(self, job_id: str) -> dict[str, Any]:
        path = self._record_path(job_id)
        if not path.is_file(): raise WU4Error("RESOURCE_NOT_FOUND", "The render job was not found.")
        return self._read_json(path)
    def _records(self) -> list[dict[str, Any]]:
        directory = self.root / "jobs"
        return [self._read_json(path) for path in directory.glob("*.json")] if directory.is_dir() else []
    def _recover(self) -> None:
        records = sorted(self._records(), key=lambda value: (value["job"]["created_at"], value["job"]["job_id"]))
        for record in records:
            job = record["job"]
            if job["state"] == "queued": self._queue.append(job["job_id"]); self._cancel[job["job_id"]] = threading.Event()
            elif job["state"] in {"running", "cancel_requested"}:
                artifact = self._committed_artifact(record)
                now = utc_timestamp()
                if artifact is not None:
                    job.update({"state": "succeeded", "phase": "completed", "updated_at": now, "finished_at": now, "recovery": "reconciling", "diagnostic": None, "result_available": True}); record["result"] = self._terminal_result(record, "succeeded", [], [artifact])
                    record["publication"] = {"state": "result_committed", "artifact": artifact}
                else:
                    self._rollback_uncommitted_publication(record)
                    diagnostic = self._diagnostic("RECOVERY_INDETERMINATE", "Rendering was interrupted before durable completion.", job["target"], {}); job.update({"state": "failed", "phase": "completed", "updated_at": now, "finished_at": now, "recovery": "indeterminate", "diagnostic": diagnostic, "result_available": True}); record["result"] = self._terminal_result(record, "failed", [diagnostic])
                self._save_record(job["job_id"], record)
                if artifact is not None: self._cleanup_success_staging(record)

    def _committed_artifact(self, record: Mapping[str, Any]) -> dict[str, Any] | None:
        publication = record.get("publication")
        candidate = publication.get("artifact") if isinstance(publication, Mapping) else None
        if not isinstance(candidate, Mapping) or publication.get("state") not in {"verified", "artifact_committed", "result_committed"}: return None
        registered = self._artifact_for_path(record["job"]["project_id"], record["plan"]["output"]["relative_path"])
        if registered is None or registered.get("artifact_id") != candidate.get("artifact_id") or registered.get("plan_fingerprint") != record["job"]["plan_fingerprint"]: return None
        if not self._artifact_file_is_current(record["job"]["project_id"], registered): return None
        return copy.deepcopy(registered)

    def _rollback_uncommitted_publication(self, record: Mapping[str, Any]) -> None:
        publication = record.get("publication")
        artifact = publication.get("artifact") if isinstance(publication, Mapping) else None
        if not isinstance(artifact, Mapping) or publication.get("state") != "verified": return
        job, plan = record["job"], record["plan"]
        registered = self._artifact_for_path(job["project_id"], plan["output"]["relative_path"])
        replacement = record.get("request", {}).get("replacement")
        if registered is not None:
            old_receipt_matches = (
                isinstance(replacement, Mapping)
                and registered.get("artifact_id") == replacement.get("artifact_id")
                and registered.get("sha256") == replacement.get("expected_sha256")
            )
            if not old_receipt_matches: return
        _entry, project_root = self.runtime.catalogs.resolve(job["project_id"])
        final = self._contained(project_root, plan["output"]["relative_path"])
        if not final.is_file() or self._sha256(final) != artifact.get("sha256"): return
        if record.get("recovery") is not None:
            recovery = record["recovery"]; staged = self._recovery_stage_path(recovery["failed_job_id"], recovery["failed_attempt_id"])
        else:
            staged = self.root / "staging" / job["job_id"] / job["attempt_id"] / "output.mp4"
        if staged.exists(): return
        staged.parent.mkdir(parents=True, exist_ok=True); os.replace(final, staged)
        if isinstance(replacement, Mapping):
            history = project_root / "output" / ".wrld-history" / str(replacement.get("artifact_id")) / f"{replacement.get('expected_sha256')}.mp4"
            if history.is_file() and self._sha256(history) == replacement.get("expected_sha256"): os.replace(history, final)

    def _cleanup_success_staging(self, record: Mapping[str, Any]) -> None:
        job = record["job"]
        owned = self.root / "staging" / job["job_id"] / job["attempt_id"]
        # No per-file ownership ledger exists yet. Remove only directories that
        # are already empty; retained known/unknown files are reported rather
        # than guessed safe for deletion.
        for directory in (owned, owned.parent):
            try: directory.rmdir()
            except OSError: break

    def _render_capacity(self, project_id: str, plan: Mapping[str, Any]) -> dict[str, Any]:
        _entry, project_root = self.runtime.catalogs.resolve(project_id)
        source_bytes = 0
        for source in [*plan["audio_sources"], plan["background_source"]]:
            path = self._contained(project_root, source["relative_path"])
            if path.is_file(): source_bytes += path.stat().st_size
        pcm_bytes = int(plan["timeline"]["total_samples"]) * 4
        estimate = source_bytes + (pcm_bytes * 3)
        free = shutil.disk_usage(self.root).free
        same_volume = self.root.anchor.casefold() == project_root.anchor.casefold()
        return {"sufficient": same_volume and free >= estimate, "estimated_required_bytes": estimate, "available_bytes": free, "estimate_basis": "source_snapshots_plus_three_pcm_equivalents", "same_publication_volume": same_volume}

    def _with_queue_position(self, job: Mapping[str, Any]) -> dict[str, Any]:
        value = copy.deepcopy(dict(job))
        with self._guard:
            value["queue_position"] = list(self._queue).index(value["job_id"]) + 1 if value["job_id"] in self._queue else None
        return value

    def _artifact_file_is_current(self, project_id: str, artifact: Mapping[str, Any]) -> bool:
        try:
            _entry, root = self.runtime.catalogs.resolve(project_id)
            path = self._contained(root, str(artifact["relative_path"]))
            return path.is_file() and self._sha256(path) == artifact["sha256"]
        except (OSError, WU4Error):
            return False

    def _fresh_verify_artifact(self, project_id: str, artifact: Mapping[str, Any]) -> None:
        if not self._artifact_file_is_current(project_id, artifact):
            raise WU4Error("OUTPUT_INVALID", "The registered output is missing or changed on disk.")
        _entry, root = self.runtime.catalogs.resolve(project_id)
        path = self._contained(root, str(artifact["relative_path"]))
        media = artifact["media"]
        expected = {"video_codec": media["video_codec"], "audio_codec": media["audio_codec"], "pixel_format": media["pixel_format"], "width": media["width"], "height": media["height"], "frame_rate": media["frame_rate"], "audio_sample_rate": media["audio_sample_rate"], "audio_channels": media["audio_channels"], "video_profile": media["video_profile"], "audio_profile": media["audio_profile"], "color_space": media["color_space"], "color_transfer": media["color_transfer"], "color_primaries": media["color_primaries"], "duration_seconds": media["duration_seconds"], "duration_tolerance_seconds": 0.25, "request_digest": artifact["plan_fingerprint"], "faststart": True, "full_decode": True, "decode_timeout_seconds": max(600, float(media["duration_seconds"]) * 4)}
        try: self.verifier.verify(path, expected)
        except MediaInfrastructureError as error: raise WU4Error("OUTPUT_INVALID", "The prior artifact no longer passes verification.", error.details) from error

    @staticmethod
    def _atomic(path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        try:
            for attempt in range(8):
                try:
                    os.replace(temporary, path)
                    return
                except PermissionError:
                    if attempt == 7:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        for attempt in range(8):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.05 * (attempt + 1))
        raise AssertionError("unreachable")

    @staticmethod
    def _contained(root: Path, relative: str) -> Path:
        candidate = (root / Path(relative)).resolve(strict=False); resolved = root.resolve()
        if not candidate.is_relative_to(resolved): raise WU4Error("OUTPUT_PATH_INVALID", "A render path escapes the selected project.")
        return candidate
    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""): digest.update(chunk)
        return digest.hexdigest()


__all__ = ["CreationRenderService"]
