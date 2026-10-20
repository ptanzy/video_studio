from copy import deepcopy

import pytest

from wrld_video_studio.application.manifest_validation import validate_manifest
from wrld_video_studio.domain.errors import StudioError


def test_valid_manifest_preserves_unknown_metadata_and_free_form_emotion(
    valid_manifest, manifest_schema
):
    result = validate_manifest(valid_manifest, manifest_schema)
    assert result["tracks"][0]["music"]["emotion"].startswith("misty")
    assert result["tracks"][0]["creative_metadata"] == {"unmodeled_note": "retain this source value"}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.pop("project"),
        lambda value: value.update(schema_version="3.0"),
    ],
    ids=["missing-required-field", "incorrect-version"],
)
def test_missing_fields_and_incorrect_version_are_typed_errors(
    valid_manifest, manifest_schema, mutate
):
    manifest = deepcopy(valid_manifest)
    mutate(manifest)
    with pytest.raises(StudioError) as caught:
        validate_manifest(manifest, manifest_schema)
    assert caught.value.code == "INVALID_MANIFEST"


def test_duplicate_track_ids_are_rejected_semantically(valid_manifest, manifest_schema):
    manifest = deepcopy(valid_manifest)
    manifest["tracks"].append(deepcopy(manifest["tracks"][0]))
    with pytest.raises(StudioError, match="Track IDs must be unique") as caught:
        validate_manifest(manifest, manifest_schema)
    assert caught.value.code == "INVALID_MANIFEST"
