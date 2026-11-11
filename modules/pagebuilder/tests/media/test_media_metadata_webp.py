"""WebP metadata is removed chunk by chunk, without re-encoding (#356).

Only a static WebP with an orientation to apply is re-encoded; everything else
keeps its compressed picture byte for byte, so a lossy WebP loses no quality.
"""

from __future__ import annotations

import io
import struct

import pytest
from fastapi import HTTPException
from pagebuilder.media import media_webp
from pagebuilder.media.media_metadata import clean_bytes
from pagebuilder.media.media_webp import is_lossless
from PIL import Image

from tests.support.metadata_images import (
    ICC,
    XMP,
    _exif,
    _service,
    _stored,
    _two_tone,
    _upload,
)

_EXIF_FLAG, _XMP_FLAG = 0x08, 0x04


def _riff(data: bytes) -> list[tuple[bytes, bytes]]:
    """``(type, payload)`` of each chunk, walked independently of the code."""
    out, offset = [], 12
    while offset < len(data):
        kind = data[offset : offset + 4]
        (length,) = struct.unpack("<I", data[offset + 4 : offset + 8])
        out.append((kind, data[offset + 8 : offset + 8 + length]))
        offset += 8 + length + (length & 1)
    return out


def _webp(*, animated: bool = False, orientation: int | None = None, **options) -> bytes:
    buf = io.BytesIO()
    meta = {"exif": _exif(orientation=orientation), "xmp": XMP, "icc_profile": ICC}
    if animated:
        frames = [Image.new("RGB", (10, 10), c) for c in ((255, 0, 0), (0, 255, 0))]
        frames[0].save(buf, format="WEBP", save_all=True, append_images=frames[1:],
                       duration=100, **meta, **options)
    else:
        _two_tone().save(buf, format="WEBP", **meta, **options)
    return buf.getvalue()


def _assert_only_metadata_went(original: bytes, cleaned: bytes) -> None:
    before, after = _riff(original), _riff(cleaned)
    assert {b"EXIF", b"XMP "} <= {kind for kind, _ in before}
    expected = [(k, p) for k, p in before if k not in (b"EXIF", b"XMP ")]
    # Every chunk but VP8X is the original's, in order; VP8X differs by its flags.
    assert [k for k, _ in after] == [k for k, _ in expected]
    for (kind, old), (_, new) in zip(expected, after, strict=True):
        if kind == b"VP8X":
            assert old[0] & (_EXIF_FLAG | _XMP_FLAG)
            assert new[0] == old[0] & ~(_EXIF_FLAG | _XMP_FLAG)
            assert new[1:] == old[1:]
        else:
            assert new == old
    (riff_size,) = struct.unpack("<I", cleaned[4:8])
    assert riff_size == len(cleaned) - 8


async def test_a_lossy_webp_keeps_its_picture_byte_for_byte(db, tmp_path):
    original = _webp(quality=80)
    asset, path = await _stored(_service(db, tmp_path), original, "image/webp", "a.webp")

    cleaned = path.read_bytes()
    assert b"SecretCam" not in cleaned and b"GPSLatitude" not in cleaned
    _assert_only_metadata_went(original, cleaned)
    assert not is_lossless(cleaned)
    with Image.open(path) as image:
        assert image.info["icc_profile"] == ICC
        assert len(image.getexif()) == 0
    assert asset.size_bytes == len(cleaned)


async def test_an_animated_webp_keeps_every_frame_byte_for_byte(db, tmp_path):
    original = _webp(animated=True, orientation=6)
    asset, path = await _stored(_service(db, tmp_path), original, "image/webp", "loop.webp")

    cleaned = path.read_bytes()
    assert b"SecretCam" not in cleaned
    _assert_only_metadata_went(original, cleaned)
    with Image.open(path) as image:
        assert image.n_frames == 2 and image.size == (10, 10)  # not turned
    assert asset.size_bytes == len(cleaned)


async def test_a_turned_static_webp_is_re_encoded_upright(db, tmp_path):
    original = _webp(orientation=6, lossless=True)
    _asset, path = await _stored(_service(db, tmp_path), original, "image/webp", "t.webp")

    assert b"SecretCam" not in path.read_bytes()
    assert is_lossless(path.read_bytes())
    with Image.open(path) as image:
        assert image.size == (20, 40)
        assert image.convert("RGB").getpixel((10, 5)) == (255, 0, 0)


def test_a_clean_webp_is_left_as_it_is():
    buf = io.BytesIO()
    _two_tone().save(buf, format="WEBP", quality=80)
    assert clean_bytes(buf.getvalue(), "image/webp") is None


def _with_riff_size(data: bytes, size: int) -> bytes:
    return data[:4] + struct.pack("<I", size) + data[8:]


def _malformed() -> list[bytes]:
    good = _webp(quality=80)
    # A chunk header claiming more bytes than the RIFF holds, sized to fit.
    overlong = good + b"EXIF" + struct.pack("<I", 1000) + b"\x00" * 8
    return [
        _with_riff_size(overlong, len(overlong) - 8),
        _with_riff_size(good, len(good)),  # RIFF size past the end of the file
        _with_riff_size(good + b"\x00", len(good) - 7),  # odd RIFF size
    ]


@pytest.mark.parametrize("index", range(3), ids=["overlong-chunk", "riff-past-end", "odd-size"])
async def test_a_malformed_riff_is_refused_not_stored(db, tmp_path, index):
    service = _service(db, tmp_path)
    with pytest.raises(HTTPException) as refused:
        await service.upload(_upload(_malformed()[index], "image/webp", "bad.webp"))
    assert refused.value.status_code == 415
    assert refused.value.detail["code"] == "image_metadata_not_removed"
    assert list(service.tenant_dir().iterdir()) == []


@pytest.mark.parametrize("index", range(3), ids=["overlong-chunk", "riff-past-end", "odd-size"])
def test_the_riff_walk_refuses_what_the_decoder_also_refuses(index):
    """The chunk copy checks the container itself, not only through Pillow."""
    with pytest.raises(media_webp.WebpStructureError):
        media_webp.strip_chunks(_malformed()[index])


def test_bytes_after_the_riff_are_dropped():
    good = _webp(quality=80)
    cleaned = media_webp.strip_chunks(good + b"EXIF" + struct.pack("<I", 4) + b"Jane")
    assert cleaned is not None and b"Jane" not in cleaned
    assert len(cleaned) == 8 + struct.unpack("<I", cleaned[4:8])[0]


def _with_frame_chunk(data: bytes, extra: bytes) -> bytes:
    """*data* with *extra* appended inside its first ANMF frame, sizes fixed."""
    offset = 12
    while data[offset : offset + 4] != b"ANMF":
        (length,) = struct.unpack("<I", data[offset + 4 : offset + 8])
        offset += 8 + length + (length & 1)
    (length,) = struct.unpack("<I", data[offset + 4 : offset + 8])
    stop = offset + 8 + length
    frame = b"ANMF" + struct.pack("<I", length + len(extra)) + data[offset + 8 : stop] + extra
    out = data[:offset] + frame + data[stop:]
    return out[:4] + struct.pack("<I", len(out) - 8) + out[8:]


async def test_metadata_hidden_inside_an_animation_frame_is_removed(db, tmp_path):
    plain = _webp(animated=True)
    hidden = b"EXIF" + struct.pack("<I", 10) + b"GPSSecret!"
    original = _with_frame_chunk(plain, hidden)
    with Image.open(io.BytesIO(original)) as probe:
        assert probe.n_frames == 2  # the decoder skips it, so it would be published
    _asset, path = await _stored(_service(db, tmp_path), original, "image/webp", "loop.webp")

    cleaned = path.read_bytes()
    assert b"GPSSecret" not in cleaned
    assert media_webp.strip_chunks(plain) is not None  # top-level EXIF/XMP go too
    assert cleaned == media_webp.strip_chunks(plain)  # frames exactly as without it


def test_a_frame_whose_chunks_do_not_parse_is_refused():
    broken = _with_frame_chunk(_webp(animated=True), b"EXIF" + struct.pack("<I", 99) + b"xx")
    with pytest.raises(media_webp.WebpStructureError):
        media_webp.strip_chunks(broken)
