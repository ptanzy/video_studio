from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from wrld_video_studio.application.ports.still_images import (
    STILL_RENDER_REQUEST_VERSION,
    StillRenderRequest,
)
from wrld_video_studio.domain.color_resolution import resolve_color_treatment
from wrld_video_studio.domain.jobs import ProcessExecution
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.infrastructure.still_image_renderer import (
    FFmpegStillImageRenderer,
    REQUIRED_FFMPEG_ENCODERS,
    REQUIRED_FFMPEG_FILTERS,
    _ImageInfo,
    _read_image_metadata,
    _treatment_filter_graph,
)


class StubToolchain:
    def resolve(self, name: str):
        return SimpleNamespace(path=Path(name), version=f"{name} version fixture")


class RecordingRunner:
    def __init__(self, result: ProcessExecution | None = None) -> None:
        self.result = result or ProcessExecution(0, "", "", sanitized_argv=("ffmpeg",))
        self.calls: list[tuple[list[str], float, object]] = []

    def run(self, argv, timeout_seconds, cancel_event=None, heartbeat=None, progress_callback=None):
        self.calls.append((list(argv), timeout_seconds, cancel_event))
        return self.result

    @staticmethod
    def sanitize_diagnostic(text: str) -> str:
        return text


class CapabilityRunner(RecordingRunner):
    def __init__(self, filters=None, encoders=None) -> None:
        super().__init__()
        self.filters = set(REQUIRED_FFMPEG_FILTERS if filters is None else filters)
        self.encoders = set(REQUIRED_FFMPEG_ENCODERS if encoders is None else encoders)

    def run(self, argv, timeout_seconds, cancel_event=None, heartbeat=None, progress_callback=None):
        self.calls.append((list(argv), timeout_seconds, cancel_event))
        if "-filters" in argv:
            output = "\n".join(f" ... {name} fixture" for name in sorted(self.filters))
        elif "-encoders" in argv:
            output = "\n".join(f" V..... {name} fixture" for name in sorted(self.encoders))
        else:
            output = ""
        return ProcessExecution(0, output, "")


def _resolution(hex_color="#71869A", intensity=0.3):
    return resolve_color_treatment(
        {
            "contract_version": "color-resolution-input-v1",
            "treatment": {"mode": "custom", "hex": hex_color, "intensity": intensity},
        }
    )


def _request(source: Path, output="rendered.png", resolution=None):
    return StillRenderRequest(
        contract_version=STILL_RENDER_REQUEST_VERSION,
        source_path=source,
        output_relative_path=output,
        resolution=resolution or _resolution(),
    )


def _renderer(tmp_path, runner=None, timeout_seconds=30.0):
    runner = runner or RecordingRunner()
    return FFmpegStillImageRenderer(
        StubToolchain(), runner, tmp_path / "outputs", timeout_seconds=timeout_seconds
    )


@pytest.mark.parametrize("field", ["resolver_version", "preset_mapping_version"])
def test_runtime_rejects_fabricated_phase_one_versions(tmp_path, field):
    resolution = replace(_resolution(), **{field: "fabricated"})

    with pytest.raises(MediaInfrastructureError) as raised:
        _renderer(tmp_path)._validate_resolution(resolution)

    assert raised.value.code == "INVALID_COLOR_RESOLUTION"


def test_runtime_request_path_rules_match_contract_case_and_extension(tmp_path):
    renderer = _renderer(tmp_path)
    with pytest.raises(MediaInfrastructureError) as extension_error:
        renderer._validate_request(_request(tmp_path / "source.png", "result.PNG"))
    assert extension_error.value.code == "INVALID_OUTPUT_FORMAT"

    with pytest.raises(MediaInfrastructureError) as reserved_error:
        renderer._resolve_output(".WRLD-STAGING/result.png")
    assert reserved_error.value.code == "INVALID_OUTPUT_PATH"


def test_black_target_graph_is_the_same_explicit_untreated_pipeline():
    graph = _treatment_filter_graph("#000000", 0.6, 20, 10)

    assert "geq=" not in graph
    assert "rangein=full:range=full" in graph
    assert "format=rgb24" in graph


def test_treated_graph_explicitly_clamps_gamut_and_declares_full_range():
    graph = _treatment_filter_graph("#B47B55", 0.6, 20, 10)

    assert graph.startswith("format=rgb24,zscale=")
    assert not graph.startswith("format=gbrpf32le")
    assert "max(0,min(" in graph
    assert "min(1,max(0," in graph
    assert graph.count("rangein=full:range=full") == 2
    assert graph.endswith("format=rgb24")


def test_capability_validation_accepts_complete_listing_and_reports_missing(tmp_path):
    complete_runner = CapabilityRunner()
    _renderer(tmp_path, complete_runner)._validate_ffmpeg_capabilities(Path("ffmpeg"), None)
    assert [call[0][-1] for call in complete_runner.calls] == ["-filters", "-encoders"]

    incomplete_runner = CapabilityRunner(filters={"scale"}, encoders=set())
    with pytest.raises(MediaInfrastructureError) as raised:
        _renderer(tmp_path, incomplete_runner)._validate_ffmpeg_capabilities(Path("ffmpeg"), None)
    assert raised.value.code == "MEDIA_CAPABILITY_MISSING"
    assert raised.value.details == {
        "missing_filters": sorted(REQUIRED_FFMPEG_FILTERS - {"scale"}),
        "missing_encoders": ["png"],
    }


def test_pre_cancelled_request_stops_before_source_or_tool_access(tmp_path):
    cancel_event = Event()
    cancel_event.set()

    with pytest.raises(MediaInfrastructureError) as raised:
        _renderer(tmp_path).render(_request(tmp_path / "missing.png"), cancel_event)

    assert raised.value.code == "PROCESS_CANCELLED"


@pytest.mark.parametrize(
    ("execution", "expected_code"),
    [
        (ProcessExecution(-1, "", "cancelled", cancelled=True), "PROCESS_CANCELLED"),
        (ProcessExecution(-1, "", "timeout", timed_out=True), "PROCESS_TIMEOUT"),
    ],
)
def test_process_cancel_and_timeout_clean_owned_staging(
    tmp_path, monkeypatch, execution, expected_code
):
    source = tmp_path / "source.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\n")
    runner = RecordingRunner(execution)
    renderer = _renderer(tmp_path, runner)
    info = _ImageInfo("png", 1, 1, "rgba", 0, 1, None, None, None)
    monkeypatch.setattr(renderer, "_validate_ffmpeg_capabilities", lambda *args: None)
    monkeypatch.setattr(renderer, "_probe_image", lambda *args: info)
    monkeypatch.setattr(renderer, "_count_image_frames", lambda *args: 1)

    with pytest.raises(MediaInfrastructureError) as raised:
        renderer.render(_request(source), Event())

    assert raised.value.code == expected_code
    assert not (tmp_path / "outputs" / "rendered.png").exists()
    assert list((tmp_path / "outputs").glob("*.partial.png")) == []


def test_configurable_timeout_and_cancel_token_reach_render_process(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\n")
    runner = RecordingRunner()
    renderer = _renderer(tmp_path, runner, timeout_seconds=7.5)
    info = _ImageInfo("png", 2, 1, "rgba", 0, 1, None, None, None)
    monkeypatch.setattr(renderer, "_validate_ffmpeg_capabilities", lambda *args: None)
    monkeypatch.setattr(renderer, "_probe_image", lambda *args: info)
    monkeypatch.setattr(renderer, "_count_image_frames", lambda *args: 1)
    monkeypatch.setattr(renderer, "_verify_png", lambda *args: None)

    original_run = runner.run

    def write_render(argv, timeout_seconds, cancel_event=None, **kwargs):
        result = original_run(argv, timeout_seconds, cancel_event, **kwargs)
        Path(argv[-1]).write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00IEND\xaeB\x60\x82"
        )
        return result

    monkeypatch.setattr(runner, "run", write_render)
    cancel_event = Event()
    result = renderer.render(_request(source), cancel_event)

    assert result.artifact_path.is_file()
    assert runner.calls[-1][1] == 7.5
    assert runner.calls[-1][2] is cancel_event
    assert source.read_bytes() == b"\x89PNG\r\n\x1a\n"


def test_dimension_limit_is_enforced_before_expensive_frame_count(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\n")
    renderer = _renderer(tmp_path)
    info = _ImageInfo("png", 10_001, 1, "rgba", 0, 1, None, None, None)
    monkeypatch.setattr(renderer, "_validate_ffmpeg_capabilities", lambda *args: None)
    monkeypatch.setattr(renderer, "_probe_image", lambda *args: info)

    def frame_count_must_not_run(*args):
        raise AssertionError("frame counting ran before dimension enforcement")

    monkeypatch.setattr(renderer, "_count_image_frames", frame_count_must_not_run)
    with pytest.raises(MediaInfrastructureError) as raised:
        renderer.render(_request(source))

    assert raised.value.code == "IMAGE_DIMENSION_LIMIT"


def test_container_extension_mismatch_is_rejected_before_frame_count(tmp_path, monkeypatch):
    source = tmp_path / "source.jpg"
    source.write_bytes(b"\xff\xd8\xff\xd9")
    renderer = _renderer(tmp_path)
    info = _ImageInfo("png", 1, 1, "rgb24", 0, 1, None, None, None)
    monkeypatch.setattr(renderer, "_validate_ffmpeg_capabilities", lambda *args: None)
    monkeypatch.setattr(renderer, "_probe_image", lambda *args: info)
    monkeypatch.setattr(
        renderer,
        "_count_image_frames",
        lambda *args: (_ for _ in ()).throw(AssertionError("unexpected frame count")),
    )

    with pytest.raises(MediaInfrastructureError) as raised:
        renderer.render(_request(source))

    assert raised.value.code == "IMAGE_EXTENSION_MISMATCH"


def test_animated_frame_count_is_rejected_before_staging(tmp_path, monkeypatch):
    source = tmp_path / "animated.webp"
    source.write_bytes(b"RIFF\x04\x00\x00\x00WEBP")
    renderer = _renderer(tmp_path)
    info = _ImageInfo("webp", 2, 2, "rgba", 0, 1, None, None, None)
    monkeypatch.setattr(renderer, "_validate_ffmpeg_capabilities", lambda *args: None)
    monkeypatch.setattr(renderer, "_probe_image", lambda *args: info)
    monkeypatch.setattr(renderer, "_count_image_frames", lambda *args: 2)

    with pytest.raises(MediaInfrastructureError) as raised:
        renderer.render(_request(source))

    assert raised.value.code == "ANIMATED_IMAGE_UNSUPPORTED"
    assert list((tmp_path / "outputs").glob("*.partial.png")) == []


def test_embedded_profile_is_rejected_before_tool_discovery(tmp_path):
    source = tmp_path / "profile.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00iCCP\x00\x00\x00\x00")
    runner = RecordingRunner()
    renderer = _renderer(tmp_path, runner)

    with pytest.raises(MediaInfrastructureError) as raised:
        renderer.render(_request(source))

    assert raised.value.code == "IMAGE_COLOR_PROFILE_UNSUPPORTED"
    assert runner.calls == []


def test_png_srgb_chunk_makes_matching_gamma_metadata_order_independent(tmp_path):
    def chunk(name: bytes, payload: bytes) -> bytes:
        return len(payload).to_bytes(4, "big") + name + payload + b"\x00\x00\x00\x00"

    srgb = tmp_path / "srgb.png"
    srgb.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"gAMA", (45455).to_bytes(4, "big"))
        + chunk(b"sRGB", b"\x00")
        + chunk(b"IEND", b"")
    )
    untagged_gamma = tmp_path / "gamma-only.png"
    untagged_gamma.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"gAMA", (45455).to_bytes(4, "big"))
        + chunk(b"IEND", b"")
    )

    assert _read_image_metadata(srgb) == (1, False)
    assert _read_image_metadata(untagged_gamma) == (1, True)


def test_malformed_probe_response_is_a_typed_input_error(tmp_path):
    runner = RecordingRunner(ProcessExecution(0, "not-json", ""))
    renderer = _renderer(tmp_path, runner)

    with pytest.raises(MediaInfrastructureError) as raised:
        renderer._probe_image(Path("ffprobe"), tmp_path / "source.png")

    assert raised.value.code == "IMAGE_UNSUPPORTED_OR_CORRUPT"


def test_atomic_publication_never_replaces_existing_destination(tmp_path):
    staged = tmp_path / "staged.png"
    destination = tmp_path / "result.png"
    staged.write_bytes(b"new")
    destination.write_bytes(b"existing")

    with pytest.raises(MediaInfrastructureError) as raised:
        FFmpegStillImageRenderer._publish_no_replace(staged, destination)

    assert raised.value.code == "OUTPUT_COLLISION"
    assert destination.read_bytes() == b"existing"
    assert staged.read_bytes() == b"new"
