from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from wrld_video_studio.domain.canonical_json import canonical_json_bytes, canonical_sha256
from wrld_video_studio.domain.video_export import VideoTrack, build_timeline, chapters_text
from wrld_video_studio.domain.wu4 import WU4Error


EDITOR_VERSION = "wrld-youtube-metadata-editor/1.0"
EXPORT_VERSION = "wrld-youtube-metadata/1.0"
GENERATION_VERSION = "wrld-youtube-metadata-draft/1.0"
VALIDATION_VERSION = "wrld-youtube-metadata-validation/1.0"
RECONCILE_PREVIEW_VERSION = "wrld-youtube-metadata-reconcile-preview/1.0"
EXPORT_PREVIEW_VERSION = "wrld-youtube-metadata-export-preview/1.0"
EXPORT_RESULT_VERSION = "wrld-youtube-metadata-export-result/1.0"
CREATION_V4 = "wrld-creation-state/4.0"
PLACEHOLDER = re.compile(r"\{\{[^{}]+\}\}")
FIELDS = (
    "title", "description", "tags", "hashtags", "artist_name", "channel_name",
    "credits", "links", "visibility", "pinned_comment", "release_album_plan_id",
    "related_video_url",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _field(value: Any, origin: str = "generated", source: str | None = None) -> dict[str, Any]:
    return {"value": value, "origin": origin, "source_fingerprint": source}


def _target_key(kind: str, value: str) -> str:
    return f"{kind}:{value}"


def _diagnostic(code: str, severity: str, target_key: str | None, field: str | None, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, "target_key": target_key, "field": field, "message": message, "details": details}


class YouTubeMetadataService:
    def __init__(self, catalogs: Any, inventories: Any, albums: Any, creation: Any, store: Any) -> None:
        self.catalogs = catalogs
        self.inventories = inventories
        self.albums = albums
        self.creation = creation
        self.store = store

    def get(self, project_id: str) -> dict[str, Any]:
        self.catalogs.resolve(project_id)
        try:
            return self.store.read(project_id)
        except WU4Error as error:
            if error.code == "PROJECT_DOCUMENT_NOT_FOUND":
                raise WU4Error("METADATA_STATE_NOT_FOUND", "Publishing metadata has not been initialized for this project.") from error
            raise

    def initialize(self, project_id: str, save_id: str, creation_revision: int, creation_state_digest: str) -> dict[str, Any]:
        self.catalogs.resolve(project_id)
        try:
            self.store.read(project_id)
        except WU4Error as error:
            if error.code != "PROJECT_DOCUMENT_NOT_FOUND":
                raise
        else:
            raise WU4Error("METADATA_ALREADY_INITIALIZED", "Publishing metadata is already initialized for this project.")
        creation = self._creation(project_id)
        if creation["revision"] != creation_revision or creation["state_digest"] != creation_state_digest:
            raise WU4Error("SOURCE_CHANGED", "Creation changed before metadata initialization.", {"current_revision": creation["revision"]})
        candidate = self._initial(project_id, creation, save_id)
        return self.store.create(project_id, candidate)

    def put(self, project_id: str, expected_revision: int, save_id: str, state: Mapping[str, Any]) -> dict[str, Any]:
        current = self.get(project_id)
        if current["revision"] != expected_revision:
            raise WU4Error("REVISION_CONFLICT", "Stored publishing metadata changed before this save.", {"expected_revision": expected_revision, "actual_revision": current["revision"]})
        candidate = copy.deepcopy(dict(state))
        candidate.update({"contract_version": EDITOR_VERSION, "project_id": project_id, "revision": expected_revision, "save_id": save_id, "state_digest": current["state_digest"]})
        self._semantic_validate(candidate)
        report = self.validate(project_id, candidate, "draft", None)
        fingerprints = {item["target_key"]: item["approval_fingerprint"] for item in report["target_fingerprints"]}
        for target in candidate["targets"]:
            approval = target.get("approval")
            if approval is not None and approval.get("approved_fingerprint") != fingerprints.get(target["target_key"]):
                # Existing stale approvals are preserved, but a newly invented value is rejected.
                old = next((item.get("approval") for item in current["targets"] if item["target_key"] == target["target_key"]), None)
                if approval != old:
                    raise WU4Error("METADATA_APPROVAL_INVALID", "The metadata approval fingerprint is stale or was not computed by the server.", {"target_key": target["target_key"]})
        return self.store.update(project_id, expected_revision, candidate)

    def validate(self, project_id: str, state: Mapping[str, Any], mode: str, target_keys: Sequence[str] | None) -> dict[str, Any]:
        if mode not in {"draft", "approval", "export"}:
            raise WU4Error("METADATA_STATE_INVALID", "Metadata validation mode is invalid.")
        candidate = copy.deepcopy(dict(state))
        self._semantic_validate(candidate)
        if candidate.get("project_id") != project_id:
            raise WU4Error("METADATA_STATE_INVALID", "Publishing metadata does not match the requested project.")
        selected = set(target_keys) if target_keys is not None else None
        known = {item["target_key"] for item in candidate["targets"]}
        if selected is not None and (len(selected) != len(target_keys or ()) or selected - known):
            raise WU4Error("METADATA_EXPORT_SELECTION_INVALID", "Metadata target selection is invalid.")
        current_creation = self._creation(project_id)
        current_source = self._source_metadata_fingerprint(project_id)
        diagnostics: list[dict[str, Any]] = []
        fingerprints: list[dict[str, Any]] = []
        titles: dict[str, list[str]] = {}
        for target in candidate["targets"]:
            key = target["target_key"]
            if selected is not None and key not in selected:
                continue
            target_diagnostics, resolved = self._validate_target(target, mode, candidate)
            diagnostics.extend(target_diagnostics)
            title = str(resolved.get("title", "")).casefold()
            if title:
                titles.setdefault(title, []).append(key)
            current = self._current_target(current_creation, target["target"])
            if current is None:
                diagnostics.append(_diagnostic("TARGET_REFERENCE_INVALID", "error", key, "/target", "The Creation target no longer exists."))
            else:
                fingerprint = self._creation_target_fingerprint(current, target["target"]["kind"])
                if fingerprint != target["basis"]["creation_target_fingerprint"]:
                    diagnostics.append(_diagnostic("SOURCE_REFERENCE_CHANGED", "error" if mode != "draft" else "warning", key, "/basis/creation_target_fingerprint", "The Creation target changed after metadata reconciliation."))
            if target["basis"]["source_metadata_fingerprint"] != current_source:
                diagnostics.append(_diagnostic("SOURCE_METADATA_CHANGED", "error" if mode != "draft" else "warning", key, "/basis/source_metadata_fingerprint", "Source metadata changed after metadata reconciliation."))
            approval_fingerprint = self._approval_fingerprint(target, resolved)
            fingerprints.append({"target_key": key, "approval_fingerprint": approval_fingerprint})
            if mode == "export":
                approval = target.get("approval")
                if approval is None:
                    diagnostics.append(_diagnostic("APPROVAL_REQUIRED", "error", key, "/approval", "Explicit metadata approval is required for export."))
                elif approval.get("approved_fingerprint") != approval_fingerprint:
                    diagnostics.append(_diagnostic("APPROVAL_STALE", "error", key, "/approval", "Metadata approval is stale."))
        for keys in titles.values():
            if len(keys) > 1:
                for key in keys:
                    diagnostics.append(_diagnostic("DUPLICATE_TITLE", "warning", key, "/content/title/value", "Another selected target has the same title.", target_keys=keys))
        order = {item["target_key"]: index for index, item in enumerate(candidate["targets"])}
        diagnostics.sort(key=lambda item: (order.get(item["target_key"], 10**9), item["field"] or "", 0 if item["severity"] == "error" else 1, item["code"]))
        return {"contract_version": VALIDATION_VERSION, "mode": mode, "valid": not any(item["severity"] == "error" for item in diagnostics), "target_fingerprints": fingerprints, "diagnostics": diagnostics}

    def reconcile_preview(self, project_id: str, expected_revision: int, refresh_fields: Sequence[Mapping[str, str]], carry_chapter_labels: Sequence[Mapping[str, str]]) -> dict[str, Any]:
        current = self.get(project_id)
        if current["revision"] != expected_revision:
            raise WU4Error("REVISION_CONFLICT", "Stored publishing metadata changed before reconciliation.", {"actual_revision": current["revision"]})
        fresh = self._initial(project_id, self._creation(project_id), current["save_id"])
        old_by_key = {item["target_key"]: item for item in current["targets"]}
        refresh = {(item["target_key"], item["field"]) for item in refresh_fields}
        carries = {(item["target_key"], item["track_id"]) for item in carry_chapter_labels}
        changes: list[dict[str, Any]] = []
        merged: list[dict[str, Any]] = []
        for item in fresh["targets"]:
            key = item["target_key"]
            old = old_by_key.pop(key, None)
            if old is None:
                changes.append({"kind": "add_target", "target_key": key, "field": None})
                merged.append(item)
                continue
            result = copy.deepcopy(old)
            if old["lifecycle"] != item["lifecycle"]:
                changes.append({"kind": "restore_target" if item["lifecycle"] == "active" else "archive_target", "target_key": key, "field": None})
            result["lifecycle"] = item["lifecycle"]
            result["target"] = item["target"]
            for field in FIELDS:
                if (key, field) in refresh:
                    result["content"][field] = copy.deepcopy(item["content"][field])
                    changes.append({"kind": "refresh_field", "target_key": key, "field": field})
            if item["chapters"] is not None and old.get("chapters") is not None:
                old_labels = {entry["track_id"]: entry["label"] for entry in old["chapters"]["entries"]}
                for entry in item["chapters"]["entries"]:
                    if (key, entry["track_id"]) in carries and entry["track_id"] in old_labels:
                        entry["label"] = copy.deepcopy(old_labels[entry["track_id"]])
                        changes.append({"kind": "carry_chapter_label", "target_key": key, "field": entry["track_id"]})
            if old.get("chapters") != item.get("chapters"):
                changes.append({"kind": "refresh_chapter_source", "target_key": key, "field": None})
            result["chapters"] = item["chapters"]
            result["basis"] = item["basis"]
            merged.append(result)
        for orphan in old_by_key.values():
            preserved = copy.deepcopy(orphan)
            if preserved["lifecycle"] != "orphaned":
                changes.append({"kind": "orphan_target", "target_key": preserved["target_key"], "field": None})
            preserved["lifecycle"] = "orphaned"
            merged.append(preserved)
        candidate = copy.deepcopy(current)
        candidate["creation_basis"] = fresh["creation_basis"]
        candidate["targets"] = merged
        preview = canonical_sha256({"editor_revision": expected_revision, "candidate": candidate, "refresh_fields": list(refresh_fields), "carry_chapter_labels": list(carry_chapter_labels)})
        return {"contract_version": RECONCILE_PREVIEW_VERSION, "editor_revision": expected_revision, "creation_revision": fresh["creation_basis"]["revision"], "preview_fingerprint": preview, "changes": changes, "candidate": candidate, "diagnostics": []}

    def reconcile(self, project_id: str, expected_revision: int, save_id: str, preview_fingerprint: str, refresh_fields: Sequence[Mapping[str, str]], carry_chapter_labels: Sequence[Mapping[str, str]]) -> dict[str, Any]:
        preview = self.reconcile_preview(project_id, expected_revision, refresh_fields, carry_chapter_labels)
        if preview["preview_fingerprint"] != preview_fingerprint:
            raise WU4Error("METADATA_RECONCILE_STALE", "The metadata reconciliation preview is stale.")
        return self.put(project_id, expected_revision, save_id, preview["candidate"])

    def export_preview(self, project_id: str, expected_revision: int, target_keys: Sequence[str]) -> dict[str, Any]:
        state = self.get(project_id)
        if state["revision"] != expected_revision:
            raise WU4Error("REVISION_CONFLICT", "Stored publishing metadata changed before export preview.", {"actual_revision": state["revision"]})
        if not target_keys or len(set(target_keys)) != len(target_keys):
            raise WU4Error("METADATA_EXPORT_SELECTION_INVALID", "Export requires a nonempty unique target selection.")
        validation = self.validate(project_id, state, "export", target_keys)
        if not validation["valid"]:
            # An ineligible set has no schema-valid portable document because portable entries
            # require real approval evidence. Never synthesize an approval timestamp merely to
            # populate a preview; return the approved validation failure envelope instead.
            raise WU4Error("METADATA_VALIDATION_FAILED", "The selected metadata is not eligible for export.", {"diagnostics": validation["diagnostics"]})
        selected = [next((item for item in state["targets"] if item["target_key"] == key), None) for key in target_keys]
        if any(item is None for item in selected):
            raise WU4Error("METADATA_EXPORT_SELECTION_INVALID", "An export target does not exist.")
        document = self._export_document(project_id, selected, validation)
        path = self._export_path(project_id)
        existing_sha, existing_document = self._existing_export(path, project_id)
        predicted_revision = 1
        if existing_document is not None:
            predicted_revision = existing_document["revision"] if existing_document.get("content_fingerprint") == document["content_fingerprint"] else existing_document["revision"] + 1
        document["revision"] = predicted_revision
        data = self._export_bytes(document)
        proposed_sha = _sha_bytes(data)
        preview = canonical_sha256({"editor_revision": expected_revision, "target_keys": list(target_keys), "approval_fingerprints": [item["approval"]["approved_fingerprint"] for item in selected], "proposed_sha256": proposed_sha, "predicted_export_revision": predicted_revision, "existing_sha256": existing_sha})
        return {"contract_version": EXPORT_PREVIEW_VERSION, "editor_revision": expected_revision, "eligible": validation["valid"], "preview_fingerprint": preview, "proposed_sha256": proposed_sha, "predicted_export_revision": predicted_revision, "existing_sha256": existing_sha, "document": document, "diagnostics": validation["diagnostics"]}

    def export(self, project_id: str, expected_revision: int, target_keys: Sequence[str], preview_fingerprint: str, replace_existing: bool, expected_existing_sha256: str | None) -> dict[str, Any]:
        preview = self.export_preview(project_id, expected_revision, target_keys)
        if preview["preview_fingerprint"] != preview_fingerprint:
            raise WU4Error("METADATA_EXPORT_PREVIEW_STALE", "The metadata export preview is stale.")
        if not preview["eligible"]:
            raise WU4Error("METADATA_VALIDATION_FAILED", "The selected metadata is not eligible for export.", {"diagnostics": preview["diagnostics"]})
        path = self._export_path(project_id)
        data = self._export_bytes(preview["document"])
        current_sha = _sha_bytes(path.read_bytes()) if path.exists() else None
        if current_sha == preview["proposed_sha256"]:
            return self._export_result(preview, path, reused=True)
        if current_sha is not None:
            if not replace_existing:
                raise WU4Error("METADATA_EXPORT_EXISTS", "A different metadata export already exists.", {"existing_sha256": current_sha})
            if expected_existing_sha256 != current_sha or preview["existing_sha256"] != current_sha:
                raise WU4Error("METADATA_EXPORT_CHANGED", "The existing metadata export changed after preview.", {"existing_sha256": current_sha})
        elif replace_existing or expected_existing_sha256 is not None:
            raise WU4Error("METADATA_EXPORT_CHANGED", "The expected metadata export no longer exists.")
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".youtube_metadata.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            staged = Path(temporary)
            if _sha_bytes(staged.read_bytes()) != preview["proposed_sha256"]:
                raise WU4Error("STORAGE_ERROR", "The staged metadata export could not be verified.")
            try:
                os.replace(staged, path)
            except OSError as error:
                raise WU4Error("STORAGE_ERROR", "The metadata export could not be committed atomically.") from error
        finally:
            Path(temporary).unlink(missing_ok=True)
        return self._export_result(preview, path, reused=False)

    def _creation(self, project_id: str) -> dict[str, Any]:
        state = self.creation.get(project_id)
        if state.get("contract_version") != CREATION_V4:
            raise WU4Error("CREATION_UPGRADE_REQUIRED", "Creation must be upgraded to v4 before publishing metadata is initialized.", {"contract_version": state.get("contract_version")})
        result = copy.deepcopy(state)
        result.pop("issues", None)
        return result

    def _source_context(self, project_id: str) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, dict[str, Any]]]:
        inventory = self.inventories.read(project_id)
        by_asset = {item["asset_id"]: item for item in inventory["assets"]}
        try:
            album = self.albums.read(project_id)
        except WU4Error:
            album = None
        tracks: dict[str, dict[str, Any]] = {}
        if album is not None:
            by_path_sha = {(item["relative_path"], item.get("sha256")): item["asset_id"] for item in inventory["assets"]}
            for track in album["tracks"]:
                asset_id = by_path_sha.get((track["audio"], track["audio_sha256"]))
                if asset_id:
                    tracks[asset_id] = track
        return album, inventory, {asset_id: {**track, "asset": by_asset.get(asset_id)} for asset_id, track in tracks.items()}

    def _initial(self, project_id: str, creation: Mapping[str, Any], save_id: str) -> dict[str, Any]:
        album_source, _inventory, tracks = self._source_context(project_id)
        source_fingerprint = self._source_fingerprint(album_source)
        active_albums_by_asset: dict[str, set[str]] = {}
        for album in creation["albums"]:
            if album["status"] == "active":
                for assignment in album["assignments"]:
                    active_albums_by_asset.setdefault(assignment["asset_id"], set()).add(album["album_plan_id"])
        targets: list[dict[str, Any]] = []
        for album in creation["albums"]:
            chapters = self._chapters(project_id, album, album_source, tracks)
            targets.append(self._target(
                "album", album, source_fingerprint,
                title=album["label"], description=f"{album['label']}\n\n{{{{chapters}}}}" if chapters else album["label"],
                artist=album_source["album"]["artist"] if album_source else "",
                channel=album_source["album"]["channel"] if album_source else "",
                hashtags=[], release=None, chapters=chapters,
            ))
        for collection, kind, id_key in (("singles", "single", "single_id"), ("shorts", "short", "short_id")):
            for item in creation[collection]:
                track = tracks.get(item["asset_id"])
                track_title = track["title"] if track else ""
                releases = active_albums_by_asset.get(item["asset_id"], set())
                release = next(iter(releases)) if len(releases) == 1 else None
                title = f"{track_title} #Shorts" if kind == "short" and track_title else track_title
                description = f"{track_title}\n\nWatch the full compilation: {{{{compilation_url}}}}" if kind == "short" and track_title else track_title
                targets.append(self._target(
                    kind, item, source_fingerprint, title=title, description=description,
                    artist=album_source["album"]["artist"] if album_source else "",
                    channel=album_source["album"]["channel"] if album_source else "",
                    hashtags=["#Shorts"] if kind == "short" else [], release=release, chapters=None,
                ))
        return {"contract_version": EDITOR_VERSION, "project_id": project_id, "revision": 1, "save_id": save_id, "generation_version": GENERATION_VERSION, "creation_basis": {"contract_version": CREATION_V4, "revision": creation["revision"], "state_digest": creation["state_digest"]}, "targets": targets, "state_digest": "0" * 64}

    @staticmethod
    def _source_fingerprint(album_source: Mapping[str, Any] | None) -> str:
        return canonical_sha256({"album": album_source["album"] if album_source else None, "source_fingerprint": album_source["source_fingerprint"] if album_source else None, "generation_version": GENERATION_VERSION})

    def _source_metadata_fingerprint(self, project_id: str) -> str:
        album_source, _inventory, _tracks = self._source_context(project_id)
        return self._source_fingerprint(album_source)

    def _target(self, kind: str, source: Mapping[str, Any], source_fingerprint: str, *, title: str, description: str, artist: str, channel: str, hashtags: list[str], release: str | None, chapters: dict[str, Any] | None) -> dict[str, Any]:
        id_key = {"album": "album_plan_id", "single": "single_id", "short": "short_id"}[kind]
        identity = str(source[id_key])
        target_reference = {"kind": kind, id_key: identity}
        content = {
            "title": _field(title, "generated", source_fingerprint),
            "description": _field(description, "generated", source_fingerprint),
            "tags": _field([], "generated", source_fingerprint),
            "hashtags": _field(hashtags, "generated", source_fingerprint),
            "artist_name": _field(artist, "supplied" if artist else "generated", source_fingerprint),
            "channel_name": _field(channel, "supplied" if channel else "generated", source_fingerprint),
            "credits": _field([], "generated", source_fingerprint),
            "links": _field([], "generated", source_fingerprint),
            "visibility": _field("private"),
            "pinned_comment": _field(None),
            "release_album_plan_id": _field(release, "generated", source_fingerprint),
            "related_video_url": _field(None),
        }
        return {"target_key": _target_key(kind, identity), "target": target_reference, "lifecycle": source["status"], "basis": {"creation_target_fingerprint": self._creation_target_fingerprint(source, kind), "source_metadata_fingerprint": source_fingerprint, "chapter_source_fingerprint": chapters["source"]["canonical_text_sha256"] if chapters else None}, "content": content, "chapters": chapters, "approval": None}

    def _chapters(self, project_id: str, album_plan: Mapping[str, Any], album_source: Mapping[str, Any] | None, tracks_by_asset: Mapping[str, Mapping[str, Any]]) -> dict[str, Any] | None:
        if album_source is None or len(album_plan["assignments"]) != len(album_source["tracks"]):
            return None
        mapped = [tracks_by_asset.get(item["asset_id"]) for item in album_plan["assignments"]]
        if any(item is None for item in mapped) or [item["id"] for item in mapped if item] != [item["id"] for item in album_source["tracks"]]:
            return None
        video_tracks = tuple(VideoTrack(item["id"], item["number"], item["title"], item["audio"]) for item in album_source["tracks"])
        timeline = build_timeline(video_tracks, tuple(item["normalized_sample_count"] for item in album_source["tracks"]))
        text = chapters_text(timeline)
        text_sha = _sha_bytes(text.encode("utf-8"))
        root = self.catalogs.resolve(project_id)[1]
        artifact = root / "output" / "metadata" / "chapters.txt"
        report_path = root / "output" / "metadata" / "render_report.json"
        source = {"source_kind": "wu3a_timeline", "canonical_text_sha256": text_sha, "artifact_path": None, "artifact_sha256": None, "render_report_revision": None}
        if self._safe_project_file(root, artifact) and self._safe_project_file(root, report_path):
            try:
                artifact_sha = _sha_bytes(artifact.read_bytes())
                report = json.loads(report_path.read_text(encoding="utf-8"))
                verified = any(item.get("kind") == "chapters" and item.get("path") == "output/metadata/chapters.txt" and item.get("sha256") == artifact_sha for item in report.get("artifacts", []))
                if verified and artifact_sha == text_sha:
                    source = {"source_kind": "verified_artifact", "canonical_text_sha256": text_sha, "artifact_path": "output/metadata/chapters.txt", "artifact_sha256": artifact_sha, "render_report_revision": report.get("revision")}
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        entries = []
        for index, entry in enumerate(timeline):
            entries.append({"index": index, "track_id": entry.track_id, "start_seconds": entry.display_seconds, "source_label": entry.title, "label": _field(entry.title, "generated", text_sha)})
        return {"source": source, "entries": entries}

    @staticmethod
    def _safe_project_file(root: Path, path: Path) -> bool:
        try:
            resolved_root = root.resolve(strict=True)
            resolved_path = path.resolve(strict=True)
            return not YouTubeMetadataService._is_link(path) and resolved_path.is_relative_to(resolved_root) and resolved_path.is_file()
        except OSError:
            return False

    @staticmethod
    def _is_link(path: Path) -> bool:
        is_junction = getattr(path, "is_junction", None)
        return path.is_symlink() or bool(is_junction and is_junction())

    @staticmethod
    def _creation_target_fingerprint(value: Mapping[str, Any], kind: str) -> str:
        if kind == "album":
            source = {"album_plan_id": value["album_plan_id"], "label": value["label"], "assignments": [{key: item[key] for key in ("assignment_id", "asset_id", "expected_sha256")} for item in value["assignments"]]}
        else:
            key = "single_id" if kind == "single" else "short_id"
            source = {key: value[key], "asset_id": value["asset_id"], "expected_sha256": value["expected_sha256"]}
        return canonical_sha256(source)

    @staticmethod
    def _current_target(creation: Mapping[str, Any], reference: Mapping[str, Any]) -> Mapping[str, Any] | None:
        kind = reference["kind"]
        collection, key = {"album": ("albums", "album_plan_id"), "single": ("singles", "single_id"), "short": ("shorts", "short_id")}[kind]
        return next((item for item in creation[collection] if item[key] == reference[key]), None)

    def _semantic_validate(self, state: Mapping[str, Any]) -> None:
        validate_contract = getattr(self.store, "validate", None)
        if callable(validate_contract):
            try:
                validate_contract(state)
            except WU4Error as error:
                if error.code == "PROJECT_DOCUMENT_INVALID":
                    raise WU4Error("METADATA_STATE_INVALID", "Publishing metadata does not satisfy the approved contract.", dict(error.details)) from error
                raise
        if state.get("contract_version") != EDITOR_VERSION or state.get("generation_version") != GENERATION_VERSION:
            raise WU4Error("METADATA_STATE_INVALID", "Publishing metadata does not satisfy the approved contract.")
        keys: set[str] = set()
        for target in state.get("targets", []):
            key = target.get("target_key")
            reference = target.get("target", {})
            kind = reference.get("kind")
            id_key = {"album": "album_plan_id", "single": "single_id", "short": "short_id"}.get(kind)
            if id_key is None or key != _target_key(kind, str(reference.get(id_key, ""))) or key in keys:
                raise WU4Error("METADATA_STATE_INVALID", "Metadata target identities are inconsistent.", {"target_key": key})
            keys.add(key)
            if set(target.get("content", {})) != set(FIELDS):
                raise WU4Error("METADATA_STATE_INVALID", "Metadata target fields are incomplete.", {"target_key": key})

    def _validate_target(self, target: Mapping[str, Any], mode: str, state: Mapping[str, Any] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        key = target["target_key"]
        content = {name: target["content"][name]["value"] for name in FIELDS}
        diagnostics: list[dict[str, Any]] = []
        if target["lifecycle"] != "active":
            diagnostics.append(_diagnostic("ARCHIVED_TARGET" if target["lifecycle"] == "archived" else "ORPHANED_TARGET", "error" if mode == "export" else "warning", key, "/lifecycle", "Only active metadata targets are exportable."))
        if not content["title"]:
            diagnostics.append(_diagnostic("TITLE_REQUIRED", "error" if mode != "draft" else "warning", key, "/content/title/value", "A title is required for approval and export."))
        if len(content["title"]) > 100:
            diagnostics.append(_diagnostic("TITLE_TOO_LONG", "error", key, "/content/title/value", "The title exceeds 100 Unicode code points."))
        if not content["artist_name"] or not content["channel_name"]:
            diagnostics.append(_diagnostic("IDENTITY_REQUIRED", "error" if mode != "draft" else "warning", key, "/content", "Publishing artist and channel identities are required."))
        resolved = copy.deepcopy(content)
        for field in ("description", "pinned_comment"):
            value = resolved[field]
            if value is None:
                continue
            tokens = PLACEHOLDER.findall(value)
            allowed = {"{{chapters}}", "{{compilation_url}}"}
            for token in tokens:
                if token not in allowed:
                    diagnostics.append(_diagnostic("PLACEHOLDER_UNKNOWN", "error", key, f"/content/{field}/value", "The publishing text contains an unknown placeholder.", placeholder=token))
            if "{{chapters}}" in value:
                if target["target"]["kind"] != "album" or target.get("chapters") is None:
                    diagnostics.append(_diagnostic("PLACEHOLDER_UNRESOLVED", "error" if mode != "draft" else "warning", key, f"/content/{field}/value", "The chapter placeholder has no authoritative chapter source."))
                else:
                    value = value.replace("{{chapters}}", self._chapter_block(target["chapters"]))
            if "{{compilation_url}}" in value:
                if not content["related_video_url"]:
                    diagnostics.append(_diagnostic("PLACEHOLDER_UNRESOLVED", "error" if mode != "draft" else "warning", key, f"/content/{field}/value", "The compilation URL placeholder is unresolved."))
                else:
                    value = value.replace("{{compilation_url}}", content["related_video_url"])
            resolved[field] = value
        if len(resolved["description"]) > 5000:
            diagnostics.append(_diagnostic("DESCRIPTION_TOO_LONG", "error", key, "/content/description/value", "The resolved description exceeds 5,000 Unicode code points."))
        seen_tags: set[str] = set()
        tag_cost = max(0, len(content["tags"]) - 1)
        for tag in content["tags"]:
            normalized = unicodedata.normalize("NFC", tag).casefold()
            if normalized in seen_tags:
                diagnostics.append(_diagnostic("DUPLICATE_TAG", "warning", key, "/content/tags/value", "A tag is duplicated.", tag=tag))
            seen_tags.add(normalized)
            if any(char in tag for char in ',"\r\n') or tag != tag.strip() or not tag:
                diagnostics.append(_diagnostic("TAG_INVALID", "error", key, "/content/tags/value", "Tags cannot contain commas, quotes, line breaks, or surrounding whitespace.", tag=tag))
            tag_cost += len(tag) + (2 if any(char.isspace() for char in tag) else 0)
        if tag_cost > 500:
            diagnostics.append(_diagnostic("TAGS_TOO_LONG", "error", key, "/content/tags/value", "The serialized tag cost exceeds 500 Unicode code points.", cost=tag_cost))
        seen_hashes: set[str] = set()
        for hashtag in content["hashtags"]:
            if not re.fullmatch(r"#[^#\s]+", hashtag):
                diagnostics.append(_diagnostic("HASHTAG_INVALID", "error", key, "/content/hashtags/value", "Hashtags must begin with one # and contain no whitespace."))
            folded = unicodedata.normalize("NFC", hashtag).casefold()
            if folded in seen_hashes:
                diagnostics.append(_diagnostic("DUPLICATE_TAG", "warning", key, "/content/hashtags/value", "A hashtag is duplicated.", hashtag=hashtag))
            seen_hashes.add(folded)
        if target["target"]["kind"] == "album" and target.get("chapters") is None:
            diagnostics.append(_diagnostic("CHAPTER_SOURCE_REQUIRED", "error" if mode != "draft" else "warning", key, "/chapters", "This Album plan has no verified WU3A-equivalent timeline mapping."))
        chapters = target.get("chapters")
        if chapters is not None:
            starts = [entry["start_seconds"] for entry in chapters["entries"]]
            if not starts or starts[0] != 0 or any(right <= left for left, right in zip(starts, starts[1:])):
                diagnostics.append(_diagnostic("CHAPTER_ENTRY_INVALID", "error", key, "/chapters/entries", "Chapter timestamps must begin at zero and increase strictly."))
            if len(starts) < 3 or any(right - left < 10 for left, right in zip(starts, starts[1:])):
                diagnostics.append(_diagnostic("CHAPTERS_NOT_YOUTUBE_ELIGIBLE", "warning", key, "/chapters/entries", "YouTube recommends at least three chapters with adjacent timestamps at least ten seconds apart."))
        release = content["release_album_plan_id"]
        if target["target"]["kind"] == "album" and release is not None:
            diagnostics.append(_diagnostic("TARGET_REFERENCE_INVALID", "error", key, "/content/release_album_plan_id/value", "Album targets cannot reference a release Album plan."))
        elif release is not None and state is not None:
            release_target = next((item for item in state["targets"] if item["target_key"] == _target_key("album", release)), None)
            if release_target is None or release_target["lifecycle"] != "active":
                diagnostics.append(_diagnostic("TARGET_REFERENCE_INVALID", "error" if mode != "draft" else "warning", key, "/content/release_album_plan_id/value", "The release association must name an active Album target."))
        return diagnostics, resolved

    def _approval_fingerprint(self, target: Mapping[str, Any], resolved: Mapping[str, Any]) -> str:
        return canonical_sha256({"algorithm": "wrld-youtube-metadata-approval/1.0", "target_key": target["target_key"], "target_reference": target["target"], "creation_target_fingerprint": target["basis"]["creation_target_fingerprint"], "source_metadata_fingerprint": target["basis"]["source_metadata_fingerprint"], "chapter_source_fingerprint": target["basis"]["chapter_source_fingerprint"], "resolved_metadata": resolved, "effective_chapters": self._effective_chapters(target.get("chapters"))})

    @staticmethod
    def _timestamp(seconds: int) -> str:
        hours, remainder = divmod(seconds, 3600)
        minutes, second = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{second:02d}" if hours else f"{minutes:02d}:{second:02d}"

    def _effective_chapters(self, chapters: Mapping[str, Any] | None) -> list[dict[str, Any]] | None:
        if chapters is None:
            return None
        return [{"track_id": item["track_id"], "start_seconds": item["start_seconds"], "timestamp": self._timestamp(item["start_seconds"]), "label": item["label"]["value"]} for item in chapters["entries"]]

    def _chapter_block(self, chapters: Mapping[str, Any]) -> str:
        return "\n".join(f"{item['timestamp']} {item['label']}" for item in self._effective_chapters(chapters) or [])

    def _export_document(self, project_id: str, selected: Sequence[Mapping[str, Any] | None], validation: Mapping[str, Any]) -> dict[str, Any]:
        by_fingerprint = {item["target_key"]: item["approval_fingerprint"] for item in validation["target_fingerprints"]}
        result: dict[str, Any] = {"contract_version": EXPORT_VERSION, "project_id": project_id, "revision": 1, "content_fingerprint": "0" * 64, "albums": [], "singles": [], "shorts": []}
        for target in selected:
            assert target is not None
            _, resolved = self._validate_target(target, "export")
            common = {"target_key": target["target_key"], "metadata": resolved, "media": None, "thumbnail": None, "approval": {"fingerprint": by_fingerprint[target["target_key"]], "approved_at": target["approval"]["approved_at"]}}
            kind = target["target"]["kind"]
            current = self._current_target(self._creation(project_id), target["target"])
            if kind == "album":
                entry = {**common, "album_plan_id": target["target"]["album_plan_id"], "assignments": [{key: item[key] for key in ("assignment_id", "asset_id", "expected_sha256")} for item in current["assignments"]], "chapter_source_sha256": target["basis"]["chapter_source_fingerprint"], "chapters": self._effective_chapters(target["chapters"])}
                result["albums"].append(entry)
            else:
                id_key = "single_id" if kind == "single" else "short_id"
                entry = {**common, id_key: target["target"][id_key], "recording": {"asset_id": current["asset_id"], "expected_sha256": current["expected_sha256"]}}
                result["singles" if kind == "single" else "shorts"].append(entry)
        content = {"project_id": project_id, "albums": [{key: value for key, value in item.items() if key not in {"media", "thumbnail", "approval"}} for item in result["albums"]], "singles": [{key: value for key, value in item.items() if key not in {"media", "thumbnail", "approval"}} for item in result["singles"]], "shorts": [{key: value for key, value in item.items() if key not in {"media", "thumbnail", "approval"}} for item in result["shorts"]]}
        result["content_fingerprint"] = canonical_sha256(content)
        return result

    def _export_path(self, project_id: str) -> Path:
        _entry, root = self.catalogs.resolve(project_id)
        destination = root / "output" / "metadata" / "youtube_metadata.json"
        try:
            resolved_root = root.resolve(strict=True)
            current = root
            for component in ("output", "metadata"):
                current = current / component
                if current.exists() and (self._is_link(current) or not current.resolve(strict=True).is_relative_to(resolved_root)):
                    raise WU4Error("STORAGE_ERROR", "The metadata output directory is not a safe project-local destination.")
            if destination.exists() and (self._is_link(destination) or not destination.resolve(strict=True).is_relative_to(resolved_root) or not destination.is_file()):
                raise WU4Error("METADATA_EXPORT_OWNERSHIP_UNKNOWN", "The existing metadata destination is not a recognized regular project-local file.")
        except WU4Error:
            raise
        except OSError as error:
            raise WU4Error("STORAGE_ERROR", "The metadata output destination could not be verified.") from error
        return destination

    @staticmethod
    def _export_bytes(document: Mapping[str, Any]) -> bytes:
        return (json.dumps(document, ensure_ascii=False, indent=2, separators=(",", ": ")) + "\n").encode("utf-8")

    @staticmethod
    def _existing_export(path: Path, project_id: str) -> tuple[str | None, dict[str, Any] | None]:
        if not path.exists():
            return None, None
        data = path.read_bytes()
        digest = _sha_bytes(data)
        try:
            document = json.loads(data.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise WU4Error("METADATA_EXPORT_OWNERSHIP_UNKNOWN", "The existing metadata export is not a recognized owned document.", {"existing_sha256": digest}) from error
        if document.get("contract_version") != EXPORT_VERSION or document.get("project_id") != project_id or type(document.get("revision")) is not int:
            raise WU4Error("METADATA_EXPORT_OWNERSHIP_UNKNOWN", "The existing metadata export belongs to another contract or project.", {"existing_sha256": digest})
        return digest, document

    @staticmethod
    def _export_result(preview: Mapping[str, Any], path: Path, *, reused: bool) -> dict[str, Any]:
        data = path.read_bytes()
        return {"contract_version": EXPORT_RESULT_VERSION, "path": "output/metadata/youtube_metadata.json", "sha256": _sha_bytes(data), "byte_size": len(data), "revision": preview["document"]["revision"], "reused": reused, "document": preview["document"]}


__all__ = ["YouTubeMetadataService"]
