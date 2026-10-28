import json

import pytest

from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.video_effects import VideoEffects
from wrld_video_studio.domain.video_effects_v2 import VideoEffectsV2
from wrld_video_studio.domain.video_export_v2 import MotionVideoManifest
from wrld_video_studio.domain.video_export_v3 import RefinedVideoManifest
from wrld_video_studio.infrastructure.project_sources import FilesystemVideoProjectLoader


def _write_project(tmp_path, schema_dir, mutate=None):
    root = tmp_path / "album"
    root.mkdir()
    (root / "background.png").write_bytes(b"png")
    (root / "audio.wav").write_bytes(b"wav")
    value = {
        "format": "wrld-video-album/1.0",
        "album": {"id": "a1", "title": "A", "artist": "B", "channel": "C"},
        "visual": {"background": "background.png"},
        "tracks": [{"id": "t1", "number": 1, "title": "T", "audio": "audio.wav"}],
        "render": {"profile_id": "youtube-1080p30-v1"},
    }
    if mutate:
        mutate(value)
    (root / "video_manifest.json").write_text(json.dumps(value), encoding="utf-8")
    return root, FilesystemVideoProjectLoader(schema_dir / "video-manifest-v1.schema.json")


def test_loader_accepts_portable_sources(tmp_path, schema_dir):
    root, loader = _write_project(tmp_path, schema_dir)
    project = loader.load(root.resolve())
    assert project.root == root.resolve()
    assert project.manifest.tracks[0].audio == "audio.wav"


def test_loader_rejects_obsolete_output_block(tmp_path, schema_dir):
    root, loader = _write_project(tmp_path, schema_dir, lambda value: value.update(output={}))
    with pytest.raises(MediaInfrastructureError) as caught:
        loader.load(root.resolve())
    assert caught.value.code == "MANIFEST_SCHEMA_INVALID"
    assert caught.value.details["property_path"] == "$"


def test_loader_rejects_output_source_alias(tmp_path, schema_dir):
    root, loader = _write_project(
        tmp_path, schema_dir, lambda value: value["visual"].update(background="output/source.png")
    )
    (root / "output").mkdir()
    (root / "output" / "source.png").write_bytes(b"png")
    with pytest.raises(MediaInfrastructureError) as caught:
        loader.load(root.resolve())
    assert caught.value.code == "INVALID_INPUT_PATH"


def test_loader_rejects_duplicate_json_keys(tmp_path, schema_dir):
    root, loader = _write_project(tmp_path, schema_dir)
    (root / "video_manifest.json").write_text(
        '{"format":"wrld-video-album/1.0","format":"wrld-video-album/1.0"}',
        encoding="utf-8",
    )
    with pytest.raises(MediaInfrastructureError) as caught:
        loader.load(root.resolve())
    assert caught.value.code == "MANIFEST_INVALID"


def test_loader_rejects_non_directory_output_boundary(tmp_path, schema_dir):
    root, loader = _write_project(tmp_path, schema_dir)
    (root / "output").write_bytes(b"not a directory")
    with pytest.raises(MediaInfrastructureError) as caught:
        loader.load(root.resolve())
    assert caught.value.code == "INVALID_OUTPUT_PATH"


def test_loader_selects_and_resolves_v2_motion_manifest(tmp_path, schema_dir):
    root, _loader = _write_project(tmp_path, schema_dir)
    document = json.loads((root / "video_manifest.json").read_text(encoding="utf-8"))
    document["format"] = "wrld-video-album/2.0"
    document["render"] = {
        "profile_id": "youtube-1080p30-motion-v1",
        "effects": VideoEffects().to_dict(),
    }
    (root / "video_manifest.json").write_text(json.dumps(document), encoding="utf-8")
    loader = FilesystemVideoProjectLoader(
        (
            schema_dir / "video-manifest-v1.schema.json",
            schema_dir / "video-manifest-v2.schema.json",
        )
    )

    project = loader.load(root.resolve())

    assert isinstance(project.manifest, MotionVideoManifest)
    assert project.manifest.effects == VideoEffects()


def test_v2_loader_rejects_static_profile_before_source_use(tmp_path, schema_dir):
    root, _loader = _write_project(tmp_path, schema_dir)
    document = json.loads((root / "video_manifest.json").read_text(encoding="utf-8"))
    document["format"] = "wrld-video-album/2.0"
    document["render"]["effects"] = VideoEffects().to_dict()
    (root / "video_manifest.json").write_text(json.dumps(document), encoding="utf-8")
    loader = FilesystemVideoProjectLoader(
        (
            schema_dir / "video-manifest-v1.schema.json",
            schema_dir / "video-manifest-v2.schema.json",
        )
    )

    with pytest.raises(MediaInfrastructureError) as caught:
        loader.load(root.resolve())

    assert caught.value.code == "MANIFEST_SCHEMA_INVALID"


def test_loader_selects_and_resolves_v3_refined_manifest(tmp_path, schema_dir):
    root, _loader = _write_project(tmp_path, schema_dir)
    document = json.loads((root / "video_manifest.json").read_text(encoding="utf-8"))
    document["format"] = "wrld-video-album/3.0"
    document["render"] = {
        "profile_id": "youtube-1080p30-motion-v2",
        "effects": VideoEffectsV2().to_dict(),
    }
    (root / "video_manifest.json").write_text(json.dumps(document), encoding="utf-8")
    loader = FilesystemVideoProjectLoader(
        (
            schema_dir / "video-manifest-v1.schema.json",
            schema_dir / "video-manifest-v2.schema.json",
            schema_dir / "video-manifest-v3.schema.json",
        )
    )

    project = loader.load(root.resolve())

    assert isinstance(project.manifest, RefinedVideoManifest)
    assert project.manifest.effects == VideoEffectsV2()
