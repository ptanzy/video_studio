from pathlib import Path
from types import SimpleNamespace

import pytest

from wrld_video_studio.application.video_export import VideoExports
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.video_export import (
    ExportTarget,
    VideoExportRequest,
    create_plan,
    parse_manifest,
)
from wrld_video_studio.infrastructure.artifact_store import FilesystemArtifactStore
from wrld_video_studio.infrastructure.video_export_paths import VideoExportPathPreflight


def _manifest(title: str = "Album"):
    document = {
        "format": "wrld-video-album/1.0",
        "album": {"id": "album-1", "title": title, "artist": "Artist", "channel": "Channel"},
        "visual": {"background": "background.png"},
        "tracks": [{"id": "track-1", "number": 1, "title": "Track", "audio": "track.wav"}],
        "render": {"profile_id": "youtube-1080p30-v1"},
    }
    return document, parse_manifest(document)


def test_preflight_accepts_spaces_unicode_and_bounded_staging(tmp_path):
    root = tmp_path / "Álbum Project With Spaces"
    root.mkdir()
    store = FilesystemArtifactStore(root / "output")
    document, manifest = _manifest("夜のアルバム")
    plan = create_plan(manifest, VideoExportRequest(ExportTarget("album")))
    validator = VideoExportPathPreflight(
        store, windows=True, max_path_characters=500
    )

    validator.validate(root, plan)

    paths = store.preflight_paths(plan.output_relative_path)
    assert all(path.is_absolute() for path in paths.values())
    assert paths["staged_output"].name.endswith(".partial.mp4")
    assert "夜のアルバム" not in paths["staged_output"].name


def test_preflight_rejects_long_final_path_with_safe_context(tmp_path):
    root = tmp_path / "album"
    root.mkdir()
    store = FilesystemArtifactStore(root / "output")
    _document, manifest = _manifest("A" * 180)
    plan = create_plan(manifest, VideoExportRequest(ExportTarget("album")))
    validator = VideoExportPathPreflight(
        store, windows=True, max_path_characters=120
    )

    with pytest.raises(MediaInfrastructureError) as failure:
        validator.validate(root, plan)

    assert failure.value.code == "INVALID_OUTPUT_PATH"
    assert failure.value.details == {
        "path_purpose": "final_output",
        "actual_characters": len(str(store.resolve_final(plan.output_relative_path)).encode("utf-16-le")) // 2,
        "supported_characters": 120,
    }
    assert str(root) not in str(failure.value.details)


def test_preflight_rejection_happens_before_job_submission(tmp_path):
    root = tmp_path / "album"
    root.mkdir()
    (root / "background.png").write_bytes(b"png")
    (root / "track.wav").write_bytes(b"wav")
    document, manifest = _manifest("Album")
    project = SimpleNamespace(root=root.resolve(), manifest=manifest, manifest_document=document)

    class Loader:
        def load(self, _path):
            return project

    class Jobs:
        called = False

        def submit(self, *args, **kwargs):
            self.called = True
            raise AssertionError("job submission must not run")

    class RejectingValidator:
        def validate(self, _root, _plan):
            raise MediaInfrastructureError("INVALID_OUTPUT_PATH", "rejected")

    jobs = Jobs()
    exports = VideoExports(Loader(), jobs, path_validator=RejectingValidator())

    with pytest.raises(MediaInfrastructureError) as failure:
        exports.submit(root, VideoExportRequest(ExportTarget("album")))

    assert failure.value.code == "INVALID_OUTPUT_PATH"
    assert jobs.called is False
    assert not (root / "output" / ".wrld-staging").exists()
