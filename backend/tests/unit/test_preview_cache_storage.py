import struct
import threading
import zlib
from dataclasses import FrozenInstanceError

import pytest

from wrld_video_studio.application.ports.preview_cache import (
    PREVIEW_CACHE_MANIFEST_VERSION,
    CachedPreviewArtifact,
    PreviewCacheError,
)
from wrld_video_studio.domain.color_resolution import INPUT_CONTRACT_VERSION, resolve_color_treatment
from wrld_video_studio.domain.preview_cache import PreviewToolchainIdentity, build_preview_cache_identity
from wrld_video_studio.infrastructure import preview_cache as adapter


def _identity():
    resolution = resolve_color_treatment(
        {
            "contract_version": INPUT_CONTRACT_VERSION,
            "treatment": {"mode": "custom", "hex": "#ABCDEF", "intensity": 0.3},
        }
    )
    return build_preview_cache_identity(
        source_sha256="3" * 64,
        resolution=resolution,
        toolchain=PreviewToolchainIdentity.create(
            ffmpeg_sha256="5" * 64,
            ffprobe_sha256="6" * 64,
        ),
    )


def _chunk(name, data):
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)


def _png(*, filter_byte=0, trailing=b"", width=2, height=2):
    pixels = b"".join(bytes([filter_byte]) + b"\x01\x02\x03" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(pixels) + trailing)
        + _chunk(b"IEND", b"")
    )


def test_port_metadata_is_immutable_and_manifest_version_is_private():
    value = CachedPreviewArtifact("a" * 64, "b" * 64, 10, 2, 3)
    with pytest.raises(FrozenInstanceError):
        value.width = 4
    assert PREVIEW_CACHE_MANIFEST_VERSION == "preview-cache-entry-v1"


def test_png_validation_checks_encoding_dimensions_filters_and_deflate_stream():
    assert adapter._validate_png(_png()) == (2, 2)
    with pytest.raises(ValueError):
        adapter._validate_png(_png(filter_byte=5))
    with pytest.raises(ValueError):
        adapter._validate_png(_png(trailing=b"not-deflate"))
    with pytest.raises(ValueError):
        adapter._validate_png(_png(width=1025))


def test_png_rejects_large_or_repeated_ihdr_before_reading_declared_body():
    signature = b"\x89PNG\r\n\x1a\n"
    declared_length = 64 * 1024 * 1024
    prefix = signature + struct.pack(">I", declared_length) + b"IHDR"
    position = 0

    def seek(offset, whence=0):
        nonlocal position
        assert whence == 0
        position = offset
        return position

    def read(amount=-1):
        nonlocal position
        if amount < 0:
            amount = declared_length + 20 - position
        end = min(position + amount, len(prefix))
        value = prefix[position:end]
        position = end
        return value

    reader = adapter._Reader(
        identity=(0, 0),
        size=declared_length + 20,
        links=1,
        read=read,
        seek=seek,
        close=lambda: None,
    )
    with pytest.raises(ValueError, match="IHDR"):
        adapter._inspect_png_reader(reader, reader.size, None)
    assert position == len(prefix)

    valid_ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    repeated = signature + valid_ihdr + struct.pack(">I", declared_length) + b"IHDR"
    stream_position = 0

    def repeated_seek(offset, whence=0):
        nonlocal stream_position
        assert whence == 0
        stream_position = offset
        return stream_position

    def repeated_read(amount=-1):
        nonlocal stream_position
        if amount < 0:
            amount = declared_length + len(repeated) + 4 - stream_position
        end = min(stream_position + amount, len(repeated))
        value = repeated[stream_position:end]
        stream_position = end
        return value

    repeated_reader = adapter._Reader(
        identity=(0, 0),
        size=declared_length + len(repeated) + 4,
        links=1,
        read=repeated_read,
        seek=repeated_seek,
        close=lambda: None,
    )
    with pytest.raises(ValueError, match="multiple IHDR"):
        adapter._inspect_png_reader(repeated_reader, repeated_reader.size, None)
    assert stream_position == len(repeated)


def test_png_accepts_valid_supported_palette_and_non_palette_rgb():
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = _chunk(b"IDAT", zlib.compress(b"\x00\x01\x02\x03"))
    iend = _chunk(b"IEND", b"")
    assert adapter._validate_png(b"\x89PNG\r\n\x1a\n" + ihdr + idat + iend) == (1, 1)
    assert adapter._validate_png(
        b"\x89PNG\r\n\x1a\n" + ihdr + _chunk(b"PLTE", b"\x00\x00\x00") + idat + iend
    ) == (1, 1)


@pytest.mark.parametrize(
    "chunks",
    [
        (b"IDAT", b"PLTE"),
        (b"PLTE", b"PLTE", b"IDAT"),
        (b"BAD_PLTE", b"IDAT"),
        (b"abca", b"IDAT"),
    ],
    ids=["palette-after-idat", "duplicate-palette", "invalid-palette-length", "reserved-bit"],
)
def test_png_rejects_invalid_palette_and_reserved_chunk_names(chunks):
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = _chunk(b"IDAT", zlib.compress(b"\x00\x01\x02\x03"))
    parts = [b"\x89PNG\r\n\x1a\n", ihdr]
    for name in chunks:
        if name == b"IDAT":
            parts.append(idat)
        elif name == b"PLTE":
            parts.append(_chunk(name, b"\x00\x00\x00"))
        elif name == b"BAD_PLTE":
            parts.append(_chunk(b"PLTE", b"\x00\x00\x00\x00"))
        else:
            parts.append(_chunk(name, b""))
    parts.append(_chunk(b"IEND", b""))
    with pytest.raises(ValueError):
        adapter._validate_png(b"".join(parts))


def test_manifest_contains_only_pixel_identity_and_verified_artifact_metadata():
    identity = _identity()
    manifest = adapter._manifest(identity, "9" * 64, 80, 2, 2)
    adapter._validate_manifest_structure(manifest)
    assert set(manifest) == {"contract_version", "preview_id", "descriptor", "artifact"}
    serialized = repr(manifest)
    assert "input_fingerprint" not in serialized
    assert "reason" not in serialized
    assert "source" not in manifest["descriptor"]


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.update(extra=True),
        lambda value: value["artifact"].update(width=True),
        lambda value: value["descriptor"]["treatment"].update(resolver_version="forged"),
        lambda value: value["descriptor"]["render_policy"].update(scale_filter="forged"),
        lambda value: value["descriptor"]["toolchain"].update(ffmpeg_sha256="UPPER" * 12 + "ABCD"),
    ],
)
def test_manifest_descriptor_validation_is_strict(change):
    identity = _identity()
    manifest = adapter._manifest(identity, "9" * 64, 80, 2, 2)
    change(manifest)
    with pytest.raises(ValueError):
        adapter._validate_manifest_structure(manifest)


def test_cancellation_uses_typed_path_safe_error():
    event = threading.Event()
    event.set()
    with pytest.raises(PreviewCacheError) as raised:
        adapter._raise_if_cancelled(event)
    assert raised.value.code == "PREVIEW_CANCELLED"
    assert "\\" not in raised.value.message


def test_untrusted_identity_is_rejected_before_filesystem_access(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    with adapter.SecureFilesystemPreviewCache(root) as cache:
        with pytest.raises(TypeError):
            cache.lookup(object())
