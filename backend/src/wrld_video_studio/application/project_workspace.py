from __future__ import annotations

import copy
import hashlib
import math
import re
from typing import Any, Mapping
from uuid import uuid4

from wrld_video_studio.application.ports.wu4 import ProjectDocumentStorePort
from wrld_video_studio.application.creation_v4 import (
    canonical_visual_configuration,
    migrate_creation_state_v3_to_v4,
    visual_configuration_from_template,
    visual_configurations_equivalent,
)
from wrld_video_studio.domain.video_export import SAMPLE_RATE
from wrld_video_studio.domain.wu4 import (
    CREATION_STATE_VERSION,
    CREATION_STATE_V2_VERSION,
    CREATION_STATE_V3_VERSION,
    CREATION_STATE_V4_VERSION,
    DEFAULT_PREFERRED_SHORT_SECONDS,
    IMPORT_HANDOFF_V2_VERSION,
    MAX_PREFERRED_SHORT_SECONDS,
    MIN_APPROVABLE_SHORT_SAMPLES,
    MIN_PREFERRED_SHORT_SECONDS,
    PROJECT_PREFERENCES_VERSION,
    WU4Error,
)


_FLAT_EFFECT_KEYS = {
    "camera", "zoom", "bars", "barCount", "barOpacity", "progress",
    "tint", "tintIntensity", "positionX", "positionY",
}
_EFFECT_DEFAULTS: dict[str, Any] = {
    "camera": True,
    "zoom": 1.04,
    "bars": True,
    "barCount": 24,
    "barOpacity": 0.65,
    "progress": True,
    "tint": "#416E9D",
    "tintIntensity": 18,
    "positionX": 50,
    "positionY": 50,
}
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _effect_dialect(settings: Mapping[str, Any], short_id: str) -> tuple[str, dict[str, Any] | None]:
    if "effects" not in settings:
        return "flat", copy.deepcopy(_EFFECT_DEFAULTS)
    effects = settings["effects"]
    if not isinstance(effects, Mapping) or isinstance(effects, (list, tuple)):
        raise WU4Error(
            "CREATION_STATE_INVALID",
            "Short settings.effects must be a JSON object for Creation v2 migration.",
            {"short_id": short_id, "path": "settings.effects", "reason": "not_object"},
        )
    keys = set(effects)
    if not keys <= _FLAT_EFFECT_KEYS:
        return "historical", None
    if any(isinstance(value, (Mapping, list, tuple)) for value in effects.values()):
        return "historical", None

    merged = {**_EFFECT_DEFAULTS, **dict(effects)}

    def invalid(reason: str) -> None:
        raise WU4Error(
            "CREATION_STATE_INVALID",
            "Short settings.effects contains an invalid flat WU4 value.",
            {"short_id": short_id, "path": "settings.effects", "reason": reason},
        )

    for key in ("camera", "bars", "progress"):
        if type(merged[key]) is not bool:
            invalid(f"{key}_must_be_boolean")
    for key, minimum, maximum in (
        ("zoom", 1.0, 1.05),
        ("barOpacity", 0.1, 1.0),
        ("tintIntensity", 0.0, 60.0),
        ("positionX", 0.0, 100.0),
        ("positionY", 0.0, 100.0),
    ):
        value = merged[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
            invalid(f"{key}_out_of_range")
    if type(merged["barCount"]) is not int or not 8 <= merged["barCount"] <= 64:
        invalid("barCount_out_of_range")
    if not isinstance(merged["tint"], str) or _HEX_COLOR.fullmatch(merged["tint"]) is None:
        invalid("tint_invalid")
    return "flat", merged


def _template_id(project_id: str, short_id: str) -> str:
    source = f"{project_id}\0{short_id}\0{CREATION_STATE_V2_VERSION}".encode("utf-8")
    return f"visual-template-{hashlib.sha256(source).hexdigest()[:32]}"


def _migrated_template(project_id: str, short_id: str, effects: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "visual_template_id": _template_id(project_id, short_id),
        "label": f"Short visual {short_id}"[:128],
        "canvas": {"aspect_ratio": "9:16"},
        "background_image": None,
        "geometry": {
            "fit_mode": "contain",
            "focal_x": effects["positionX"] / 100,
            "focal_y": effects["positionY"] / 100,
        },
        "camera": {
            "mode": "bounded" if effects["camera"] else "static",
            "max_zoom": effects["zoom"],
        },
        "visualizer": {
            "enabled": effects["bars"],
            "bar_count": effects["barCount"],
            "opacity": effects["barOpacity"],
        },
        "progress": {"enabled": effects["progress"]},
        "color_treatment": {
            "mode": "custom",
            "hex": effects["tint"],
            "intensity": effects["tintIntensity"] / 100,
        },
    }


def migrate_creation_state_v1_to_v2(state: Mapping[str, Any]) -> dict[str, Any]:
    """Build the deterministic explicit-upgrade candidate without mutating v1."""
    if state.get("contract_version") != CREATION_STATE_VERSION:
        raise WU4Error("CREATION_STATE_INVALID", "Only Creation v1 can be upgraded to v2.")
    result = copy.deepcopy(dict(state))
    result.pop("issues", None)
    result["contract_version"] = CREATION_STATE_V2_VERSION
    result["visual_templates"] = []
    identifiers: set[str] = set()
    for album in result.get("albums", []):
        identifiers.add(str(album.get("album_plan_id")))
        identifiers.update(str(item.get("assignment_id")) for item in album.get("assignments", []))
        album["visual_template_id"] = None
    for single in result.get("singles", []):
        identifiers.add(str(single.get("single_id")))
        single["visual_template_id"] = None
    for short in result.get("shorts", []):
        short_id = str(short.get("short_id"))
        identifiers.add(short_id)
        short["visual_template_id"] = None
        settings = short.get("settings")
        if not isinstance(settings, Mapping):
            raise WU4Error("CREATION_STATE_INVALID", "Short settings must be a JSON object.", {"short_id": short_id, "path": "settings"})
        dialect, effects = _effect_dialect(settings, short_id)
        if dialect != "flat" or effects is None:
            continue
        template = _migrated_template(str(result.get("project_id")), short_id, effects)
        template_id = template["visual_template_id"]
        if template_id in identifiers:
            raise WU4Error(
                "CREATION_STATE_INVALID",
                "A deterministic visual-template identity collides with existing Creation work.",
                {"short_id": short_id, "visual_template_id": template_id},
            )
        identifiers.add(template_id)
        result["visual_templates"].append(template)
        short["visual_template_id"] = template_id
    return result


_FAMILY_SLOTS = ("album", "single", "short")
_FAMILY_MEMBER_FIELDS = {
    "album": "album_visual_template_id",
    "single": "single_visual_template_id",
    "short": "short_visual_template_id",
}
_FAMILY_ASPECTS = {"album": "16:9", "single": "16:9", "short": "9:16"}
_VISUAL_CREATION_VERSIONS = {CREATION_STATE_V2_VERSION, CREATION_STATE_V3_VERSION, CREATION_STATE_V4_VERSION}


def _v3_migration_id(project_id: str, template_id: str, role: str) -> str:
    source = f"{project_id}\0{template_id}\0{CREATION_STATE_V3_VERSION}\0{role}".encode("utf-8")
    prefix = "visual-template-family-" if role == "family" else "visual-template-"
    return f"{prefix}{hashlib.sha256(source).hexdigest()[:32]}"


def _document_identifiers(state: Mapping[str, Any]) -> set[str]:
    identifiers = {
        str(template["visual_template_id"])
        for template in state.get("visual_templates", [])
    }
    for album in state.get("albums", []):
        identifiers.add(str(album["album_plan_id"]))
        identifiers.update(str(item["assignment_id"]) for item in album.get("assignments", []))
    identifiers.update(str(item["single_id"]) for item in state.get("singles", []))
    identifiers.update(str(item["short_id"]) for item in state.get("shorts", []))
    return identifiers


def migrate_creation_state_v2_to_v3(state: Mapping[str, Any]) -> dict[str, Any]:
    """Build the deterministic explicit-upgrade candidate without mutating v2."""
    if state.get("contract_version") == CREATION_STATE_V3_VERSION:
        return copy.deepcopy(dict(state))
    if state.get("contract_version") != CREATION_STATE_V2_VERSION:
        raise WU4Error("CREATION_STATE_INVALID", "Only Creation v2 can be upgraded to v3.")

    result = copy.deepcopy(dict(state))
    result.pop("issues", None)
    result["contract_version"] = CREATION_STATE_V3_VERSION
    result["visual_template_families"] = []
    source_templates = copy.deepcopy(list(result.get("visual_templates", [])))
    identifiers = _document_identifiers(result)
    project_id = str(result.get("project_id"))
    album_consumers = {
        str(item["visual_template_id"])
        for item in result.get("albums", [])
        if item.get("visual_template_id") is not None
    }
    single_consumers = {
        str(item["visual_template_id"])
        for item in result.get("singles", [])
        if item.get("visual_template_id") is not None
    }
    generated_templates: list[dict[str, Any]] = []

    def reserve(identity: str, source_template_id: str, role: str) -> None:
        if identity in identifiers:
            raise WU4Error(
                "CREATION_STATE_INVALID",
                "A deterministic Creation v3 identity collides with existing work.",
                {
                    "source_visual_template_id": source_template_id,
                    "generated_identity": identity,
                    "role": role,
                },
            )
        identifiers.add(identity)

    for source in source_templates:
        source_id = str(source.get("visual_template_id"))
        aspect = source.get("canvas", {}).get("aspect_ratio")
        if aspect == "9:16":
            primary_slot = "short"
        elif aspect == "16:9":
            primary_slot = "single" if source_id in single_consumers else "album"
        else:
            raise WU4Error(
                "CREATION_STATE_INVALID",
                "Creation v2 contains a visual template with an invalid aspect ratio.",
                {"source_visual_template_id": source_id, "aspect_ratio": aspect},
            )

        family_id = _v3_migration_id(project_id, source_id, "family")
        reserve(family_id, source_id, "family")
        members: dict[str, str] = {}
        for slot in _FAMILY_SLOTS:
            if slot == primary_slot:
                member_id = source_id
            else:
                member_id = _v3_migration_id(project_id, source_id, slot)
                reserve(member_id, source_id, slot)
                member = copy.deepcopy(source)
                member["visual_template_id"] = member_id
                member["canvas"]["aspect_ratio"] = _FAMILY_ASPECTS[slot]
                generated_templates.append(member)
            members[_FAMILY_MEMBER_FIELDS[slot]] = member_id

        result["visual_template_families"].append(
            {
                "visual_template_family_id": family_id,
                "name": source["label"],
                "members": members,
            }
        )

        if primary_slot == "single" and source_id in album_consumers:
            album_member_id = members["album_visual_template_id"]
            for album in result.get("albums", []):
                if album.get("visual_template_id") == source_id:
                    album["visual_template_id"] = album_member_id

    result["visual_templates"].extend(generated_templates)
    return result


class ProjectPreferences:
    def __init__(self, catalogs: Any, inventories: Any, store: ProjectDocumentStorePort) -> None:
        self.catalogs, self.inventories, self.store = catalogs, inventories, store

    def get(self, project_id: str) -> dict[str, Any]:
        self.catalogs.resolve(project_id)
        try:
            return self.store.read(project_id)
        except WU4Error as error:
            if error.code != "PROJECT_DOCUMENT_NOT_FOUND":
                raise
        return self.store.create(project_id, self._initial(project_id))

    def put(self, project_id: str, expected_revision: int, save_id: str, state: Mapping[str, Any]) -> dict[str, Any]:
        self.catalogs.resolve(project_id)
        candidate = copy.deepcopy(dict(state))
        if candidate.get("contract_version") != PROJECT_PREFERENCES_VERSION or candidate.get("project_id") != project_id:
            raise WU4Error("PROJECT_PREFERENCES_INVALID", "Project preferences do not match the requested project.")
        candidate["save_id"] = save_id
        excluded = candidate.get("excluded_asset_ids")
        if not isinstance(excluded, list) or len(excluded) != len(set(excluded)):
            raise WU4Error("PROJECT_PREFERENCES_INVALID", "Excluded asset identities must be a unique list.")
        known = {item["asset_id"] for item in self.inventories.read(project_id)["assets"]}
        unknown = sorted(set(excluded) - known)
        if unknown:
            raise WU4Error("PROJECT_PREFERENCES_INVALID", "An excluded asset identity is not part of this project.", {"asset_ids": unknown})
        return self.store.update(project_id, expected_revision, candidate)

    @staticmethod
    def handoff(project_id: str, inventory_revision: int, preferences_revision: int) -> dict[str, Any]:
        return {
            "contract_version": IMPORT_HANDOFF_V2_VERSION,
            "project_id": project_id,
            "inventory_revision": inventory_revision,
            "preferences_revision": preferences_revision,
        }

    @staticmethod
    def _initial(project_id: str) -> dict[str, Any]:
        return {
            "contract_version": PROJECT_PREFERENCES_VERSION,
            "project_id": project_id,
            "revision": 1,
            "save_id": "initial",
            "excluded_asset_ids": [],
            "state_digest": "0" * 64,
        }


class CreationStates:
    def __init__(
        self,
        catalogs: Any,
        inventories: Any,
        store: ProjectDocumentStorePort,
        *,
        albums: Any | None = None,
        editors: Any | None = None,
        preferences: Any | None = None,
    ) -> None:
        self.catalogs, self.inventories, self.store = catalogs, inventories, store
        self.albums, self.editors, self.preferences = albums, editors, preferences

    def get(self, project_id: str) -> dict[str, Any]:
        catalog_entry, _root = self.catalogs.resolve(project_id)
        inventory = self.inventories.read(project_id)
        excluded_asset_ids = (
            set(self.preferences.get(project_id)["excluded_asset_ids"])
            if self.preferences is not None
            else set()
        )
        try:
            state = self.store.read(project_id)
        except WU4Error as error:
            if error.code != "PROJECT_DOCUMENT_NOT_FOUND":
                raise
            state = self.store.create(
                project_id,
                self._initial(
                    project_id,
                    inventory,
                    catalog_entry,
                    excluded_asset_ids,
                ),
            )
        state = self._reconcile_legacy_primary(
            project_id, state, inventory, catalog_entry, excluded_asset_ids
        )
        return self._view(state, inventory, excluded_asset_ids)

    def _reconcile_legacy_primary(
        self,
        project_id: str,
        state: Mapping[str, Any],
        inventory: Mapping[str, Any],
        catalog_entry: Mapping[str, Any],
        excluded_asset_ids: set[str],
    ) -> dict[str, Any]:
        legacy = self._legacy_primary_shorts(
            project_id, inventory, catalog_entry, excluded_asset_ids
        )
        existing_ids = {item["short_id"] for item in state["shorts"]}
        additions = [item for item in legacy if item["short_id"] not in existing_ids]
        if not additions:
            return copy.deepcopy(dict(state))
        candidate = copy.deepcopy(dict(state))
        self._extend_legacy_shorts(candidate, additions)
        candidate["save_id"] = f"reconcile-primary-{inventory['inventory_revision']}"
        try:
            return self.store.update(project_id, state["revision"], candidate)
        except WU4Error as error:
            if error.code != "REVISION_CONFLICT":
                raise
            latest = self.store.read(project_id)
            latest_ids = {item["short_id"] for item in latest["shorts"]}
            additions = [item for item in legacy if item["short_id"] not in latest_ids]
            if not additions:
                return latest
            retry = copy.deepcopy(latest)
            self._extend_legacy_shorts(retry, additions)
            retry["save_id"] = f"reconcile-primary-{inventory['inventory_revision']}"
            return self.store.update(project_id, latest["revision"], retry)

    @staticmethod
    def _extend_legacy_shorts(document: dict[str, Any], additions: list[dict[str, Any]]) -> None:
        if document.get("contract_version") not in _VISUAL_CREATION_VERSIONS:
            document["shorts"].extend(copy.deepcopy(additions))
            return
        if document.get("contract_version") == CREATION_STATE_V4_VERSION:
            for addition in copy.deepcopy(additions):
                dialect, effects = _effect_dialect(addition["settings"], addition["short_id"])
                if dialect != "flat" or effects is None:
                    raise WU4Error(
                        "CREATION_STATE_INVALID",
                        "A reconciled legacy Short has no complete authoritative visual settings for Creation v4.",
                        {
                            "target_kind": "short",
                            "target_id": addition["short_id"],
                            "reason": "authoritative_visual_configuration_missing",
                        },
                    )
                template = _migrated_template(document["project_id"], addition["short_id"], effects)
                addition["visual_configuration"] = visual_configuration_from_template(template)
                addition["source_visual_template_id"] = None
                document["shorts"].append(addition)
            return
        identifiers = {
            item["visual_template_id"] for item in document.get("visual_templates", [])
        }
        for addition in copy.deepcopy(additions):
            addition["visual_template_id"] = None
            dialect, effects = _effect_dialect(addition["settings"], addition["short_id"])
            if dialect == "flat" and effects is not None:
                template = _migrated_template(document["project_id"], addition["short_id"], effects)
                if template["visual_template_id"] in identifiers:
                    raise WU4Error("CREATION_STATE_INVALID", "A reconciled Short visual-template identity collides with existing work.")
                identifiers.add(template["visual_template_id"])
                document["visual_templates"].append(template)
                addition["visual_template_id"] = template["visual_template_id"]
            document["shorts"].append(addition)

    def put(self, project_id: str, expected_revision: int, save_id: str, state: Mapping[str, Any]) -> dict[str, Any]:
        self.catalogs.resolve(project_id)
        current = self.store.read(project_id)
        if current.get("revision") != expected_revision:
            raise WU4Error(
                "REVISION_CONFLICT",
                "Stored creation state changed before this save.",
                {"current_revision": current.get("revision")},
            )
        candidate = copy.deepcopy(dict(state))
        candidate.pop("issues", None)
        version = candidate.get("contract_version")
        current_version = current.get("contract_version")
        if version not in {CREATION_STATE_VERSION, CREATION_STATE_V2_VERSION, CREATION_STATE_V3_VERSION, CREATION_STATE_V4_VERSION} or candidate.get("project_id") != project_id:
            raise WU4Error("CREATION_STATE_INVALID", "Creation state does not match the requested project.")
        if current_version == CREATION_STATE_VERSION and version not in {CREATION_STATE_VERSION, CREATION_STATE_V2_VERSION}:
            raise WU4Error("CREATION_STATE_INVALID", "Creation v1 must be upgraded to v2 before v3.")
        if current_version == CREATION_STATE_V2_VERSION and version not in {CREATION_STATE_V2_VERSION, CREATION_STATE_V3_VERSION}:
            raise WU4Error("CREATION_STATE_INVALID", "Creation v2 cannot be downgraded to v1.")
        if current_version == CREATION_STATE_V3_VERSION and version not in {CREATION_STATE_V3_VERSION, CREATION_STATE_V4_VERSION}:
            raise WU4Error("CREATION_STATE_INVALID", "Creation v3 can only be preserved or upgraded to v4.")
        if current_version == CREATION_STATE_V4_VERSION and version != CREATION_STATE_V4_VERSION:
            raise WU4Error("CREATION_STATE_INVALID", "Creation v4 cannot be downgraded.")
        if current_version == CREATION_STATE_VERSION and version == CREATION_STATE_V2_VERSION:
            expected = migrate_creation_state_v1_to_v2(current)
            stable_keys = lambda value: {key: item for key, item in value.items() if key not in {"revision", "save_id", "state_digest"}}
            if stable_keys(candidate) != stable_keys(expected):
                raise WU4Error(
                    "CREATION_STATE_INVALID",
                    "The explicit Creation upgrade candidate does not match the deterministic v1-to-v2 migration.",
                )
        if current_version == CREATION_STATE_V2_VERSION and version == CREATION_STATE_V3_VERSION:
            expected = migrate_creation_state_v2_to_v3(current)
            stable_keys = lambda value: {key: item for key, item in value.items() if key not in {"revision", "save_id", "state_digest"}}
            if stable_keys(candidate) != stable_keys(expected):
                raise WU4Error(
                    "CREATION_STATE_INVALID",
                    "The explicit Creation upgrade candidate does not match the deterministic v2-to-v3 migration.",
                )
        if current_version == CREATION_STATE_V3_VERSION and version == CREATION_STATE_V4_VERSION:
            expected = migrate_creation_state_v3_to_v4(current)
            stable_keys = lambda value: {key: item for key, item in value.items() if key not in {"revision", "save_id", "state_digest"}}
            if stable_keys(candidate) != stable_keys(expected):
                raise WU4Error(
                    "CREATION_STATE_INVALID",
                    "The explicit Creation upgrade candidate does not match the deterministic v3-to-v4 migration.",
                )
        candidate["save_id"] = save_id
        inventory = self.inventories.read(project_id)
        excluded_asset_ids = (
            set(self.preferences.get(project_id)["excluded_asset_ids"])
            if self.preferences is not None
            else set()
        )
        self._validate(candidate, inventory, current, excluded_asset_ids)
        return self._view(self.store.update(project_id, expected_revision, candidate), inventory, excluded_asset_ids)

    def _initial(
        self,
        project_id: str,
        inventory: Mapping[str, Any],
        catalog_entry: Mapping[str, Any],
        excluded_asset_ids: set[str],
    ) -> dict[str, Any]:
        return {
            "contract_version": CREATION_STATE_VERSION,
            "project_id": project_id,
            "revision": 1,
            "save_id": "initial",
            "preferred_short_duration_seconds": DEFAULT_PREFERRED_SHORT_SECONDS,
            "albums": [],
            "singles": [
                {
                    "single_id": f"single-{uuid4()}",
                    "asset_id": asset["asset_id"],
                    "expected_sha256": asset["sha256"],
                    "status": "active",
                    "customized": False,
                    "approved": False,
                    "settings": {},
                }
                for asset in inventory["assets"]
                if asset.get("kind") == "audio"
                and asset.get("presence") == "present"
                and isinstance(asset.get("sha256"), str)
                and len(asset["sha256"]) == 64
                and asset.get("asset_id") not in excluded_asset_ids
            ],
            "shorts": self._legacy_primary_shorts(
                project_id, inventory, catalog_entry, excluded_asset_ids
            ),
            "state_digest": "0" * 64,
        }

    def _legacy_primary_shorts(
        self,
        project_id: str,
        inventory: Mapping[str, Any],
        catalog_entry: Mapping[str, Any],
        excluded_asset_ids: set[str],
    ) -> list[dict[str, Any]]:
        """Carry Phase 1 primary Shorts into the additive Creation document.

        Manifestless projects have no earlier editor state.  For enriched projects,
        the existing editor service remains the authority for stable primary IDs,
        ranges, settings, and approvals; this one-time initialization only changes
        their storage shape.
        """
        enrichment = catalog_entry.get("enrichment")
        if (
            self.albums is None
            or self.editors is None
            or not isinstance(enrichment, Mapping)
            or enrichment.get("status") != "recognized"
        ):
            return []
        album = self.albums.read(project_id)
        editor = self.editors.get(project_id)
        assets_by_path = {
            item["relative_path"]: item
            for item in inventory["assets"]
            if item.get("kind") == "audio" and item.get("sha256")
        }
        migrated: list[dict[str, Any]] = []
        for track in album["tracks"]:
            asset = assets_by_path.get(track["audio"])
            short = editor["shorts"].get(track["id"])
            if (
                asset is None
                or short is None
                or asset.get("asset_id") in excluded_asset_ids
            ):
                continue
            migrated.append(
                {
                    "short_id": short["short_id"],
                    "asset_id": asset["asset_id"],
                    "expected_sha256": asset["sha256"],
                    "status": "active",
                    "start_sample": short["start_sample"],
                    "sample_count": short["sample_count"],
                    "origin": (
                        "primary_fallback"
                        if short["origin"] == "fallback"
                        else "manual"
                    ),
                    "review_required": short["review_required"],
                    "customized": (
                        short["origin"] != "fallback" or bool(short["settings"])
                    ),
                    "approved": short["approval"] is not None,
                    "settings": copy.deepcopy(short["settings"]),
                }
            )
        return migrated

    def _validate(
        self,
        state: Mapping[str, Any],
        inventory: Mapping[str, Any],
        prior: Mapping[str, Any] | None = None,
        excluded_asset_ids: set[str] | None = None,
    ) -> None:
        preferred = state.get("preferred_short_duration_seconds")
        if type(preferred) is not int or not MIN_PREFERRED_SHORT_SECONDS <= preferred <= MAX_PREFERRED_SHORT_SECONDS:
            raise WU4Error("CREATION_STATE_INVALID", "Preferred Short duration must be an integer from 20 through 120 seconds.")
        assets = {item["asset_id"]: item for item in inventory["assets"]}
        identifiers: set[str] = set()

        def unique(value: Any, label: str) -> None:
            if not isinstance(value, str) or not value or value in identifiers:
                raise WU4Error("CREATION_STATE_INVALID", f"{label} identities must be non-empty and unique.")
            identifiers.add(value)

        def source(reference: Mapping[str, Any]) -> Mapping[str, Any]:
            asset = assets.get(reference.get("asset_id"))
            if asset is None or asset.get("kind") != "audio":
                raise WU4Error("CREATION_STATE_INVALID", "Creation drafts may reference only inventoried audio assets.")
            expected = reference.get("expected_sha256")
            if not isinstance(expected, str) or len(expected) != 64:
                raise WU4Error("CREATION_STATE_INVALID", "Creation dependencies require a strong source fingerprint.")
            if asset.get("presence") != "present" or asset.get("sha256") != expected:
                raise WU4Error(
                    "SOURCE_CHANGED",
                    "A Creation dependency is missing or changed and must be reviewed before saving.",
                    {"asset_id": reference.get("asset_id")},
                )
            return asset

        templates: dict[str, Mapping[str, Any]] = {}
        if state.get("contract_version") in _VISUAL_CREATION_VERSIONS:
            for template in state.get("visual_templates", []):
                unique(template.get("visual_template_id"), "Visual template")
                templates[str(template.get("visual_template_id"))] = template

        if state.get("contract_version") in {CREATION_STATE_V3_VERSION, CREATION_STATE_V4_VERSION}:
            member_templates: set[str] = set()
            for family in state.get("visual_template_families", []):
                family_id = family.get("visual_template_family_id")
                unique(family_id, "Visual template family")
                name = family.get("name")
                if not isinstance(name, str) or not 1 <= len(name) <= 128:
                    raise WU4Error("CREATION_STATE_INVALID", "Visual template family names must contain 1 through 128 characters.")
                members = family.get("members")
                if not isinstance(members, Mapping):
                    raise WU4Error("CREATION_STATE_INVALID", "Visual template family members are invalid.", {"visual_template_family_id": family_id})
                resolved: list[str] = []
                for slot in _FAMILY_SLOTS:
                    field = _FAMILY_MEMBER_FIELDS[slot]
                    member_id = members.get(field)
                    template = templates.get(str(member_id))
                    if template is None:
                        raise WU4Error(
                            "CREATION_STATE_INVALID",
                            "A visual template family references an unknown member.",
                            {"visual_template_family_id": family_id, "member": field, "visual_template_id": member_id},
                        )
                    if template.get("canvas", {}).get("aspect_ratio") != _FAMILY_ASPECTS[slot]:
                        raise WU4Error(
                            "CREATION_STATE_INVALID",
                            "A visual template family member has an incompatible aspect ratio.",
                            {"visual_template_family_id": family_id, "member": field, "visual_template_id": member_id},
                        )
                    resolved.append(str(member_id))
                if len(set(resolved)) != len(resolved):
                    raise WU4Error(
                        "CREATION_STATE_INVALID",
                        "A concrete visual template cannot occupy multiple family slots.",
                        {"visual_template_family_id": family_id},
                    )
                duplicate = member_templates.intersection(resolved)
                if duplicate:
                    raise WU4Error(
                        "CREATION_STATE_INVALID",
                        "A concrete visual template cannot belong to multiple families.",
                        {"visual_template_family_id": family_id, "visual_template_id": sorted(duplicate)[0]},
                    )
                member_templates.update(resolved)

        target_refs: set[tuple[str, str, str]] = set()
        v4_targets: list[tuple[str, str, Mapping[str, Any]]] = []

        def validate_target_visual(kind: str, identity: Any, target: Mapping[str, Any], aspect_ratio: str) -> None:
            if state.get("contract_version") not in _VISUAL_CREATION_VERSIONS:
                return
            if state.get("contract_version") == CREATION_STATE_V4_VERSION:
                configuration = canonical_visual_configuration(target.get("visual_configuration"))
                if configuration is None:
                    raise WU4Error(
                        "CREATION_STATE_INVALID",
                        "A Creation v4 target requires a complete supported visual configuration.",
                        {"target_kind": kind, "target_id": identity},
                    )
                if configuration["canvas"]["aspect_ratio"] != aspect_ratio:
                    raise WU4Error(
                        "CREATION_STATE_INVALID",
                        "A composition-owned visual configuration has an incompatible aspect ratio.",
                        {"target_kind": kind, "target_id": identity},
                    )
                provenance = target.get("source_visual_template_id")
                if provenance is not None and (not isinstance(provenance, str) or not provenance):
                    raise WU4Error(
                        "CREATION_STATE_INVALID",
                        "Visual-template provenance must be a stable identifier or null.",
                        {"target_kind": kind, "target_id": identity},
                    )
                v4_targets.append((kind, str(identity), target))
                return
            reference = target.get("visual_template_id")
            if reference is None:
                return
            template = templates.get(reference)
            if template is None:
                raise WU4Error("CREATION_STATE_INVALID", "A Creation target references an unknown visual template.", {"visual_template_id": reference})
            if template.get("canvas", {}).get("aspect_ratio") != aspect_ratio:
                raise WU4Error("CREATION_STATE_INVALID", "A visual template aspect ratio is incompatible with its target.", {"visual_template_id": reference, "target_id": identity})
            target_refs.add((kind, str(identity), str(reference)))

        for album in state.get("albums", []):
            unique(album.get("album_plan_id"), "Album plan")
            validate_target_visual("album", album.get("album_plan_id"), album, "16:9")
            for assignment in album.get("assignments", []):
                unique(assignment.get("assignment_id"), "Album assignment")
                source(assignment)
        for single in state.get("singles", []):
            unique(single.get("single_id"), "Single draft")
            source(single)
            validate_target_visual("single", single.get("single_id"), single, "16:9")
        for short in state.get("shorts", []):
            unique(short.get("short_id"), "Short draft")
            asset = source(short)
            validate_target_visual("short", short.get("short_id"), short, "9:16")
            if short.get("origin") == "analyzer":
                raise WU4Error("ANALYZER_UNAVAILABLE", "Analyzer-origin Short ranges require a validated analyzer observation contract.")
            start, count = short.get("start_sample"), short.get("sample_count")
            if type(start) is not int or type(count) is not int or start < 0 or count <= 0:
                raise WU4Error("CREATION_STATE_INVALID", "Short ranges must use positive normalized sample frames.")
            duration = asset.get("media", {}).get("duration_seconds")
            total = round(float(duration) * SAMPLE_RATE) if isinstance(duration, (int, float)) and duration > 0 else None
            if total is not None and start + count > total:
                raise WU4Error("CREATION_STATE_INVALID", "A Short range extends beyond its source recording.")
            too_short = count < MIN_APPROVABLE_SHORT_SAMPLES
            if too_short and total is not None and total >= MIN_APPROVABLE_SHORT_SAMPLES:
                raise WU4Error("CREATION_STATE_INVALID", "Short clips must be at least five seconds.")
            if short.get("approved") and (too_short or short.get("review_required")):
                raise WU4Error("SHORT_REVIEW_REQUIRED", "A Short requiring review cannot be approved.")
            if short.get("origin") == "manual_required" and not short.get("review_required"):
                raise WU4Error("CREATION_STATE_INVALID", "A Short awaiting manual selection must require review.")

        if state.get("contract_version") in _VISUAL_CREATION_VERSIONS:
            prior_templates = {
                item["visual_template_id"]: item
                for item in (prior or {}).get("visual_templates", [])
                if isinstance(item, Mapping) and isinstance(item.get("visual_template_id"), str)
            }
            is_v3_upgrade = (
                (prior or {}).get("contract_version") == CREATION_STATE_V2_VERSION
                and state.get("contract_version") == CREATION_STATE_V3_VERSION
            )
            is_v4_upgrade = (
                (prior or {}).get("contract_version") == CREATION_STATE_V3_VERSION
                and state.get("contract_version") == CREATION_STATE_V4_VERSION
            )
            prior_refs: set[tuple[str, str, str]] = set()
            prior_version = (prior or {}).get("contract_version")
            if prior_version in {CREATION_STATE_V2_VERSION, CREATION_STATE_V3_VERSION} and state.get("contract_version") != CREATION_STATE_V4_VERSION:
                for kind, collection, key in (
                    ("album", prior.get("albums", []), "album_plan_id"),
                    ("single", prior.get("singles", []), "single_id"),
                    ("short", prior.get("shorts", []), "short_id"),
                ):
                    prior_refs.update(
                        (kind, str(item[key]), str(item["visual_template_id"]))
                        for item in collection
                        if item.get("visual_template_id") is not None
                    )
                def pixels(template: Mapping[str, Any] | None) -> dict[str, Any] | None:
                    if template is None:
                        return None
                    return {
                        key: copy.deepcopy(value)
                        for key, value in template.items()
                        if key not in {"visual_template_id", "label"}
                    }

                for collection_name, key in (("singles", "single_id"), ("shorts", "short_id")):
                    prior_targets = {
                        str(item[key]): item
                        for item in prior.get(collection_name, [])
                    }
                    for item in state.get(collection_name, []):
                        previous = prior_targets.get(str(item[key]))
                        if previous is None or not item.get("approved"):
                            continue
                        old_ref = previous.get("visual_template_id")
                        new_ref = item.get("visual_template_id")
                        if old_ref == new_ref:
                            changed = new_ref is not None and pixels(prior_templates.get(str(new_ref))) != pixels(templates.get(str(new_ref)))
                        else:
                            # Customize is the sole reference-change exception: a newly
                            # created byte-equivalent copy may preserve approval.
                            changed = not (
                                old_ref is not None
                                and new_ref is not None
                                and str(new_ref) not in prior_templates
                                and pixels(prior_templates.get(str(old_ref))) == pixels(templates.get(str(new_ref)))
                            )
                        if changed:
                            raise WU4Error(
                                "CREATION_STATE_INVALID",
                                "Pixel-affecting visual changes must invalidate linked Single and Short approvals.",
                                {"target_id": item[key], "visual_template_id": new_ref},
                            )
            assets_by_id = {item["asset_id"]: item for item in inventory["assets"]}
            excluded = excluded_asset_ids or set()

            def validate_background(background: Mapping[str, Any]) -> None:
                asset_id = background.get("asset_id")
                asset = assets_by_id.get(asset_id)
                if asset_id in excluded:
                    raise WU4Error("CREATION_STATE_INVALID", "An excluded image cannot be selected as a new visual dependency.", {"asset_id": asset_id})
                if asset is None or asset.get("kind") != "image" or asset.get("presence") != "present":
                    raise WU4Error("CREATION_STATE_INVALID", "A new visual dependency must reference a present project image.", {"asset_id": asset_id})
                if asset.get("capabilities", {}).get("inspection", {}).get("status") != "supported":
                    raise WU4Error("CREATION_STATE_INVALID", "The selected image is not supported for safe inspection.", {"asset_id": asset_id})
                if asset.get("sha256") != background.get("expected_sha256"):
                    raise WU4Error("SOURCE_CHANGED", "The selected image fingerprint does not match the current inventory.", {"asset_id": asset_id})
                verified_asset, _path, digest = self.inventories.verify_asset(str(state.get("project_id")), str(asset_id))
                if verified_asset.get("kind") != "image" or digest != background.get("expected_sha256"):
                    raise WU4Error("SOURCE_CHANGED", "The selected image changed during dependency verification.", {"asset_id": asset_id})

            if state.get("contract_version") == CREATION_STATE_V4_VERSION:
                for collection_name, key in (("singles", "single_id"), ("shorts", "short_id")):
                    prior_targets = {
                        str(item[key]): item
                        for item in (prior or {}).get(collection_name, [])
                    }
                    for item in state.get(collection_name, []):
                        previous = prior_targets.get(str(item[key]))
                        if previous is None or not item.get("approved"):
                            continue
                        if prior_version == CREATION_STATE_V4_VERSION:
                            previous_configuration = previous.get("visual_configuration")
                        elif is_v4_upgrade:
                            reference = previous.get("visual_template_id")
                            previous_configuration = prior_templates.get(str(reference)) if reference is not None else previous.get("visual_configuration")
                        else:
                            previous_configuration = None
                        if not visual_configurations_equivalent(previous_configuration, item.get("visual_configuration")):
                            raise WU4Error(
                                "CREATION_STATE_INVALID",
                                "Pixel-affecting composition changes must invalidate the Single or Short approval.",
                                {"target_id": item[key], "source_visual_template_id": item.get("source_visual_template_id")},
                            )

                if not is_v4_upgrade:
                    prior_targets_by_kind = {
                        (kind, str(item[key])): item
                        for kind, collection, key in (
                            ("album", (prior or {}).get("albums", []), "album_plan_id"),
                            ("single", (prior or {}).get("singles", []), "single_id"),
                            ("short", (prior or {}).get("shorts", []), "short_id"),
                        )
                        for item in collection
                    }
                    for kind, identity, target in v4_targets:
                        background = target["visual_configuration"].get("background_image")
                        if background is None:
                            continue
                        previous = prior_targets_by_kind.get((kind, identity))
                        prior_background = None if previous is None else previous.get("visual_configuration", {}).get("background_image")
                        if previous is None or prior_background != background:
                            validate_background(background)
                    for template_id, template in templates.items():
                        background = template.get("background_image")
                        if background is None:
                            continue
                        prior_background = prior_templates.get(template_id, {}).get("background_image")
                        if template_id not in prior_templates or prior_background != background:
                            validate_background(background)
                return

            for template_id, template in templates.items():
                background = template.get("background_image")
                if background is None:
                    continue
                if is_v3_upgrade:
                    # The exact deterministic candidate was checked before validation.
                    # Its generated members preserve existing v2 dependencies; migration
                    # must not reinterpret them as newly selected image relationships.
                    continue
                prior_background = prior_templates.get(template_id, {}).get("background_image")
                new_reference = any(item[2] == template_id and item not in prior_refs for item in target_refs)
                requires_fresh_validation = prior_background != background or new_reference
                if not requires_fresh_validation:
                    continue
                validate_background(background)

    @staticmethod
    def _view(
        state: Mapping[str, Any],
        inventory: Mapping[str, Any],
        excluded_asset_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        result = copy.deepcopy(dict(state))
        assets = {item["asset_id"]: item for item in inventory["assets"]}
        issues: list[dict[str, Any]] = []
        references: list[tuple[str, Mapping[str, Any]]] = []
        for album in result["albums"]:
            references.extend((assignment["assignment_id"], assignment) for assignment in album["assignments"])
        references.extend((item["single_id"], item) for item in result["singles"])
        references.extend((item["short_id"], item) for item in result["shorts"])
        for identity, reference in references:
            asset = assets.get(reference["asset_id"])
            if asset is None or asset.get("presence") != "present":
                issues.append({
                    "draft_id": identity,
                    "asset_id": str(reference["asset_id"]),
                    "relative_path": "" if asset is None else str(asset.get("relative_path", "")),
                    "code": "SOURCE_MISSING",
                })
            elif asset.get("sha256") != reference["expected_sha256"]:
                issues.append({
                    "draft_id": identity,
                    "asset_id": str(reference["asset_id"]),
                    "relative_path": str(asset.get("relative_path", "")),
                    "code": "SOURCE_CHANGED",
                })
        if result.get("contract_version") in _VISUAL_CREATION_VERSIONS:
            excluded = excluded_asset_ids or set()
            def append_visual_issue(background: Any, template_id: Any, targets: list[dict[str, str]]) -> None:
                code = None
                asset = None
                if background is None:
                    code = "VISUAL_SOURCE_REQUIRED"
                else:
                    asset = assets.get(background["asset_id"])
                    if asset is None or asset.get("presence") != "present":
                        code = "VISUAL_SOURCE_MISSING"
                    elif asset.get("sha256") != background.get("expected_sha256"):
                        code = "VISUAL_SOURCE_CHANGED"
                    elif background["asset_id"] in excluded:
                        code = "VISUAL_SOURCE_EXCLUDED"
                    elif asset.get("capabilities", {}).get("inspection", {}).get("status") != "supported":
                        code = "VISUAL_SOURCE_UNSUPPORTED"
                if code is not None:
                    issues.append({
                        "code": code,
                        "visual_template_id": template_id,
                        "asset_id": None if background is None else background["asset_id"],
                        "relative_path": None if asset is None else asset.get("relative_path"),
                        "expected_sha256": None if background is None else background.get("expected_sha256"),
                        "observed_sha256": None if asset is None else asset.get("sha256"),
                        "affected_targets": targets,
                    })

            if result.get("contract_version") == CREATION_STATE_V4_VERSION:
                for kind, collection, key in (
                    ("album", result["albums"], "album_plan_id"),
                    ("single", result["singles"], "single_id"),
                    ("short", result["shorts"], "short_id"),
                ):
                    for item in collection:
                        append_visual_issue(
                            item["visual_configuration"].get("background_image"),
                            item.get("source_visual_template_id"),
                            [{"kind": kind, "id": str(item[key]), "status": str(item["status"])}],
                        )
            else:
                affected: dict[str, list[dict[str, str]]] = {}
                for kind, collection, key in (
                    ("album", result["albums"], "album_plan_id"),
                    ("single", result["singles"], "single_id"),
                    ("short", result["shorts"], "short_id"),
                ):
                    for item in collection:
                        template_id = item.get("visual_template_id")
                        if template_id is not None:
                            affected.setdefault(template_id, []).append({"kind": kind, "id": str(item[key]), "status": str(item["status"])})
                for template in result.get("visual_templates", []):
                    template_id = template["visual_template_id"]
                    targets = affected.get(template_id, [])
                    if targets:
                        append_visual_issue(template.get("background_image"), template_id, targets)
            for short in result["shorts"]:
                settings = short.get("settings", {})
                unmapped = "treatment" in settings
                try:
                    dialect, _effects = _effect_dialect(settings, short["short_id"])
                    unmapped = unmapped or dialect == "historical"
                except WU4Error:
                    unmapped = True
                if unmapped:
                    issues.append({
                        "code": "LEGACY_VISUAL_SETTINGS_UNMAPPED",
                        "visual_template_id": (
                            short.get("source_visual_template_id")
                            if result.get("contract_version") == CREATION_STATE_V4_VERSION
                            else short.get("visual_template_id")
                        ),
                        "asset_id": None,
                        "relative_path": None,
                        "expected_sha256": None,
                        "observed_sha256": None,
                        "affected_targets": [{"kind": "short", "id": short["short_id"], "status": short["status"]}],
                    })
        result["issues"] = issues
        return result


__all__ = [
    "CreationStates",
    "ProjectPreferences",
    "migrate_creation_state_v1_to_v2",
    "migrate_creation_state_v2_to_v3",
    "migrate_creation_state_v3_to_v4",
]
