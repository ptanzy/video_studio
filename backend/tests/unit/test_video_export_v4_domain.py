from __future__ import annotations

import json
from pathlib import Path

import pytest

from wrld_video_studio.domain.canonical_json import canonical_sha256
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.video_export_v4 import (
    PLAYER_PRESENTATION_VERSION,
    PLAYER_PROFILE_ID,
    create_player_plan,
    parse_player_export_result,
    parse_player_export_request,
    parse_player_manifest,
    resolve_display_metadata,
)


FIXTURES = Path(__file__).parents[1] / "contracts" / "fixtures"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_player_manifest_request_plan_and_namespace() -> None:
    manifest = parse_player_manifest(_load("video-manifest-v4-valid.json"))
    request = parse_player_export_request(_load("video-export-request-v4-valid.json"))
    plan = create_player_plan(manifest, request)
    assert request.profile_id == PLAYER_PROFILE_ID
    assert plan.output_relative_path.startswith(
        f"profiles/{PLAYER_PROFILE_ID}/{plan.effect_config_digest}/album/"
    )
    assert plan.effect_config_digest not in {
        manifest.effects.fingerprint,
        "7c2eadb17a2cfab9ed55570d6e68f72ee848b26d29af8307045df02cd60e84b3",
    }
    assert PLAYER_PRESENTATION_VERSION == "wrld-player-presentation/1.0"
    legacy_digest = canonical_sha256({
        "effects": request.effects.to_dict(),
        "resolved_player": request.resolved_player.to_dict(),
    })
    assert plan.effect_config_digest != legacy_digest


def test_metadata_prefers_only_reliable_analysis_and_preserves_provenance() -> None:
    manifest = parse_player_manifest(_load("video-manifest-v4-valid.json"))
    display = resolve_display_metadata(manifest, parse_player_export_request(_load("video-export-request-v4-valid.json")).target)
    assert display[0].bpm == "91.8"
    assert display[0].bpm_provenance == "analyzed"
    assert display[0].musical_key == "D minor"
    assert display[0].key_provenance == "intended"
    assert display[0].parent_channel == "WRLD-FI"
    assert display[0].genre_channel == "World Music"


def test_player_contract_rejects_invented_or_unknown_metadata() -> None:
    value = _load("video-manifest-v4-valid.json")
    value["tracks"][0]["music"]["analyzed"]["bpm"]["reliable"] = "probably"
    with pytest.raises(MediaInfrastructureError) as failure:
        parse_player_manifest(value)
    assert failure.value.code == "MANIFEST_INVALID"


def test_player_request_identity_changes_for_resolved_theme() -> None:
    first = _load("video-export-request-v4-valid.json")
    second = _load("video-export-request-v4-valid.json")
    second["resolved_player"]["theme"]["colors"]["visualizer"] = "#89AABB"
    first_request = parse_player_export_request(first)
    second_request = parse_player_export_request(second)
    assert first_request.to_dict() != second_request.to_dict()


def test_player_result_round_trips_and_rejects_unknown_fields() -> None:
    document = _load("video-export-result-v4-valid.json")
    assert parse_player_export_result(document).to_dict() == document
    document["unknown"] = True
    with pytest.raises(MediaInfrastructureError) as failure:
        parse_player_export_result(document)
    assert failure.value.code == "OUTPUT_INVALID"


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.__setitem__("target", {"kind": "track"}),
        lambda value: value.__setitem__("target", {"kind": "album", "track_id": "extra"}),
        lambda value: value.__setitem__("artifacts", [{"kind": "album_video"}]),
        lambda value: value.__setitem__(
            "timeline",
            [{
                "track_id": "track-01", "number": 1, "title": "First Track",
                "start_sample": 0, "sample_count": 0, "display_seconds": 0,
            }],
        ),
        lambda value: value.__setitem__("started_at", "not-a-date-time"),
    ),
)
def test_player_result_runtime_rejects_schema_invalid_nested_values(mutate) -> None:
    document = _load("video-export-result-v4-valid.json")
    mutate(document)
    with pytest.raises(MediaInfrastructureError) as failure:
        parse_player_export_result(document)
    assert failure.value.code == "OUTPUT_INVALID"
