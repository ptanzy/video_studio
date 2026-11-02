from __future__ import annotations

import hashlib
import json
import struct
import zlib
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wrld_video_studio.application.ports.still_images import (
    STILL_RENDER_REQUEST_VERSION,
    STILL_RENDERER_VERSION,
    StillRenderRequest,
)
from wrld_video_studio.domain.color_resolution import (
    INPUT_CONTRACT_VERSION,
    resolve_color_treatment,
)
from wrld_video_studio.domain.color_transform import TRANSFORM_VERSION
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.infrastructure.artwork_sources import (
    ArtworkSourceRegistration,
    TrustedArtworkRoot,
)
from wrld_video_studio.infrastructure.media_tools import MediaToolchain
from wrld_video_studio.infrastructure.preview_context import PreviewContextRegistration
from wrld_video_studio.infrastructure.process_runner import SubprocessRunner
from wrld_video_studio.infrastructure.still_image_renderer import FFmpegStillImageRenderer
from wrld_video_studio.interfaces.http.app import PreviewApplicationConfig, create_app


pytestmark = pytest.mark.integration_ffmpeg


def _chunk(name: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + name
        + data
        + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
    )


def _rgba_png(width, height, pixels, *, orientation=None):
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


def _solid_png(width, height, pixel):
    return _rgba_png(width, height, [pixel] * (width * height))


def _tools():
    runner = SubprocessRunner()
    tools = MediaToolchain(runner)
    try:
        return runner, tools.resolve("ffmpeg").path, tools.resolve("ffprobe").path
    except MediaInfrastructureError as error:
        if error.code == "MEDIA_TOOL_MISSING":
            pytest.skip(f"FFmpeg preview tools unavailable: {error.code}: {error.message}")
        raise


def _run_ffmpeg(runner, ffmpeg, arguments):
    result = runner.run(
        [str(ffmpeg), "-hide_banner", "-nostdin", "-v", "error", *arguments],
        timeout_seconds=30,
    )
    assert result.returncode == 0, result.stderr_tail


def _decode_rgba(runner, ffmpeg, png_bytes, root, name):
    source = root / f"{name}.png"
    output = root / f"{name}.rgba"
    source.write_bytes(png_bytes)
    _run_ffmpeg(
        runner,
        ffmpeg,
        ["-i", str(source), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-y", str(output)],
    )
    return output.read_bytes()


def _parse(response):
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {response.headers['content-type']}\r\nMIME-Version: 1.0\r\n\r\n".encode()
        + response.content
    )
    parts = list(message.iter_parts())
    assert [part.get_content_type() for part in parts] == ["application/json", "image/png"]
    return json.loads(parts[0].get_payload(decode=True)), parts[1].get_payload(decode=True)


def _payload(asset_id, treatment):
    return {
        "contract_version": "preview-request-v1",
        "target": {"album_id": "Album", "artwork_asset_id": asset_id},
        "treatment": treatment,
        "variant": "authoritative_still",
    }


def test_complete_http_pipeline_real_media_and_direct_phase2_equivalence(tmp_path):
    runner, ffmpeg, ffprobe = _tools()
    source_root = tmp_path / "sources"
    snapshot_root = tmp_path / "snapshots"
    cache_root = tmp_path / "cache"
    direct_root = tmp_path / "direct"
    for directory in (source_root, snapshot_root, cache_root, direct_root):
        directory.mkdir()

    sources = {
        "alpha.png": _rgba_png(2, 1, [(20, 80, 140, 255), (220, 30, 10, 73)]),
        "oriented.png": _rgba_png(
            2, 3, [(value, value, value, 255) for value in range(1, 7)], orientation=6
        ),
        "large.png": _solid_png(1200, 600, (40, 100, 220, 93)),
        "auto.png": _solid_png(3, 2, (100, 120, 140, 255)),
    }
    for name, value in sources.items():
        (source_root / name).write_bytes(value)
    seed = source_root / "seed.png"
    seed.write_bytes(_solid_png(3, 2, (20, 90, 170, 255)))
    for extension in ("jpg", "webp"):
        destination = source_root / f"encoded.{extension}"
        arguments = ["-i", str(seed), "-frames:v", "1"]
        if extension == "jpg":
            arguments += ["-c:v", "mjpeg", "-q:v", "1", "-pix_fmt", "yuvj444p"]
        else:
            arguments += ["-c:v", "libwebp", "-lossless", "1", "-pix_fmt", "yuva420p"]
        _run_ffmpeg(runner, ffmpeg, [*arguments, "-y", str(destination)])
        sources[destination.name] = destination.read_bytes()

    registrations = tuple(
        ArtworkSourceRegistration("Album", asset_id, "main", filename)
        for asset_id, filename in {
            "alpha": "alpha.png",
            "oriented": "oriented.png",
            "large": "large.png",
            "jpeg": "encoded.jpg",
            "webp": "encoded.webp",
            "auto": "auto.png",
        }.items()
    )
    contexts = tuple(
        PreviewContextRegistration(
            "Album",
            registration.artwork_asset_id,
            {"album_palette": [{"hex": "#71869A"}]}
            if registration.artwork_asset_id == "auto"
            else {},
        )
        for registration in registrations
    )
    config = PreviewApplicationConfig(
        artwork_roots=(TrustedArtworkRoot("main", source_root),),
        artwork_registrations=registrations,
        context_registrations=contexts,
        snapshot_root=snapshot_root,
        cache_root=cache_root,
        ffmpeg_path=ffmpeg,
        ffprobe_path=ffprobe,
        preview_wait_timeout_seconds=20.0,
        preview_render_timeout_seconds=30.0,
        shutdown_timeout_seconds=10.0,
    )
    source_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_root.iterdir()
    }
    custom = {"mode": "custom", "hex": "#887A9B", "intensity": 0.6}

    with TestClient(create_app(config)) as client:
        first_response = client.post("/api/v1/previews/still", json=_payload("alpha", custom))
        second_response = client.post("/api/v1/previews/still", json=_payload("alpha", custom))
        first, first_png = _parse(first_response)
        second, second_png = _parse(second_response)
        assert first["cache_status"] == "miss"
        assert second["cache_status"] == "hit"
        assert first["preview_id"] == second["preview_id"]
        assert first_png == second_png
        assert _decode_rgba(runner, ffmpeg, first_png, tmp_path, "http-alpha")[3::4] == bytes((255, 73))

        resolution = resolve_color_treatment(
            {"contract_version": INPUT_CONTRACT_VERSION, "treatment": custom}
        )
        direct = FFmpegStillImageRenderer(
            MediaToolchain(runner), runner, direct_root
        ).render(
            StillRenderRequest(
                contract_version=STILL_RENDER_REQUEST_VERSION,
                source_path=source_root / "alpha.png",
                output_relative_path="direct.png",
                resolution=resolution,
                renderer_version=STILL_RENDERER_VERSION,
                transform_version=TRANSFORM_VERSION,
            )
        )
        assert _decode_rgba(runner, ffmpeg, first_png, tmp_path, "http") == _decode_rgba(
            runner, ffmpeg, direct.artifact_path.read_bytes(), tmp_path, "direct"
        )

        original = {"mode": "preset", "preset": "original", "intensity": 0.0}
        for asset_id in ("jpeg", "webp"):
            result, _png = _parse(
                client.post("/api/v1/previews/still", json=_payload(asset_id, original))
            )
            assert result["media_type"] == "image/png"
            assert (result["width"], result["height"]) == (3, 2)

        oriented, _ = _parse(
            client.post("/api/v1/previews/still", json=_payload("oriented", original))
        )
        assert (oriented["width"], oriented["height"]) == (3, 2)
        large, _ = _parse(
            client.post("/api/v1/previews/still", json=_payload("large", original))
        )
        assert (large["width"], large["height"]) == (1024, 512)
        auto, _ = _parse(
            client.post(
                "/api/v1/previews/still",
                json=_payload("auto", {"mode": "auto", "intensity": 0.3}),
            )
        )
        assert auto["treatment"]["resolved_hex"] == "#71869A"
        assert auto["treatment"]["source"] == "album_palette"
        zero, zero_png = _parse(
            client.post(
                "/api/v1/previews/still",
                json=_payload("auto", {"mode": "custom", "hex": "#000000", "intensity": 0.0}),
            )
        )
        assert (zero["width"], zero["height"]) == (3, 2)
        assert _decode_rgba(runner, ffmpeg, zero_png, tmp_path, "zero") == bytes(
            [100, 120, 140, 255] * 6
        )

    assert list(snapshot_root.iterdir()) == []
    assert {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_root.iterdir()
    } == source_hashes
