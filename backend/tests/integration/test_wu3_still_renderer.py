from __future__ import annotations

import hashlib
import math
import struct
import tempfile
import zlib
from pathlib import Path
from threading import Event

import pytest

from wrld_video_studio.application.ports.still_images import (
    STILL_RENDER_REQUEST_VERSION,
    STILL_RENDERER_VERSION,
    StillRenderRequest,
)
from wrld_video_studio.domain.color_resolution import resolve_color_treatment
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.infrastructure.media_tools import MediaToolchain
from wrld_video_studio.infrastructure.process_runner import SubprocessRunner
from wrld_video_studio.infrastructure.still_image_renderer import (
    FFmpegStillImageRenderer,
    MAX_INPUT_BYTES,
    _read_image_metadata,
    _scaled_dimensions,
)


pytestmark = pytest.mark.integration_ffmpeg

# Measured on Gyan FFmpeg 9.0.2 essentials across the matrix below. FFmpeg's
# float expression and pixel-format conversion may choose the adjacent 8-bit
# code relative to the ties-up Python reference, but no larger error is accepted.
MEASURED_MAX_RGB_CODE_ERROR = 1


@pytest.fixture(scope="module", autouse=True)
def require_ffmpeg_toolchain() -> None:
    runner = SubprocessRunner()
    tools = MediaToolchain(runner)
    try:
        tools.resolve("ffmpeg")
        tools.resolve("ffprobe")
    except MediaInfrastructureError as error:
        if error.code == "MEDIA_TOOL_MISSING":
            pytest.skip(f"FFmpeg still-render tools unavailable: {error.code}: {error.message}")
        raise


def _chunk(name: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)


def _webp_chunk_types(data: bytes) -> list[bytes]:
    assert data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    assert int.from_bytes(data[4:8], "little") + 8 == len(data)
    offset = 12
    chunk_types: list[bytes] = []
    while offset + 8 <= len(data):
        chunk_type = data[offset : offset + 4]
        length = int.from_bytes(data[offset + 4 : offset + 8], "little")
        end = offset + 8 + length
        assert end <= len(data)
        chunk_types.append(chunk_type)
        offset = end + (length & 1)
    assert offset == len(data)
    return chunk_types


def _write_rgba_png(
    path: Path,
    width: int,
    height: int,
    pixels: list[tuple[int, int, int, int]],
    orientation: int | None = None,
) -> None:
    assert len(pixels) == width * height
    rows = bytearray()
    for row in range(height):
        rows.append(0)
        for red, green, blue, alpha in pixels[row * width : (row + 1) * width]:
            rows.extend((red, green, blue, alpha))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    orientation_chunk = b""
    if orientation is not None:
        assert orientation in range(1, 9)
        tiff = (
            b"II\x2a\x00\x08\x00\x00\x00\x01\x00"
            b"\x12\x01\x03\x00\x01\x00\x00\x00"
            + orientation.to_bytes(2, "little")
            + b"\x00\x00\x00\x00\x00\x00"
        )
        orientation_chunk = _chunk(b"eXIf", tiff)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + orientation_chunk
        + _chunk(b"IDAT", zlib.compress(bytes(rows), level=9))
        + _chunk(b"IEND", b"")
    )


def _write_solid_rgba_png(
    path: Path, width: int, height: int, pixel: tuple[int, int, int, int]
) -> None:
    row = b"\x00" + bytes(pixel) * width
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(row * height, level=9))
        + _chunk(b"IEND", b"")
    )


def _resolution(
    mode: str = "custom",
    hex_color: str = "#71869A",
    intensity: float = 0.6,
    preset: str = "original",
):
    treatment = (
        {"mode": "preset", "preset": preset, "intensity": intensity}
        if mode == "preset"
        else {"mode": "custom", "hex": hex_color, "intensity": intensity}
    )
    return resolve_color_treatment({"contract_version": "color-resolution-input-v1", "treatment": treatment})


def _renderer(tmp_path, timeout_seconds=30.0):
    runner = SubprocessRunner()
    tools = MediaToolchain(runner)
    return FFmpegStillImageRenderer(
        tools, runner, tmp_path / "outputs", timeout_seconds=timeout_seconds
    )


def _run_ffmpeg(arguments: list[str]) -> None:
    runner = SubprocessRunner()
    ffmpeg_path = MediaToolchain(runner).resolve("ffmpeg").path
    result = runner.run(
        [str(ffmpeg_path), "-hide_banner", "-nostdin", "-v", "error", *arguments],
        timeout_seconds=30.0,
    )
    assert result.returncode == 0, result.stderr_tail


def _render(renderer, source, relative, resolution):
    return renderer.render(
        StillRenderRequest(
            contract_version=STILL_RENDER_REQUEST_VERSION,
            source_path=source,
            output_relative_path=relative,
            resolution=resolution,
            renderer_version=STILL_RENDERER_VERSION,
        )
    )


def _decode_rgba(path: Path) -> list[tuple[int, int, int, int]]:
    runner = SubprocessRunner()
    ffmpeg_path = MediaToolchain(runner).resolve("ffmpeg").path
    with tempfile.TemporaryDirectory() as temporary_directory:
        raw_path = Path(temporary_directory) / "decoded.rgba"
        result = runner.run(
            [
                str(ffmpeg_path), "-hide_banner", "-nostdin", "-v", "error", "-i", str(path),
                "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-y", str(raw_path),
            ],
            timeout_seconds=15.0,
        )
        assert result.returncode == 0
        data = raw_path.read_bytes()
    assert len(data) % 4 == 0
    return [tuple(data[offset : offset + 4]) for offset in range(0, len(data), 4)]


def _reference_channel_to_linear(channel: float) -> float:
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def _reference_channel_to_srgb(channel: float) -> float:
    if channel <= 0.0031308:
        return 12.92 * channel
    return 1.055 * channel ** (1.0 / 2.4) - 0.055


def _reference_tint_8bit(
    source: tuple[int, int, int], target_hex: str, intensity: float
) -> tuple[int, int, int]:
    source_linear = tuple(_reference_channel_to_linear(value / 255) for value in source)
    target_linear = tuple(
        _reference_channel_to_linear(int(target_hex[index : index + 2], 16) / 255)
        for index in (1, 3, 5)
    )
    weights = (0.2126, 0.7152, 0.0722)
    source_luminance = sum(weight * value for weight, value in zip(weights, source_linear))
    target_luminance = sum(weight * value for weight, value in zip(weights, target_linear))
    if intensity == 0 or source_luminance == 0 or target_luminance == 0:
        return source
    chromaticity = tuple(value / target_luminance for value in target_linear)
    candidate = tuple(
        (1 - intensity) * source_value
        + intensity * source_luminance * target_value
        for source_value, target_value in zip(source_linear, chromaticity)
    )
    differences = tuple(value - source_luminance for value in candidate)
    scales = [1.0]
    for difference in differences:
        if difference > 0:
            scales.append((1 - source_luminance) / difference)
        elif difference < 0:
            scales.append(source_luminance / -difference)
    gamut_scale = min(1.0, max(0.0, min(scales)))
    bounded = tuple(
        min(1.0, max(0.0, source_luminance + gamut_scale * difference))
        for difference in differences
    )
    return tuple(
        math.floor(min(1.0, max(0.0, _reference_channel_to_srgb(value))) * 255 + 0.5)
        for value in bounded
    )


def test_renderer_matches_independent_reference_preserves_alpha_and_source(tmp_path):
    source = tmp_path / "source.png"
    source_pixels = [
        (128, 128, 128, 255),
        (255, 0, 0, 255),
        (0, 255, 0, 127),
        (0, 0, 255, 0),
        (2, 1, 0, 255),
        (248, 252, 255, 255),
        (64, 128, 192, 255),
        (255, 255, 255, 255),
    ]
    _write_rgba_png(source, 4, 2, source_pixels)
    original_bytes = source.read_bytes()
    source_digest = hashlib.sha256(original_bytes).hexdigest()
    renderer = _renderer(tmp_path)
    resolution = _resolution(hex_color="#B47B55", intensity=0.6)

    result = _render(renderer, source, "treated.png", resolution)
    actual = _decode_rgba(result.artifact_path)
    expected = [
        _reference_tint_8bit((red, green, blue), "#B47B55", 0.6)
        + (alpha,)
        for red, green, blue, alpha in source_pixels
    ]

    assert (result.width, result.height, result.output_format, result.output_pixel_format) == (4, 2, "png", "rgba")
    assert result.source_sha256 == source_digest
    assert result.treatment.input_fingerprint == resolution.input_fingerprint
    assert len(actual) == len(expected)
    for observed, reference in zip(actual, expected):
        assert all(
            abs(observed[channel] - reference[channel])
            <= MEASURED_MAX_RGB_CODE_ERROR
            for channel in range(3)
        ), (observed, reference)
        assert observed[3] == reference[3]
    assert source.read_bytes() == original_bytes


def test_original_and_zero_intensity_bypass_treatment_and_preserve_alpha(tmp_path):
    source = tmp_path / "transparent.png"
    pixels = [(20, 80, 140, 0), (128, 128, 128, 73), (250, 20, 10, 255), (4, 3, 2, 128)]
    _write_rgba_png(source, 2, 2, pixels)
    renderer = _renderer(tmp_path)

    original = _render(
        renderer,
        source,
        "original.png",
        _resolution(mode="preset", preset="original", intensity=0.6),
    )
    zero = _render(renderer, source, "zero.png", _resolution(hex_color="#5F817B", intensity=0.0))
    black = _render(renderer, source, "black.png", _resolution(hex_color="#000000", intensity=0.6))
    expected = [channel for pixel in pixels for channel in pixel]

    for artifact in (original.artifact_path, zero.artifact_path, black.artifact_path):
        assert list(bytes(value for pixel in _decode_rgba(artifact) for value in pixel)) == expected


def test_preset_treatment_uses_the_same_reference_math(tmp_path):
    source = tmp_path / "preset-source.png"
    pixels = [(64, 128, 192, 255), (250, 250, 250, 31)]
    _write_rgba_png(source, 2, 1, pixels)
    renderer = _renderer(tmp_path)

    rendered = _render(
        renderer,
        source,
        "preset.png",
        _resolution(mode="preset", preset="warm", intensity=0.6),
    )
    actual = _decode_rgba(rendered.artifact_path)
    expected = [
        _reference_tint_8bit((red, green, blue), "#B47B55", 0.6) + (alpha,)
        for red, green, blue, alpha in pixels
    ]
    for observed, reference in zip(actual, expected):
        assert max(abs(a - b) for a, b in zip(observed[:3], reference[:3])) <= MEASURED_MAX_RGB_CODE_ERROR
        assert observed[3] == reference[3]


def test_measured_reference_matrix_has_at_most_one_code_rgb_error_and_exact_alpha(tmp_path):
    gray_values = [0, 1, 2, 4, 8, 16, 32, 64, 96, 128, 160, 192, 224, 248, 254, 255]
    rgb_values = [(value, value, value) for value in gray_values] + [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 0),
        (0, 255, 255),
        (255, 0, 255),
        (1, 2, 3),
        (3, 2, 1),
        (10, 128, 250),
        (250, 128, 10),
        (64, 128, 192),
        (192, 64, 128),
    ]
    pixels = [
        (red, green, blue, (index * 37) % 256)
        for index, (red, green, blue) in enumerate(rgb_values)
    ]
    cases = [
        ("preset-cool", "#71869A", 0.6, "preset", "cool"),
        ("preset-warm", "#B47B55", 0.6, "preset", "warm"),
        ("preset-lavender", "#887A9B", 0.6, "preset", "lavender"),
        ("preset-teal", "#5F817B", 0.6, "preset", "teal"),
        ("preset-dark", "#48525A", 0.6, "preset", "dark"),
        ("custom-saturated", "#15A0E7", 0.6, "custom", None),
        ("custom-neutral", "#808080", 0.6, "custom", None),
        ("custom-white", "#FFFFFF", 0.6, "custom", None),
        ("custom-black", "#000000", 0.6, "custom", None),
        ("custom-mid", "#B47B55", 0.3, "custom", None),
        ("custom-zero", "#B47B55", 0.0, "custom", None),
    ]
    source = tmp_path / "reference-matrix.png"
    _write_rgba_png(source, len(pixels), 1, pixels)
    renderer = _renderer(tmp_path)
    rgb_errors: list[int] = []
    alpha_errors: list[int] = []

    for index, (name, target, intensity, mode, preset) in enumerate(cases):
        rendered = _render(
            renderer,
            source,
            f"matrix-{index}-{name}.png",
            _resolution(
                mode=mode,
                preset=preset or "original",
                hex_color=target,
                intensity=intensity,
            ),
        )
        actual = _decode_rgba(rendered.artifact_path)
        expected = [
            _reference_tint_8bit((red, green, blue), target, intensity) + (alpha,)
            for red, green, blue, alpha in pixels
        ]
        rgb_errors.extend(
            abs(observed[channel] - reference[channel])
            for observed, reference in zip(actual, expected)
            for channel in range(3)
        )
        alpha_errors.extend(
            abs(observed[3] - reference[3])
            for observed, reference in zip(actual, expected)
        )

    assert len(rgb_errors) == 924
    assert max(rgb_errors) == MEASURED_MAX_RGB_CODE_ERROR
    assert set(rgb_errors) <= {0, 1}
    assert max(alpha_errors) == 0


def test_jpeg_and_lossless_webp_inputs_render_from_their_decoded_pixels(tmp_path):
    seed = tmp_path / "seed.png"
    pixels = [
        (20, 80, 140, 255),
        (220, 30, 10, 255),
        (0, 255, 0, 127),
        (4, 3, 2, 0),
    ]
    _write_rgba_png(seed, 2, 2, pixels)
    jpeg = tmp_path / "source.jpg"
    webp = tmp_path / "source.webp"
    _run_ffmpeg(
        [
            "-i", str(seed), "-frames:v", "1", "-c:v", "mjpeg", "-q:v", "1",
            "-pix_fmt", "yuvj444p", "-y", str(jpeg),
        ]
    )
    _run_ffmpeg(
        [
            "-i", str(seed), "-frames:v", "1", "-c:v", "libwebp", "-lossless", "1",
            "-pix_fmt", "yuva420p", "-y", str(webp),
        ]
    )
    renderer = _renderer(tmp_path)
    original = _resolution(mode="preset", preset="original", intensity=0.6)

    for source in (jpeg, webp):
        before = source.read_bytes()
        expected = _decode_rgba(source)
        result = _render(renderer, source, f"decoded-{source.suffix[1:]}.png", original)
        actual = _decode_rgba(result.artifact_path)
        assert len(actual) == len(expected)
        for observed, reference in zip(actual, expected):
            assert max(abs(a - b) for a, b in zip(observed[:3], reference[:3])) <= 1
            assert observed[3] == reference[3]
        assert source.read_bytes() == before


@pytest.mark.parametrize(
    ("orientation", "expected"),
    [
        (1, [1, 2, 3, 4, 5, 6]),
        (2, [2, 1, 4, 3, 6, 5]),
        (3, [6, 5, 4, 3, 2, 1]),
        (4, [5, 6, 3, 4, 1, 2]),
        (5, [1, 3, 5, 2, 4, 6]),
        (6, [5, 3, 1, 6, 4, 2]),
        (7, [6, 4, 2, 5, 3, 1]),
        (8, [2, 4, 6, 1, 3, 5]),
    ],
)
def test_exif_orientations_are_normalized_explicitly(tmp_path, orientation, expected):
    source = tmp_path / f"orientation-{orientation}.png"
    source_pixels = [(value, value, value, 255) for value in range(1, 7)]
    _write_rgba_png(source, 2, 3, source_pixels, orientation=orientation)
    renderer = _renderer(tmp_path)

    result = _render(
        renderer,
        source,
        f"orientation-{orientation}.png",
        _resolution(mode="preset", preset="original"),
    )
    actual = _decode_rgba(result.artifact_path)

    expected_size = (3, 2) if orientation in {5, 6, 7, 8} else (2, 3)
    assert (result.width, result.height) == expected_size
    assert [pixel[0] for pixel in actual] == expected
    assert all(pixel[0] == pixel[1] == pixel[2] and pixel[3] == 255 for pixel in actual)
    assert _read_image_metadata(result.artifact_path) == (1, False)
    assert b"eXIf" not in result.artifact_path.read_bytes()


def test_unicode_paths_downscale_and_no_source_mutation(tmp_path):
    source = tmp_path / "输入-🎵.png"
    _write_solid_rgba_png(source, 1200, 600, (40, 100, 220, 93))
    before = source.read_bytes()
    renderer = _renderer(tmp_path)

    result = _render(
        renderer,
        source,
        "渲染/输出.png",
        _resolution(hex_color="#887A9B", intensity=0.6),
    )

    assert (result.width, result.height) == (1024, 512)
    assert result.artifact_path.is_file()
    assert source.read_bytes() == before


def test_animated_webp_and_explicit_profile_are_rejected(tmp_path):
    first = tmp_path / "frame-0.png"
    second = tmp_path / "frame-1.png"
    _write_rgba_png(first, 2, 1, [(255, 0, 0, 255), (0, 0, 0, 255)])
    _write_rgba_png(second, 2, 1, [(0, 255, 0, 255), (0, 0, 255, 255)])
    animated = tmp_path / "animated.webp"
    _run_ffmpeg(
        [
            "-framerate", "1", "-start_number", "0", "-i", str(tmp_path / "frame-%d.png"),
            "-frames:v", "2", "-c:v", "libwebp_anim", "-loop", "0", "-y", str(animated),
        ]
    )
    chunk_types = _webp_chunk_types(animated.read_bytes())
    assert b"VP8X" in chunk_types
    assert b"ANIM" in chunk_types
    assert chunk_types.count(b"ANMF") == 2
    renderer = _renderer(tmp_path)
    treatment = _resolution()

    with pytest.raises(MediaInfrastructureError) as animated_error:
        _render(renderer, animated, "animated.png", treatment)
    assert animated_error.value.code == "ANIMATED_IMAGE_UNSUPPORTED"

    profile = tmp_path / "profile.png"
    profile.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"iCCP", b"fixture-profile")
        + _chunk(b"IEND", b"")
    )
    with pytest.raises(MediaInfrastructureError) as profile_error:
        _render(renderer, profile, "profile.png", treatment)
    assert profile_error.value.code == "IMAGE_COLOR_PROFILE_UNSUPPORTED"


def test_real_timeout_pre_cancel_and_cleanup_leave_no_artifact(tmp_path):
    source = tmp_path / "timeout.png"
    _write_solid_rgba_png(source, 1200, 600, (80, 140, 200, 255))
    timed_renderer = _renderer(tmp_path / "timed", timeout_seconds=0.000001)

    with pytest.raises(MediaInfrastructureError) as timeout_error:
        _render(timed_renderer, source, "timeout.png", _resolution())
    assert timeout_error.value.code == "PROCESS_TIMEOUT"
    assert not (tmp_path / "timed" / "outputs" / "timeout.png").exists()
    assert list((tmp_path / "timed" / "outputs").glob("*.partial.png")) == []

    cancelled_renderer = _renderer(tmp_path / "cancelled")
    cancel_event = Event()
    cancel_event.set()
    with pytest.raises(MediaInfrastructureError) as cancellation_error:
        cancelled_renderer.render(
            StillRenderRequest(
                contract_version=STILL_RENDER_REQUEST_VERSION,
                source_path=source,
                output_relative_path="cancelled.png",
                resolution=_resolution(),
                renderer_version=STILL_RENDERER_VERSION,
            ),
            cancel_event,
        )
    assert cancellation_error.value.code == "PROCESS_CANCELLED"
    assert not (tmp_path / "cancelled" / "outputs" / "cancelled.png").exists()
    assert list((tmp_path / "cancelled" / "outputs").glob("*.partial.png")) == []


def test_renderer_repeats_identically_and_does_not_overwrite_existing_output(tmp_path):
    source = tmp_path / "source.png"
    _write_rgba_png(source, 2, 1, [(180, 100, 20, 255), (10, 80, 220, 200)])
    renderer = _renderer(tmp_path)
    treatment = _resolution(hex_color="#887A9B", intensity=0.3)

    first = _render(renderer, source, "repeat-a.png", treatment)
    second = _render(renderer, source, "repeat-b.png", treatment)
    assert _decode_rgba(first.artifact_path) == _decode_rgba(second.artifact_path)
    first.artifact_path.write_bytes(b"unrelated destination")
    with pytest.raises(MediaInfrastructureError) as raised:
        _render(renderer, source, "repeat-a.png", treatment)
    assert raised.value.code == "OUTPUT_COLLISION"
    assert first.artifact_path.read_bytes() == b"unrelated destination"


def test_renderer_rejects_corrupt_unsupported_oversized_and_escaping_inputs(tmp_path):
    renderer = _renderer(tmp_path)
    treatment = _resolution()
    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not a PNG")
    with pytest.raises(MediaInfrastructureError) as corrupt_error:
        _render(renderer, corrupt, "corrupt.png", treatment)
    assert corrupt_error.value.code in {"IMAGE_UNDECODABLE", "IMAGE_UNSUPPORTED_OR_CORRUPT"}

    unsupported = tmp_path / "source.gif"
    unsupported.write_bytes(b"GIF89a")
    with pytest.raises(MediaInfrastructureError) as unsupported_error:
        _render(renderer, unsupported, "unsupported.png", treatment)
    assert unsupported_error.value.code == "UNSUPPORTED_IMAGE_FORMAT"

    oversized = tmp_path / "large.png"
    with oversized.open("wb") as stream:
        stream.truncate(MAX_INPUT_BYTES + 1)
    with pytest.raises(MediaInfrastructureError) as size_error:
        _render(renderer, oversized, "large.png", treatment)
    assert size_error.value.code == "IMAGE_TOO_LARGE"

    valid = tmp_path / "valid.png"
    _write_rgba_png(valid, 1, 1, [(1, 2, 3, 4)])
    with pytest.raises(MediaInfrastructureError) as path_error:
        _render(renderer, valid, "../outside.png", treatment)
    assert path_error.value.code == "INVALID_OUTPUT_PATH"


def test_scaled_dimensions_respect_aspect_ratio_and_never_upscale():
    assert _scaled_dimensions(400, 200, 1024) == (400, 200)
    assert _scaled_dimensions(5000, 2500, 1024) == (1024, 512)
    assert _scaled_dimensions(1, 20000, 1024) == (1, 1024)
