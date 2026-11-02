from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any, Mapping

from wrld_video_studio.domain.canonical_json import canonical_sha256
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.wu4 import (
    ALBUM_READ_VERSION,
    EDITOR_STATE_VERSION,
    MIN_APPROVABLE_SHORT_SAMPLES,
    PROJECT_CATALOG_VERSION,
    VALIDATION_REPORT_VERSION,
    WU4Error,
    approval_digest,
    deep_merge_settings,
    primary_short_document,
    stable_primary_short_id,
    portable_directory,
    utc_now,
    validate_effects,
    validate_treatment,
)
from wrld_video_studio.application.ports.wu4 import (
    EditorStateStorePort,
    ProjectCatalogStorePort,
    ProjectLoaderPort,
    ProjectResolverPort,
    SecureProjectFilePort,
)


class ProjectCatalogs:
    def __init__(self, resolver: ProjectResolverPort, store: ProjectCatalogStorePort, loader: ProjectLoaderPort) -> None:
        self.resolver, self.store, self.loader = resolver, store, loader

    def roots(self) -> dict[str, Any]:
        return {"contract_version": PROJECT_CATALOG_VERSION, "roots": list(self.resolver.roots())}

    def directories(self, root_id: str, parent: str = "") -> dict[str, Any]:
        return {"contract_version": PROJECT_CATALOG_VERSION, "root_id": root_id, "parent": parent, "directories": list(self.resolver.directories(root_id, parent))}

    def list(self) -> dict[str, Any]:
        catalog = self.store.read()
        return {"contract_version": PROJECT_CATALOG_VERSION, "revision": catalog["revision"], "projects": [self._public(item) for item in catalog["projects"]]}

    def register(self, root_id: str, relative_path: str) -> dict[str, Any]:
        try: relative_path = portable_directory(relative_path)
        except ValueError as error: raise WU4Error("PROJECT_PATH_INVALID", "The project location is invalid.") from error
        path = self.resolver.resolve_directory(root_id, relative_path)
        enrichment = self._enrichment(path)
        now = utc_now()
        selected: dict[str, Any] = {}

        def operation(payload: dict[str, Any]) -> None:
            for item in payload["projects"]:
                if item["active"] and self._overlaps(item, root_id, relative_path):
                    code = "PROJECT_ALREADY_REGISTERED" if item["relative_path"].casefold() == relative_path.casefold() else "PROJECT_BOUNDARY_OVERLAP"
                    message = "The project is already registered." if code == "PROJECT_ALREADY_REGISTERED" else "The project boundary overlaps an active registered project."
                    raise WU4Error(code, message, {"project_id": item["project_id"]})
            reusable = next((item for item in payload["projects"] if not item["active"] and item["root_id"] == root_id and item["relative_path"].casefold() == relative_path.casefold()), None)
            if reusable is None:
                reusable = {"project_id": str(uuid.uuid4()), "registered_at": now}
                payload["projects"].append(reusable)
            reusable.update({"root_id": root_id, "relative_path": relative_path, "enrichment": enrichment, "inventory_revision": reusable.get("inventory_revision", 0), "active": True, "updated_at": now})
            selected.update(reusable)

        self.store.mutate(operation)
        return self._public(selected)

    def relink(self, project_id: str, root_id: str, relative_path: str) -> dict[str, Any]:
        try: relative_path = portable_directory(relative_path)
        except ValueError as error: raise WU4Error("PROJECT_PATH_INVALID", "The project location is invalid.") from error
        path = self.resolver.resolve_directory(root_id, relative_path)
        enrichment = self._enrichment(path)
        selected: dict[str, Any] = {}

        def operation(payload: dict[str, Any]) -> None:
            item = self._find(payload, project_id)
            for other in payload["projects"]:
                if other["project_id"] != project_id and other["active"] and self._overlaps(other, root_id, relative_path):
                    raise WU4Error("PROJECT_BOUNDARY_OVERLAP", "The project boundary overlaps an active registered project.", {"project_id": other["project_id"]})
            item.update({"root_id": root_id, "relative_path": relative_path, "enrichment": enrichment, "active": True, "updated_at": utc_now()})
            selected.update(item)

        self.store.mutate(operation)
        return self._public(selected)

    def remove(self, project_id: str) -> None:
        def operation(payload: dict[str, Any]) -> None:
            item = self._find(payload, project_id)
            item.update({"active": False, "updated_at": utc_now()})
        self.store.mutate(operation)

    def resolve(self, project_id: str) -> tuple[dict[str, Any], Path]:
        item = self._find(self.store.read(), project_id)
        if not item["active"]:
            raise WU4Error("PROJECT_REMOVED", "The project is no longer active in the catalog.")
        return item, self.resolver.resolve_directory(item["root_id"], item["relative_path"])

    def set_inventory_revision(self, project_id: str, revision: int) -> None:
        def operation(payload: dict[str, Any]) -> None:
            item = self._find(payload, project_id)
            item["inventory_revision"] = revision
            item["updated_at"] = utc_now()
        self.store.mutate(operation)

    @staticmethod
    def _find(payload: Mapping[str, Any], project_id: str) -> dict[str, Any]:
        for item in payload["projects"]:
            if item["project_id"] == project_id:
                return item
        raise WU4Error("PROJECT_NOT_FOUND", "The project identity is unknown.")

    def _load(self, path: Path) -> Any:
        try:
            return self.loader.load(path)
        except MediaInfrastructureError as error:
            raise WU4Error(error.code, error.message, dict(error.details)) from error

    def _public(self, item: Mapping[str, Any]) -> dict[str, Any]:
        value = copy.deepcopy(dict(item))
        enrichment = value.get("enrichment")
        if isinstance(enrichment, dict) and enrichment.get("album_id"):
            value["album_id"] = enrichment["album_id"]
        if item["active"]:
            try:
                self.resolver.resolve_directory(item["root_id"], item["relative_path"])
                value["availability"] = "available"
            except WU4Error:
                value["availability"] = "unavailable"
        else:
            value["availability"] = "removed"
        return value

    @staticmethod
    def _overlaps(item: Mapping[str, Any], root_id: str, relative_path: str) -> bool:
        if item["root_id"] != root_id:
            return False
        left = tuple(part.casefold() for part in item["relative_path"].split("/") if part)
        right = tuple(part.casefold() for part in relative_path.split("/") if part)
        shortest = min(len(left), len(right))
        return left[:shortest] == right[:shortest]

    def _enrichment(self, root: Path) -> dict[str, Any] | None:
        try:
            with self.resolver.open_project_file(root, "video_manifest.json") as resource:
                if resource.size > 8 * 1024 * 1024:
                    return {"status": "invalid", "manifest_format": None, "album_id": None}
                document = json.loads(resource.read().decode("utf-8"))
            format_value = document.get("format") if isinstance(document, dict) else None
            album = document.get("album") if isinstance(document, dict) else None
            album_id = album.get("id") if isinstance(album, dict) else None
            recognized = format_value in {"wrld-video-album/1.0", "wrld-video-album/2.0", "wrld-video-album/3.0", "wrld-video-album/4.0"}
            valid_id = isinstance(album_id, str) and 0 < len(album_id) <= 128
            return {"status": "recognized" if recognized and valid_id else "invalid", "manifest_format": format_value if isinstance(format_value, str) else None, "album_id": album_id if valid_id else None}
        except (WU4Error, OSError, UnicodeError, json.JSONDecodeError):
            manifest = root / "video_manifest.json"
            return None if not manifest.exists() else {"status": "invalid", "manifest_format": None, "album_id": None}


class AlbumProjects:
    def __init__(self, catalogs: ProjectCatalogs, resolver: ProjectResolverPort) -> None:
        self.catalogs, self.resolver = catalogs, resolver
        self._cache: dict[str, dict[str, Any]] = {}

    def read(self, project_id: str) -> dict[str, Any]:
        _entry, root = self.catalogs.resolve(project_id)
        project = self.catalogs._load(root)
        manifest = project.manifest
        if project.normalized_sample_counts is None:
            raise WU4Error("MEDIA_PROBE_REQUIRED", "Normalized album reads require validated WAV durations.")
        manifest_sha = self._hash(root, "video_manifest.json")
        tracks = []
        for track, count in zip(manifest.tracks, project.normalized_sample_counts, strict=True):
            tracks.append({"id": track.id, "number": track.number, "title": track.title, "audio": track.audio, "normalized_sample_count": count, "audio_sha256": self._hash(root, track.audio)})
        visual = {"background": manifest.background}
        if manifest.cover is not None: visual["cover"] = manifest.cover
        if manifest.thumbnail is not None: visual["thumbnail"] = manifest.thumbnail
        artwork_hashes = {key: self._hash(root, path) for key, path in visual.items()}
        effects = getattr(manifest, "effects", None)
        base_effects = effects.to_dict() if effects is not None else {}
        source_fingerprint = canonical_sha256({"manifest_sha256": manifest_sha, "artwork": artwork_hashes, "tracks": [{"id": t["id"], "audio_sha256": t["audio_sha256"], "normalized_sample_count": t["normalized_sample_count"]} for t in tracks]})
        result = {"contract_version": ALBUM_READ_VERSION, "project_id": project_id, "source_fingerprint": source_fingerprint, "manifest_sha256": manifest_sha, "manifest_format": manifest.format, "album": {"id": manifest.album.id, "title": manifest.album.title, "artist": manifest.album.artist, "channel": getattr(manifest.album, "channel", getattr(manifest, "genre_channel", ""))}, "visual": visual, "tracks": tracks, "render": {"profile_id": manifest.profile_id, "effects": base_effects}}
        self._cache[project_id] = copy.deepcopy(result)
        return result

    def validate(self, project_id: str) -> dict[str, Any]:
        try:
            album = self.read(project_id)
            return {"contract_version": VALIDATION_REPORT_VERSION, "project_id": project_id, "valid": True, "source_fingerprint": album["source_fingerprint"], "errors": [], "warnings": []}
        except WU4Error as error:
            return {"contract_version": VALIDATION_REPORT_VERSION, "project_id": project_id, "valid": False, "errors": [{"code": error.code, "message": error.message, "details": error.details}], "warnings": []}

    def open_audio(self, project_id: str, track_id: str) -> tuple[SecureProjectFilePort, dict[str, Any]]:
        album = copy.deepcopy(self._cache.get(project_id)) if project_id in self._cache else self.read(project_id)
        track = next((item for item in album["tracks"] if item["id"] == track_id), None)
        if track is None:
            raise WU4Error("TRACK_NOT_FOUND", "The requested track is not part of this project.")
        _entry, root = self.catalogs.resolve(project_id)
        if self._hash(root, "video_manifest.json") != album["manifest_sha256"]:
            raise WU4Error("SOURCE_CHANGED", "The source manifest changed after the album was loaded.")
        resource = self.resolver.open_project_file(root, track["audio"])
        if resource.sha256() != track["audio_sha256"]:
            resource.close()
            raise WU4Error("SOURCE_CHANGED", "The source audio changed after the album was loaded.")
        return resource, {"etag": '"sha256-' + track["audio_sha256"] + '"', "size": resource.size}

    def _hash(self, root: Path, relative: str) -> str:
        with self.resolver.open_project_file(root, relative) as resource:
            return resource.sha256()


class EditorStates:
    def __init__(self, albums: AlbumProjects, store: EditorStateStorePort) -> None:
        self.albums, self.store = albums, store

    def get(self, project_id: str) -> dict[str, Any]:
        album = self.albums.read(project_id)
        try:
            state = self.store.read(project_id)
        except WU4Error as error:
            if error.code != "EDITOR_STATE_NOT_FOUND": raise
            state = self.store.create(project_id, self._initial(album))
        return self._view(self._validate(state, album), album)

    def put(self, project_id: str, expected_revision: int, save_id: str, document: Mapping[str, Any]) -> dict[str, Any]:
        album = self.albums.read(project_id)
        current = self.store.read(project_id)
        if current["revision"] != expected_revision:
            raise WU4Error("REVISION_CONFLICT", "Stored editor state changed before this save.", {"expected_revision": expected_revision, "actual_revision": current["revision"]})
        if current["source_fingerprint"] != album["source_fingerprint"]:
            raise WU4Error("SOURCE_CHANGED", "The source manifest or media changed after editor state was loaded.")
        candidate = copy.deepcopy(dict(document))
        candidate.pop("resolved", None)
        candidate.update({"contract_version": EDITOR_STATE_VERSION, "project_id": project_id, "album_id": album["album"]["id"], "revision": expected_revision, "save_id": save_id, "source_fingerprint": album["source_fingerprint"], "profile_id": album["render"]["profile_id"], "base_effects": album["render"]["effects"], "state_digest": current["state_digest"]})
        candidate = self._validate(candidate, album)
        stored = self.store.update(project_id, expected_revision, candidate)
        return self._view(stored, album)

    def _initial(self, album: Mapping[str, Any]) -> dict[str, Any]:
        shorts = {track["id"]: primary_short_document(album["project_id"], track["id"], track["normalized_sample_count"]) for track in album["tracks"]}
        return {"contract_version": EDITOR_STATE_VERSION, "project_id": album["project_id"], "album_id": album["album"]["id"], "revision": 1, "save_id": "initial", "source_fingerprint": album["source_fingerprint"], "profile_id": album["render"]["profile_id"], "base_effects": album["render"]["effects"], "album_overrides": {}, "track_overrides": {}, "shorts": shorts, "state_digest": "0" * 64}

    def _validate(self, state: dict[str, Any], album: Mapping[str, Any]) -> dict[str, Any]:
        required = {"contract_version", "project_id", "album_id", "revision", "save_id", "source_fingerprint", "profile_id", "base_effects", "album_overrides", "track_overrides", "shorts", "state_digest"}
        if set(state) != required or state.get("contract_version") != EDITOR_STATE_VERSION:
            raise WU4Error("EDITOR_STATE_INVALID", "Editor state does not satisfy its strict contract.")
        if state.get("project_id") != album["project_id"] or state.get("album_id") != album["album"]["id"] or state.get("profile_id") != album["render"]["profile_id"]:
            raise WU4Error("EDITOR_STATE_INVALID", "Editor state does not match its registered project.")
        if state.get("source_fingerprint") != album["source_fingerprint"]:
            raise WU4Error("SOURCE_CHANGED", "The source manifest or media changed after editor state was created.")
        if state.get("base_effects") != album["render"]["effects"]:
            raise WU4Error("EDITOR_STATE_INVALID", "Manifest-derived settings are authoritative.")
        track_by_id = {item["id"]: item for item in album["tracks"]}
        if set(state.get("track_overrides", {})) - set(track_by_id) or set(state.get("shorts", {})) != set(track_by_id):
            raise WU4Error("EDITOR_STATE_INVALID", "Editor state track identities do not match the source manifest.")
        self._validate_settings(state.get("album_overrides", {}), state["base_effects"], state["profile_id"])
        for track_id, patch in state.get("track_overrides", {}).items(): self._validate_settings(patch, state["base_effects"], state["profile_id"])
        for track_id, short in state["shorts"].items():
            track = track_by_id[track_id]
            if short.get("short_id") != stable_primary_short_id(state["project_id"], track_id) or short.get("track_id") != track_id or short.get("role") != "primary":
                raise WU4Error("EDITOR_STATE_INVALID", "Primary Short identity is immutable.")
            start, count = short.get("start_sample"), short.get("sample_count")
            if type(start) is not int or type(count) is not int or start < 0 or count <= 0 or start + count > track["normalized_sample_count"]:
                raise WU4Error("EDITOR_STATE_INVALID", "A Short range is outside its source track.")
            if short.get("origin") == "analyzer":
                raise WU4Error("EDITOR_STATE_INVALID", "Analyzer-origin Short ranges require a validated analyzer contract that is not configured.")
            short["review_required"] = count < MIN_APPROVABLE_SHORT_SAMPLES
            effective = self._effective(state, track_id, short)
            digest = approval_digest(track_fingerprint=track["audio_sha256"], short=short, effective_settings=effective, profile_id=state["profile_id"])
            if short["review_required"] and short.get("approval") is not None:
                raise WU4Error("SHORT_REVIEW_REQUIRED", "Tracks shorter than five seconds cannot be approved.")
            if short.get("approval") is not None and short["approval"].get("approved_digest") != digest:
                short["approval"] = None
        return state

    def _validate_settings(self, settings: Mapping[str, Any], base: Mapping[str, Any], profile_id: str) -> None:
        if set(settings) - {"effects", "treatment"}: raise WU4Error("EDITOR_STATE_INVALID", "An editor setting is unsupported.")
        if "effects" in settings: validate_effects(profile_id, deep_merge_settings(base, settings["effects"]))
        if "treatment" in settings: validate_treatment(settings["treatment"])

    def _effective(self, state: Mapping[str, Any], track_id: str, short: Mapping[str, Any]) -> dict[str, Any]:
        effects = copy.deepcopy(state["base_effects"])
        sources = {f"effects.{path}": "manifest" for path in self._leaf_paths(effects)}
        treatment = None
        for label, settings in (("album", state["album_overrides"]), ("track", state["track_overrides"].get(track_id, {})), ("short", short.get("settings", {}))):
            if "effects" in settings:
                effects = deep_merge_settings(effects, settings["effects"])
                for path in self._leaf_paths(settings["effects"]): sources[f"effects.{path}"] = label
            if "treatment" in settings:
                treatment = validate_treatment(settings["treatment"])
                for key in treatment: sources[f"treatment.{key}"] = label
        validate_effects(state["profile_id"], effects)
        result: dict[str, Any] = {"effects": effects, "provenance": sources}
        if treatment is not None: result["treatment"] = treatment
        return result

    @classmethod
    def _leaf_paths(cls, value: Mapping[str, Any], prefix: str = "") -> tuple[str, ...]:
        paths: list[str] = []
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(item, Mapping): paths.extend(cls._leaf_paths(item, path))
            else: paths.append(path)
        return tuple(paths)

    def _view(self, state: dict[str, Any], album: Mapping[str, Any]) -> dict[str, Any]:
        view = copy.deepcopy(state)
        tracks = {item["id"]: item for item in album["tracks"]}
        view["resolved"] = {}
        for track_id, short in view["shorts"].items():
            effective = self._effective(view, track_id, short)
            effective["approval_digest"] = approval_digest(track_fingerprint=tracks[track_id]["audio_sha256"], short=short, effective_settings=effective, profile_id=view["profile_id"])
            view["resolved"][track_id] = effective
        return view


__all__ = ["AlbumProjects", "EditorStates", "ProjectCatalogs"]
