from __future__ import annotations

import hashlib
import struct
import threading
import zlib
from pathlib import Path

import pytest

from wrld_video_studio.application.preview_service import (
    AuthoritativePreviewService,
    PreviewServiceError,
)
from wrld_video_studio.application.ports.still_images import (
    STILL_RENDER_REQUEST_VERSION,
    STILL_RENDERER_VERSION,
    StillRenderRequest,
)
from wrld_video_studio.application.render_coordination import (
    PreviewSingleFlightCoordinator,
    ProcessLocalRenderAdmission,
)
from wrld_video_studio.domain.color_resolution import (
    INPUT_CONTRACT_VERSION,
    resolve_color_treatment,
)
from wrld_video_studio.domain.color_transform import TRANSFORM_VERSION
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.preview_cache import PreviewRequest
from wrld_video_studio.infrastructure.artwork_sources import (
    ArtworkSourceRegistration,
    ImmutableArtworkRegistry,
    SecureFilesystemArtworkSourceResolver,
    TrustedArtworkRoot,
)
from wrld_video_studio.infrastructure.media_tools import MediaToolchain
from wrld_video_studio.infrastructure.preview_cache import SecureFilesystemPreviewCache
from wrld_video_studio.infrastructure.preview_toolchain import VerifiedFFmpegPreviewBackend
from wrld_video_studio.infrastructure.process_runner import SubprocessRunner
from wrld_video_studio.infrastructure.still_image_renderer import FFmpegStillImageRenderer


pytestmark = pytest.mark.integration_ffmpeg


@pytest.fixture(scope="module", autouse=True)
def require_ffmpeg_toolchain() -> None:
    runner = SubprocessRunner()
    tools = MediaToolchain(runner)
    try:
        tools.resolve("ffmpeg")
        tools.resolve("ffprobe")
    except MediaInfrastructureError as error:
        if error.code == "MEDIA_TOOL_MISSING":
            pytest.skip(f"FFmpeg preview tools unavailable: {error.code}: {error.message}")
        raise


def _chunk(name: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + name
        + data
        + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
    )


def _rgba_png(
    width: int,
    height: int,
    pixels: list[tuple[int, int, int, int]],
    *,
    orientation: int | None = None,
) -> bytes:
    rows = bytearray()
    for row in range(height):
        rows.append(0)
        for pixel in pixels[row * width : (row + 1) * width]:
            rows.extend(pixel)
    extra = b""
    if orientation is not None:
        tiff = (
            b"II\x2a\x00\x08\x00\x00\x00\x01\x00"
            b"\x12\x01\x03\x00\x01\x00\x00\x00"
            + orientation.to_bytes(2, "little")
            + b"\x00\x00\x00\x00\x00\x00"
        )
        extra = _chunk(b"eXIf", tiff)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + extra
        + _chunk(b"IDAT", zlib.compress(bytes(rows), level=9))
        + _chunk(b"IEND", b"")
    )


def _solid_png(width: int, height: int, pixel: tuple[int, int, int, int]) -> bytes:
    return _rgba_png(width, height, [pixel] * (width * height))


def _request(treatment: dict[str, object]) -> PreviewRequest:
    return PreviewRequest.from_dict(
        {
            "contract_version": "preview-request-v1",
            "target": {"album_id": "Album", "artwork_asset_id": "cover"},
            "treatment": treatment,
            "variant": "authoritative_still",
        }
    )


def _resolution(treatment: dict[str, object], context=None):
    value = {"contract_version": INPUT_CONTRACT_VERSION, "treatment": treatment}
    if context is not None:
        value["context"] = context
    return resolve_color_treatment(value)


class _PreviewFixture:
    def __init__(self, tmp_path: Path, source_name: str, source_bytes: bytes, *, timeout=30.0):
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.source_root = tmp_path / "sources"
        self.snapshot_root = tmp_path / "snapshots"
        self.cache_root = tmp_path / "cache"
        for directory in (self.source_root, self.snapshot_root, self.cache_root):
            directory.mkdir()
        self.source = self.source_root / source_name
        self.source.write_bytes(source_bytes)
        registry = ImmutableArtworkRegistry(
            [TrustedArtworkRoot("main", self.source_root)],
            [ArtworkSourceRegistration("Album", "cover", "main", source_name)],
        )
        self.resolver = SecureFilesystemArtworkSourceResolver(registry, self.snapshot_root)
        self.cache = SecureFilesystemPreviewCache(self.cache_root)
        self.coordinator = PreviewSingleFlightCoordinator(
            ProcessLocalRenderAdmission(), wait_timeout_seconds=10
        )
        runner = SubprocessRunner()
        self.backend = VerifiedFFmpegPreviewBackend(
            MediaToolchain(runner), runner, render_timeout_seconds=timeout
        )
        self.service = AuthoritativePreviewService(
            source_resolver=self.resolver,
            cache_store=self.cache,
            flight_coordinator=self.coordinator,
            render_backend=self.backend,
        )

    def close(self):
        self.coordinator.close(timeout_seconds=5)
        self.cache.close()


def _run_ffmpeg(arguments: list[str]) -> None:
    runner = SubprocessRunner()
    ffmpeg = MediaToolchain(runner).resolve("ffmpeg").path
    result = runner.run(
        [str(ffmpeg), "-hide_banner", "-nostdin", "-v", "error", *arguments],
        timeout_seconds=30,
    )
    assert result.returncode == 0, result.stderr_tail


def _decode_rgba(png_bytes: bytes, tmp_path: Path) -> bytes:
    source = tmp_path / "decode.png"
    output = tmp_path / "decode.rgba"
    source.write_bytes(png_bytes)
    _run_ffmpeg(
        ["-i", str(source), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-y", str(output)]
    )
    return output.read_bytes()


def test_real_preview_first_miss_then_verified_hit_preserves_source_and_alpha(tmp_path):
    source_bytes = _rgba_png(
        2,
        1,
        [(20, 80, 140, 255), (220, 30, 10, 73)],
    )
    fixture = _PreviewFixture(tmp_path, "cover.png", source_bytes)
    treatment = {"mode": "custom", "hex": "#887A9B", "intensity": 0.6}
    request = _request(treatment)
    resolution = _resolution(treatment)
    try:
        first = fixture.service.execute(request, resolution)
        first_bytes = first.artifact.read()
        first_result = first.result
        first.close()
        second = fixture.service.execute(request, resolution)
        second_bytes = second.artifact.read()
        second_result = second.result
        second.close()

        assert first_result.cache_status == "miss"
        assert second_result.cache_status == "hit"
        assert first_result.preview_id == second_result.preview_id
        assert first_result.artifact_sha256 == hashlib.sha256(first_bytes).hexdigest()
        assert first_bytes == second_bytes
        assert _decode_rgba(first_bytes, tmp_path)[3::4] == bytes((255, 73))
        assert fixture.source.read_bytes() == source_bytes
        assert list(fixture.snapshot_root.iterdir()) == []
    finally:
        fixture.close()


@pytest.mark.parametrize("extension", ["jpg", "webp"])
def test_real_preview_accepts_supported_decoded_formats(tmp_path, extension):
    seed = tmp_path / "seed.png"
    seed.write_bytes(_solid_png(3, 2, (20, 90, 170, 255)))
    encoded = tmp_path / f"encoded.{extension}"
    arguments = ["-i", str(seed), "-frames:v", "1"]
    if extension == "jpg":
        arguments += ["-c:v", "mjpeg", "-q:v", "1", "-pix_fmt", "yuvj444p"]
    else:
        arguments += ["-c:v", "libwebp", "-lossless", "1", "-pix_fmt", "yuva420p"]
    _run_ffmpeg([*arguments, "-y", str(encoded)])
    fixture = _PreviewFixture(tmp_path / "service", f"cover.{extension}", encoded.read_bytes())
    treatment = {"mode": "preset", "preset": "original", "intensity": 0.6}
    try:
        prepared = fixture.service.execute(_request(treatment), _resolution(treatment))
        assert prepared.result.cache_status == "miss"
        assert prepared.result.media_type == "image/png"
        prepared.close()
    finally:
        fixture.close()


def test_real_preview_normalizes_orientation_and_downscales(tmp_path):
    oriented = _rgba_png(
        2,
        3,
        [(value, value, value, 255) for value in range(1, 7)],
        orientation=6,
    )
    fixture = _PreviewFixture(tmp_path / "orientation", "cover.png", oriented)
    treatment = {"mode": "preset", "preset": "original", "intensity": 0.0}
    try:
        prepared = fixture.service.execute(_request(treatment), _resolution(treatment))
        assert (prepared.result.width, prepared.result.height) == (3, 2)
        prepared.close()
    finally:
        fixture.close()

    large = _solid_png(1200, 600, (40, 100, 220, 93))
    fixture = _PreviewFixture(tmp_path / "downscale", "cover.png", large)
    try:
        prepared = fixture.service.execute(_request(treatment), _resolution(treatment))
        assert (prepared.result.width, prepared.result.height) == (1024, 512)
        prepared.close()
    finally:
        fixture.close()


def test_real_preview_treatment_identities_cover_preset_custom_black_and_zero(tmp_path):
    source = _solid_png(2, 2, (100, 120, 140, 255))
    fixture = _PreviewFixture(tmp_path, "cover.png", source)
    treatments = [
        {"mode": "preset", "preset": "warm", "intensity": 0.3},
        {"mode": "custom", "hex": "#123456", "intensity": 0.4},
        {"mode": "custom", "hex": "#000000", "intensity": 0.6},
        {"mode": "custom", "hex": "#123456", "intensity": 0.0},
        {"mode": "preset", "preset": "original", "intensity": 0.0},
    ]
    try:
        results = []
        for treatment in treatments:
            prepared = fixture.service.execute(_request(treatment), _resolution(treatment))
            results.append(prepared.result)
            prepared.close()
        assert len({result.preview_id for result in results}) == len(results)
    finally:
        fixture.close()


@pytest.mark.parametrize(
    ("case", "treatment", "width", "height", "pixel"),
    [
        (
            "preset-alpha",
            {"mode": "preset", "preset": "warm", "intensity": 0.3},
            3,
            2,
            (20, 90, 170, 73),
        ),
        (
            "custom",
            {"mode": "custom", "hex": "#123456", "intensity": 0.4},
            3,
            2,
            (100, 120, 140, 255),
        ),
        (
            "zero-intensity",
            {"mode": "custom", "hex": "#ABCDEF", "intensity": 0.0},
            3,
            2,
            (35, 80, 210, 255),
        ),
        (
            "downscaled",
            {"mode": "preset", "preset": "original", "intensity": 0.0},
            1200,
            600,
            (40, 100, 220, 93),
        ),
    ],
)
def test_service_decoded_pixels_match_direct_phase2_rendering(
    tmp_path, case, treatment, width, height, pixel
):
    source_bytes = _solid_png(width, height, pixel)
    fixture = _PreviewFixture(tmp_path / "service", "cover.png", source_bytes)
    resolution = _resolution(treatment)
    direct_root = tmp_path / "direct"
    direct_root.mkdir()
    runner = SubprocessRunner()
    direct_renderer = FFmpegStillImageRenderer(
        MediaToolchain(runner), runner, direct_root
    )
    prepared = None
    try:
        direct = direct_renderer.render(
            StillRenderRequest(
                contract_version=STILL_RENDER_REQUEST_VERSION,
                source_path=fixture.source,
                output_relative_path=f"{case}.png",
                resolution=resolution,
                renderer_version=STILL_RENDERER_VERSION,
                transform_version=TRANSFORM_VERSION,
            )
        )
        prepared = fixture.service.execute(_request(treatment), resolution)
        service_bytes = prepared.artifact.read()

        assert (prepared.result.width, prepared.result.height) == (
            direct.width,
            direct.height,
        )
        assert _decode_rgba(service_bytes, tmp_path) == _decode_rgba(
            direct.artifact_path.read_bytes(), tmp_path
        )
        assert fixture.source.read_bytes() == source_bytes
    finally:
        if prepared is not None:
            prepared.close()
        fixture.close()


def test_real_preview_unsupported_cancellation_and_timeout_are_typed_and_clean(tmp_path):
    corrupt = _PreviewFixture(tmp_path / "corrupt", "cover.png", b"not a png")
    original = {"mode": "preset", "preset": "original", "intensity": 0.0}
    try:
        with pytest.raises(PreviewServiceError) as unsupported:
            corrupt.service.execute(_request(original), _resolution(original))
        assert unsupported.value.code == "PREVIEW_IMAGE_UNSUPPORTED"
        assert str(corrupt.source) not in unsupported.value.message
        assert list(corrupt.snapshot_root.iterdir()) == []
    finally:
        corrupt.close()

    valid = _solid_png(1200, 600, (80, 140, 200, 255))
    cancelled = _PreviewFixture(tmp_path / "cancelled", "cover.png", valid)
    signal = threading.Event()
    signal.set()
    try:
        with pytest.raises(PreviewServiceError) as cancellation:
            cancelled.service.execute(_request(original), _resolution(original), signal)
        assert cancellation.value.code == "PREVIEW_CANCELLED"
        assert list(cancelled.snapshot_root.iterdir()) == []
    finally:
        cancelled.close()

    timed = _PreviewFixture(tmp_path / "timed", "cover.png", valid, timeout=0.000001)
    try:
        with pytest.raises(PreviewServiceError) as timeout:
            timed.service.execute(_request(original), _resolution(original))
        assert timeout.value.code == "PREVIEW_TIMEOUT"
        assert list(timed.snapshot_root.iterdir()) == []
        assert list((timed.cache_root / ".preview-cache-staging").iterdir()) == []
    finally:
        timed.close()
