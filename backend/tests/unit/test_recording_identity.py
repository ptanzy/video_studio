import pytest

from wrld_video_studio.domain.errors import StudioError
from wrld_video_studio.domain.identity import validate_recording_ids


def test_explicit_recording_id_is_accepted():
    assert validate_recording_ids([{"recording_id": "recording-A"}]) == ("recording-A",)


def test_missing_recording_id_requires_review():
    with pytest.raises(StudioError) as caught:
        validate_recording_ids([{"track_id": "T01"}])
    assert caught.value.code == "IDENTITY_REVIEW_REQUIRED"


def test_duplicate_recording_ids_are_rejected():
    with pytest.raises(StudioError) as caught:
        validate_recording_ids(
            [{"recording_id": "recording-A"}, {"recording_id": "recording-A"}]
        )
    assert caught.value.code == "DUPLICATE_RECORDING_ID"
