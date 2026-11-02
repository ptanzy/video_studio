from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping

from wrld_video_studio.domain.canonical_json import canonical_sha256
from wrld_video_studio.domain.wu4 import CREATION_STATE_V3_VERSION, CREATION_STATE_V4_VERSION, WU4Error


VISUAL_CONFIGURATION_FIELDS = (
    "canvas",
    "background_image",
    "geometry",
    "camera",
    "visualizer",
    "progress",
    "color_treatment",
)
_VISUAL_CONFIGURATION_FIELD_SET = frozenset(VISUAL_CONFIGURATION_FIELDS)
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _finite_number(value: Any, minimum: float, maximum: float) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum


def canonical_visual_configuration(value: Any) -> dict[str, Any] | None:
    """Return a strict, detached visual configuration or None when it is unproven.

    This intentionally rejects unknown fields instead of treating a partial or future
    visual dialect as equivalent to the current contract.
    """

    if not isinstance(value, Mapping):
        return None
    keys = set(value)
    if keys == _VISUAL_CONFIGURATION_FIELD_SET:
        visual_value = value
    elif keys == _VISUAL_CONFIGURATION_FIELD_SET | {"visual_template_id", "label"}:
        visual_value = {field: value[field] for field in VISUAL_CONFIGURATION_FIELDS}
    else:
        return None
    canvas = visual_value.get("canvas")
    background = visual_value.get("background_image")
    geometry = visual_value.get("geometry")
    camera = visual_value.get("camera")
    visualizer = visual_value.get("visualizer")
    progress = visual_value.get("progress")
    treatment = visual_value.get("color_treatment")
    if not isinstance(canvas, Mapping) or set(canvas) != {"aspect_ratio"} or canvas.get("aspect_ratio") not in {"16:9", "9:16"}:
        return None
    if background is not None:
        if not isinstance(background, Mapping) or set(background) != {"asset_id", "expected_sha256"}:
            return None
        if not isinstance(background.get("asset_id"), str) or _OPAQUE_ID.fullmatch(background["asset_id"]) is None:
            return None
        fingerprint = background.get("expected_sha256")
        if not isinstance(fingerprint, str) or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
            return None
    if (
        not isinstance(geometry, Mapping)
        or set(geometry) != {"fit_mode", "focal_x", "focal_y"}
        or geometry.get("fit_mode") not in {"contain", "cover"}
        or not _finite_number(geometry.get("focal_x"), 0, 1)
        or not _finite_number(geometry.get("focal_y"), 0, 1)
    ):
        return None
    if (
        not isinstance(camera, Mapping)
        or set(camera) != {"mode", "max_zoom"}
        or camera.get("mode") not in {"static", "bounded"}
        or not _finite_number(camera.get("max_zoom"), 1, 1.05)
    ):
        return None
    if (
        not isinstance(visualizer, Mapping)
        or set(visualizer) != {"enabled", "bar_count", "opacity"}
        or type(visualizer.get("enabled")) is not bool
        or type(visualizer.get("bar_count")) is not int
        or not 8 <= visualizer["bar_count"] <= 64
        or not _finite_number(visualizer.get("opacity"), 0.1, 1)
    ):
        return None
    if not isinstance(progress, Mapping) or set(progress) != {"enabled"} or type(progress.get("enabled")) is not bool:
        return None
    if not isinstance(treatment, Mapping):
        return None
    if treatment.get("mode") == "none":
        if set(treatment) != {"mode"}:
            return None
    elif treatment.get("mode") == "custom":
        if (
            set(treatment) != {"mode", "hex", "intensity"}
            or not isinstance(treatment.get("hex"), str)
            or _HEX_COLOR.fullmatch(treatment["hex"]) is None
            or not _finite_number(treatment.get("intensity"), 0, 0.6)
        ):
            return None
    else:
        return None
    return copy.deepcopy({field: visual_value[field] for field in VISUAL_CONFIGURATION_FIELDS})


def visual_configuration_from_template(template: Mapping[str, Any]) -> dict[str, Any]:
    configuration = canonical_visual_configuration(template)
    if configuration is None:
        raise WU4Error(
            "CREATION_STATE_INVALID",
            "A visual template does not contain a complete supported visual configuration.",
            {"visual_template_id": template.get("visual_template_id")},
        )
    return configuration


def visual_configurations_equivalent(left: Any, right: Any) -> bool:
    left_configuration = canonical_visual_configuration(left)
    right_configuration = canonical_visual_configuration(right)
    if left_configuration is None or right_configuration is None:
        return False
    return canonical_sha256(left_configuration) == canonical_sha256(right_configuration)


def visual_configuration_digest(value: Any) -> str | None:
    configuration = canonical_visual_configuration(value)
    return None if configuration is None else canonical_sha256(configuration)


_TARGET_COLLECTIONS = (
    ("album", "albums", "album_plan_id"),
    ("single", "singles", "single_id"),
    ("short", "shorts", "short_id"),
)


def migrate_creation_state_v3_to_v4(state: Mapping[str, Any]) -> dict[str, Any]:
    """Build the deterministic explicit-upgrade candidate without mutating v3."""

    if state.get("contract_version") == CREATION_STATE_V4_VERSION:
        return copy.deepcopy(dict(state))
    if state.get("contract_version") != CREATION_STATE_V3_VERSION:
        raise WU4Error("CREATION_STATE_INVALID", "Only Creation v3 can be upgraded to v4.")

    result = copy.deepcopy(dict(state))
    result.pop("issues", None)
    templates = {
        str(template.get("visual_template_id")): template
        for template in result.get("visual_templates", [])
        if isinstance(template, Mapping) and isinstance(template.get("visual_template_id"), str)
    }
    for kind, collection_name, identity_field in _TARGET_COLLECTIONS:
        for target in result.get(collection_name, []):
            identity = target.get(identity_field)
            reference = target.get("visual_template_id")
            if reference is not None:
                template = templates.get(str(reference))
                if template is None:
                    raise WU4Error(
                        "CREATION_STATE_INVALID",
                        "A Creation v3 target has a dangling visual-template reference and cannot be migrated losslessly.",
                        {
                            "target_kind": kind,
                            "target_id": identity,
                            "visual_template_id": reference,
                            "reason": "dangling_visual_template_reference",
                        },
                    )
                configuration = visual_configuration_from_template(template)
                provenance: str | None = str(reference)
            else:
                configuration = canonical_visual_configuration(target.get("visual_configuration"))
                if configuration is None:
                    raise WU4Error(
                        "CREATION_STATE_INVALID",
                        "A Creation v3 target has no resolvable authoritative visual settings and cannot be migrated losslessly.",
                        {
                            "target_kind": kind,
                            "target_id": identity,
                            "visual_template_id": None,
                            "reason": "authoritative_visual_configuration_missing",
                        },
                    )
                provenance = None
            target.pop("visual_template_id", None)
            target["visual_configuration"] = configuration
            target["source_visual_template_id"] = provenance
    result["contract_version"] = CREATION_STATE_V4_VERSION
    return result


@dataclass(frozen=True, slots=True)
class TemplateAssociation:
    target_kind: str
    target_id: str
    status: str


@dataclass(frozen=True, slots=True)
class LegacyTemplateCandidate:
    visual_template_id: str
    classification: str
    reason: str
    family_member: bool
    standalone: bool
    likely_generated: bool
    unreferenced: bool
    active_compositions: tuple[TemplateAssociation, ...]
    archived_compositions: tuple[TemplateAssociation, ...]
    provenance_only_references: tuple[TemplateAssociation, ...]
    exact_equivalence_group: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LegacyTemplateCleanupPlan:
    source_revision: int
    source_fingerprint: str
    candidates: tuple[LegacyTemplateCandidate, ...]
    retained_template_ids: tuple[str, ...]
    total_templates_before: int
    total_templates_after: int
    family_member_count: int
    standalone_count: int
    active_reference_count: int
    archived_reference_count: int
    provenance_only_reference_count: int
    unreferenced_count: int


def _cleanup_fingerprint(state: Mapping[str, Any]) -> str:
    return canonical_sha256({key: copy.deepcopy(value) for key, value in state.items() if key != "issues"})


def _generated_v2_template_id(project_id: str, short_id: str) -> str:
    import hashlib

    source = f"{project_id}\0{short_id}\0wrld-creation-state/2.0".encode("utf-8")
    return f"visual-template-{hashlib.sha256(source).hexdigest()[:32]}"


def analyze_legacy_visual_templates(state: Mapping[str, Any]) -> LegacyTemplateCleanupPlan:
    if state.get("contract_version") != CREATION_STATE_V4_VERSION:
        raise WU4Error("CREATION_STATE_INVALID", "Legacy template cleanup analysis requires Creation v4.")

    templates = list(state.get("visual_templates", []))
    family_members = {
        str(template_id)
        for family in state.get("visual_template_families", [])
        for template_id in family.get("members", {}).values()
    }
    associations: dict[str, list[TemplateAssociation]] = {}
    short_by_id: dict[str, Mapping[str, Any]] = {}
    for kind, collection_name, identity_field in _TARGET_COLLECTIONS:
        for target in state.get(collection_name, []):
            identity = str(target.get(identity_field))
            if kind == "short":
                short_by_id[identity] = target
            provenance = target.get("source_visual_template_id")
            if isinstance(provenance, str):
                associations.setdefault(provenance, []).append(
                    TemplateAssociation(kind, identity, str(target.get("status")))
                )

    equivalence: dict[str, list[str]] = {}
    for template in templates:
        template_id = str(template.get("visual_template_id"))
        digest = visual_configuration_digest(template)
        if digest is not None:
            equivalence.setdefault(digest, []).append(template_id)

    candidates: list[LegacyTemplateCandidate] = []
    project_id = str(state.get("project_id"))
    for template in templates:
        template_id = str(template.get("visual_template_id"))
        linked = tuple(associations.get(template_id, ()))
        active = tuple(item for item in linked if item.status == "active")
        archived = tuple(item for item in linked if item.status == "archived")
        digest = visual_configuration_digest(template)
        group = tuple(equivalence.get(digest, ())) if digest is not None else ()

        verified_generated_short: Mapping[str, Any] | None = None
        for short_id, short in short_by_id.items():
            if (
                template_id == _generated_v2_template_id(project_id, short_id)
                and template.get("label") == f"Short visual {short_id}"[:128]
            ):
                verified_generated_short = short
                break

        if template_id in family_members:
            classification = "RETAIN"
            reason = "Family members are protected."
        elif (
            verified_generated_short is not None
            and verified_generated_short.get("source_visual_template_id") == template_id
            and linked
            and all(
            visual_configurations_equivalent(template, target.get("visual_configuration"))
            for kind, collection_name, identity_field in _TARGET_COLLECTIONS
            for target in state.get(collection_name, [])
            if target.get("source_visual_template_id") == template_id
            )
        ):
            classification = "PROVEN_DISPOSABLE"
            reason = "The stable v2 migration identity, exact migration label, provenance, and owned visual settings all match."
        elif verified_generated_short is not None or str(template.get("label", "")).startswith("Short visual short-") or len(group) > 1:
            classification = "REVIEW_REQUIRED"
            reason = "The template may be generated or redundant, but safe disposal is not fully proven."
        else:
            classification = "RETAIN"
            reason = "The template is unique, intentional, or of uncertain origin."

        candidates.append(
            LegacyTemplateCandidate(
                visual_template_id=template_id,
                classification=classification,
                reason=reason,
                family_member=template_id in family_members,
                standalone=template_id not in family_members,
                likely_generated=verified_generated_short is not None or str(template.get("label", "")).startswith("Short visual short-"),
                unreferenced=not linked,
                active_compositions=active,
                archived_compositions=archived,
                provenance_only_references=linked,
                exact_equivalence_group=group,
            )
        )

    disposable = {item.visual_template_id for item in candidates if item.classification == "PROVEN_DISPOSABLE"}
    retained = tuple(item.visual_template_id for item in candidates if item.visual_template_id not in disposable)
    all_associations = tuple(item for values in associations.values() for item in values)
    return LegacyTemplateCleanupPlan(
        source_revision=int(state.get("revision", 0)),
        source_fingerprint=_cleanup_fingerprint(state),
        candidates=tuple(candidates),
        retained_template_ids=retained,
        total_templates_before=len(templates),
        total_templates_after=len(templates) - len(disposable),
        family_member_count=sum(1 for item in templates if str(item.get("visual_template_id")) in family_members),
        standalone_count=sum(1 for item in templates if str(item.get("visual_template_id")) not in family_members),
        active_reference_count=sum(1 for item in all_associations if item.status == "active"),
        archived_reference_count=sum(1 for item in all_associations if item.status == "archived"),
        provenance_only_reference_count=len(all_associations),
        unreferenced_count=sum(1 for item in templates if str(item.get("visual_template_id")) not in associations),
    )


def apply_legacy_visual_template_cleanup(
    state: Mapping[str, Any],
    plan: LegacyTemplateCleanupPlan,
    *,
    authorized: bool,
) -> dict[str, Any]:
    if not authorized:
        raise WU4Error("CREATION_STATE_INVALID", "Legacy template cleanup requires explicit caller authorization.")
    if not isinstance(plan, LegacyTemplateCleanupPlan):
        raise WU4Error("CREATION_STATE_INVALID", "The legacy template cleanup plan is invalid.")
    if int(state.get("revision", 0)) != plan.source_revision or _cleanup_fingerprint(state) != plan.source_fingerprint:
        raise WU4Error(
            "REVISION_CONFLICT",
            "The legacy template cleanup plan is stale and must be regenerated.",
            {"current_revision": state.get("revision"), "planned_revision": plan.source_revision},
        )
    current_plan = analyze_legacy_visual_templates(state)
    if current_plan != plan:
        raise WU4Error("REVISION_CONFLICT", "The legacy template cleanup analysis changed and must be reviewed again.")

    removable = {
        item.visual_template_id
        for item in plan.candidates
        if item.classification == "PROVEN_DISPOSABLE"
    }
    result = copy.deepcopy(dict(state))
    result.pop("issues", None)
    result["visual_templates"] = [
        template
        for template in result.get("visual_templates", [])
        if template.get("visual_template_id") not in removable
    ]
    return result


__all__ = [
    "LegacyTemplateCandidate",
    "LegacyTemplateCleanupPlan",
    "TemplateAssociation",
    "analyze_legacy_visual_templates",
    "apply_legacy_visual_template_cleanup",
    "canonical_visual_configuration",
    "migrate_creation_state_v3_to_v4",
    "visual_configuration_digest",
    "visual_configuration_from_template",
    "visual_configurations_equivalent",
]
