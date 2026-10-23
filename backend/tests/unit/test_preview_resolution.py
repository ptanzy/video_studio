from __future__ import annotations

from dataclasses import dataclass

import pytest

from wrld_video_studio.application.preview_resolution import ResolvedPreviewService
from wrld_video_studio.application.preview_service import PreviewServiceError
from wrld_video_studio.domain.preview_cache import PreviewRequest
from wrld_video_studio.infrastructure.preview_context import (
    ImmutablePreviewContextRegistry,
    PreviewContextRegistration,
)


def _request(*, mode="auto", track_id=None, short_id=None, **treatment):
    value = {
        "contract_version": "preview-request-v1",
        "target": {
            "album_id": "album-1",
            "artwork_asset_id": "artwork-1",
        },
        "treatment": {"mode": mode, "intensity": 0.3, **treatment},
        "variant": "authoritative_still",
    }
    if track_id is not None:
        value["target"]["track_id"] = track_id
    if short_id is not None:
        value["target"]["short_id"] = short_id
    return PreviewRequest.from_dict(value)


@dataclass
class _Prepared:
    marker: str = "prepared"


class _PreviewService:
    def __init__(self):
        self.calls = []

    def execute(self, request, resolution, cancel_event=None):
        self.calls.append((request, resolution, cancel_event))
        return _Prepared()


def _service(*registrations):
    preview = _PreviewService()
    registry = ImmutablePreviewContextRegistry(registrations)
    return ResolvedPreviewService(context_provider=registry, preview_service=preview), preview


def test_auto_uses_exact_full_target_and_preserves_unknown_mood_fallback():
    service, preview = _service(
        PreviewContextRegistration("album-1", "artwork-1", {"album_palette": [{"hex": "#112233"}]}),
        PreviewContextRegistration(
            "album-1",
            "artwork-1",
            {"mood": "a totally unknown but valid feeling"},
            track_id="track-1",
            short_id="short-1",
        ),
    )

    service.execute(_request(track_id="track-1", short_id="short-1"))

    resolution = preview.calls[0][1]
    assert resolution.mode == "auto"
    assert resolution.resolved_hex is None
    assert resolution.preset_id == "original"
    assert resolution.source == "fallback"


def test_auto_without_track_or_short_uses_album_artwork_context():
    service, preview = _service(
        PreviewContextRegistration(
            "album-1", "artwork-1", {"album_palette": [{"hex": "#abcdef"}]}
        )
    )

    service.execute(_request())

    assert preview.calls[0][1].resolved_hex == "#ABCDEF"


@pytest.mark.parametrize(
    ("track_id", "short_id"),
    [("unknown", None), (None, "unknown"), ("track-1", "unknown")],
)
def test_auto_unknown_supplied_target_never_inherits_album_context(track_id, short_id):
    service, _preview = _service(
        PreviewContextRegistration(
            "album-1", "artwork-1", {"album_palette": [{"hex": "#112233"}]}
        )
    )

    with pytest.raises(PreviewServiceError) as raised:
        service.execute(_request(track_id=track_id, short_id=short_id))

    assert raised.value.code == "PREVIEW_INVALID_REQUEST"


@pytest.mark.parametrize(
    ("mode", "extra", "expected_hex"),
    [
        ("preset", {"preset": "warm"}, "#B47B55"),
        ("custom", {"hex": "#123456"}, "#123456"),
    ],
)
def test_preset_and_custom_do_not_require_or_consult_context(mode, extra, expected_hex):
    service, preview = _service()

    service.execute(_request(mode=mode, **extra))

    assert preview.calls[0][1].resolved_hex == expected_hex


def test_context_registry_is_deeply_immutable_and_returns_independent_values():
    source = {"album_palette": [{"hex": "#123456", "name": "primary"}]}
    registry = ImmutablePreviewContextRegistry(
        [PreviewContextRegistration("album-1", "artwork-1", source)]
    )
    source["album_palette"][0]["hex"] = "#FFFFFF"

    first = registry.context_for(_request().target)
    first["album_palette"][0]["hex"] = "#000000"
    second = registry.context_for(_request().target)

    assert second == {"album_palette": [{"hex": "#123456", "name": "primary"}]}


def test_invalid_trusted_context_is_rejected_during_registry_construction():
    with pytest.raises(ValueError):
        ImmutablePreviewContextRegistry(
            [PreviewContextRegistration("album-1", "artwork-1", {"private_path": "C:/secret"})]
        )
