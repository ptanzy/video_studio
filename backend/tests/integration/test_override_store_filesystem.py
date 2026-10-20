from wrld_video_studio.infrastructure.override_store import OverrideStore


def test_filesystem_store_round_trip_keeps_revision_and_opaque_values(tmp_path, override_schema):
    store = OverrideStore(tmp_path / "editor-state", override_schema)
    store.create("album-integration-fixture")

    saved = store.update(
        "album-integration-fixture",
        expected_revision=0,
        overrides={"unmodeled": ["text", 7, {"preserve": True}]},
    )
    reloaded = OverrideStore(tmp_path / "editor-state", override_schema).read(
        "album-integration-fixture"
    )

    assert saved["revision"] == 1
    assert reloaded == saved
