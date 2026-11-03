from __future__ import annotations

import copy
import json

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


SHA = "a" * 64


def field(value, origin="generated", source=None):
    return {"value": value, "origin": origin, "source_fingerprint": source}


def editor_document():
    return {
        "contract_version": "wrld-youtube-metadata-editor/1.0", "project_id": "project-1", "revision": 1,
        "save_id": "initialize", "generation_version": "wrld-youtube-metadata-draft/1.0",
        "creation_basis": {"contract_version": "wrld-creation-state/4.0", "revision": 2, "state_digest": SHA},
        "targets": [{
            "target_key": "single:single-1", "target": {"kind": "single", "single_id": "single-1"}, "lifecycle": "active",
            "basis": {"creation_target_fingerprint": SHA, "source_metadata_fingerprint": SHA, "chapter_source_fingerprint": None},
            "content": {
                "title": field("First Light", "supplied", SHA), "description": field("Unicode — 世界", "edited"),
                "tags": field(["ambient"]), "hashtags": field([]), "artist_name": field("Artist", "supplied", SHA),
                "channel_name": field("Channel", "supplied", SHA), "credits": field([]), "links": field([]),
                "visibility": field("private"), "pinned_comment": field(None), "release_album_plan_id": field(None),
                "related_video_url": field(None),
            }, "chapters": None, "approval": None,
        }], "state_digest": SHA,
    }


def portable_document():
    metadata = {
        "title": "First Light", "description": "Unicode — 世界", "tags": ["ambient"], "hashtags": [],
        "artist_name": "Artist", "channel_name": "Channel", "credits": [], "links": [], "visibility": "private",
        "pinned_comment": None, "release_album_plan_id": None, "related_video_url": None,
    }
    return {
        "contract_version": "wrld-youtube-metadata/1.0", "project_id": "project-1", "revision": 1,
        "content_fingerprint": SHA, "albums": [],
        "singles": [{"target_key": "single:single-1", "single_id": "single-1", "recording": {"asset_id": "asset-1", "expected_sha256": SHA}, "metadata": metadata, "media": None, "thumbnail": None, "approval": {"fingerprint": SHA, "approved_at": "2026-11-02T00:00:00Z"}}],
        "shorts": [],
    }


def test_wu5_editor_and_portable_examples_match_approved_schemas(schema_dir):
    editor = Draft202012Validator(json.loads((schema_dir / "youtube-metadata-editor-v1.schema.json").read_text(encoding="utf-8")))
    portable = Draft202012Validator(json.loads((schema_dir / "youtube-metadata-v1.schema.json").read_text(encoding="utf-8")))
    editor.validate(editor_document())
    portable.validate(portable_document())


@pytest.mark.parametrize("name,document", [("editor", editor_document()), ("portable", portable_document())])
def test_wu5_schemas_reject_unknown_fields_and_identity_shape(schema_dir, name, document):
    schema_name = "youtube-metadata-editor-v1.schema.json" if name == "editor" else "youtube-metadata-v1.schema.json"
    validator = Draft202012Validator(json.loads((schema_dir / schema_name).read_text(encoding="utf-8")))
    extra = copy.deepcopy(document); extra["creation_visual_settings"] = {}
    with pytest.raises(ValidationError): validator.validate(extra)
    invalid = copy.deepcopy(document)
    if name == "editor": invalid["targets"][0]["target_key"] = "video:single-1"
    else: invalid["singles"][0]["recording"]["expected_sha256"] = "not-a-sha"
    with pytest.raises(ValidationError): validator.validate(invalid)
