"""PNG metadata is removed chunk by chunk, losslessly, and fails closed (#356).

Split from ``test_media_metadata.py`` for the 300-line cap.
"""

from __future__ import annotations

import io
import struct
import zlib

import pytest
from fastapi import HTTPException
from pagebuilder.media import media_png
from PIL import Image

from tests.support.metadata_images import (
    ORIENTATION,
    _chunk,
    _service,
    _stored,
    _two_tone,
    _upload,
)


def _png16_with_text() -> bytes:
    """A 2x1 16-bit RGB PNG (Pillow cannot write one) with a tEXt and a tIME chunk."""
    ihdr = struct.pack(">IIBBBBB", 2, 1, 16, 2, 0, 0, 0)
    row = b"\x00" + struct.pack(">6H", 0x1234, 0xABCD, 0x0001, 0xFFFE, 0x8000, 0x7FFF)
    return (
        media_png.PNG_SIGNATURE
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"tEXt", b"Author\x00Jane Example")
        + _chunk(b"tIME", b"\x07\xea\x0b\x0b\x0c\x00\x00")
        + _chunk(b"IDAT", zlib.compress(row))
        + _chunk(b"IEND", b"")
    )


async def test_a_16_bit_png_keeps_its_depth_and_pixels_exactly(db, tmp_path):
    original = _png16_with_text()
    asset, path = await _stored(_service(db, tmp_path), original, "image/png", "deep.png")

    cleaned = path.read_bytes()
    assert b"Jane Example" not in cleaned and b"tIME" not in cleaned
    assert media_png.bit_depth(cleaned) == 16
    # Every chunk that draws the picture is byte for byte the original's.
    assert cleaned == original.replace(_chunk(b"tEXt", b"Author\x00Jane Example"), b"").replace(
        _chunk(b"tIME", b"\x07\xea\x0b\x0b\x0c\x00\x00"), b""
    )
    assert asset.size_bytes == len(cleaned)


async def test_a_png_without_metadata_chunks_is_left_byte_for_byte(db, tmp_path):
    buf = io.BytesIO()
    _two_tone().convert("P").save(buf, format="PNG", transparency=0)
    original = buf.getvalue()
    _asset, path = await _stored(_service(db, tmp_path), original, "image/png", "p.png")
    assert path.read_bytes() == original


async def test_a_turned_8_bit_png_keeps_its_colour_chunks(db, tmp_path):
    """Orientation 6 is applied, and gAMA, cHRM, sRGB and pHYs survive the re-save."""
    exif = Image.Exif()
    exif[ORIENTATION] = 6
    exif_body = exif.tobytes().removeprefix(b"Exif\x00\x00")
    gama = _chunk(b"gAMA", struct.pack(">I", 45455))
    chrm = _chunk(b"cHRM", struct.pack(">8I", 31270, 32900, 64000, 33000, 30000, 60000,
                                       15000, 6000))
    srgb = _chunk(b"sRGB", b"\x00")
    rows = b"".join(b"\x00" + (b"\xff\x00\x00" * 2 + b"\x00\x00\xff" * 2) for _ in range(2))
    original = (
        media_png.PNG_SIGNATURE
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 2, 8, 2, 0, 0, 0))
        + chrm + gama + srgb
        + _chunk(b"pHYs", struct.pack(">IIB", 100, 200, 1))
        + _chunk(b"eXIf", exif_body)
        + _chunk(b"tEXt", b"Author\x00Jane Example")
        + _chunk(b"IDAT", zlib.compress(rows))
        + _chunk(b"IEND", b"")
    )
    with Image.open(io.BytesIO(original)) as probe:
        assert probe.getexif()[ORIENTATION] == 6

    _asset, path = await _stored(_service(db, tmp_path), original, "image/png", "turn.png")
    cleaned = path.read_bytes()
    kinds = [kind for kind, _ in media_png._chunks(cleaned)]
    assert b"eXIf" not in kinds and b"tEXt" not in kinds
    for chunk in (gama, chrm, srgb):
        assert chunk in cleaned
    # Densities swap with the axes; colour chunks come before the image data.
    assert _chunk(b"pHYs", struct.pack(">IIB", 200, 100, 1)) in cleaned
    assert kinds.index(b"gAMA") < kinds.index(b"IDAT")
    with Image.open(path) as image:
        assert image.size == (2, 4)
        assert image.convert("RGB").getpixel((0, 0)) == (255, 0, 0)  # left half now on top
        assert image.convert("RGB").getpixel((0, 3)) == (0, 0, 255)


def _bad_crc(kind: bytes, body: bytes) -> bytes:
    good = _chunk(kind, body)
    return good[:-4] + bytes(b ^ 0xFF for b in good[-4:])


def _rgb_png(*ancillary: bytes, after_idat: bytes = b"", orientation: int | None = None) -> bytes:
    exif_chunk = b""
    if orientation is not None:
        exif = Image.Exif()
        exif[ORIENTATION] = orientation
        exif_chunk = _chunk(b"eXIf", exif.tobytes().removeprefix(b"Exif\x00\x00"))
    rows = b"".join(b"\x00" + b"\x10\x20\x30" * 4 for _ in range(2))
    return (
        media_png.PNG_SIGNATURE
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 2, 8, 2, 0, 0, 0))
        + b"".join(ancillary) + exif_chunk
        + _chunk(b"tEXt", b"Author\x00Jane Example")
        + _chunk(b"IDAT", zlib.compress(rows))
        + after_idat
        + _chunk(b"IEND", b"")
    )


@pytest.mark.parametrize("orientation", [None, 6], ids=["chunk-copy", "turned"])
async def test_a_bad_crc_chunk_is_refused_not_stored(db, tmp_path, orientation):
    """Both PNG paths fail closed on a corrupt chunk, even one Pillow tolerates."""
    bad_gama = _bad_crc(b"gAMA", struct.pack(">I", 45455))
    data = _rgb_png(after_idat=bad_gama, orientation=orientation)
    service = _service(db, tmp_path)
    with pytest.raises(HTTPException) as refused:
        await service.upload(_upload(data, "image/png", "bad.png"))
    assert refused.value.status_code == 415
    assert refused.value.detail["code"] == "image_metadata_not_removed"
    assert list(service.tenant_dir().iterdir()) == []


async def test_a_cleaned_png_that_will_not_decode_is_refused(db, tmp_path, monkeypatch):
    """Belt and braces: the cleaned bytes are decoded before anything is stored."""
    monkeypatch.setattr(media_png, "strip_chunks", lambda data: data[:-30])
    service = _service(db, tmp_path)
    with pytest.raises(HTTPException) as refused:
        await service.upload(_upload(_rgb_png(), "image/png", "x.png"))
    assert refused.value.detail["code"] == "image_metadata_not_removed"
    assert list(service.tenant_dir().iterdir()) == []


async def test_an_animated_png_loses_its_metadata_and_keeps_every_frame(db, tmp_path):
    """APNG: copied chunk by chunk, never re-encoded and never turned."""
    frames = [Image.new("RGB", (6, 4), c) for c in ((255, 0, 0), (0, 255, 0))]
    buf = io.BytesIO()
    frames[0].save(buf, format="PNG", save_all=True, append_images=frames[1:], duration=100)
    plain = buf.getvalue()
    text = _chunk(b"tEXt", b"Author\x00Jane Example")
    exif = Image.Exif()
    exif[ORIENTATION] = 6
    exif_chunk = _chunk(b"eXIf", exif.tobytes().removeprefix(b"Exif\x00\x00"))
    ihdr_end = len(media_png.PNG_SIGNATURE) + 25
    original = plain[:ihdr_end] + text + exif_chunk + plain[ihdr_end:]
    with Image.open(io.BytesIO(original)) as probe:
        assert probe.n_frames == 2

    asset, path = await _stored(_service(db, tmp_path), original, "image/png", "loop.png")
    assert path.read_bytes() == plain
    with Image.open(path) as image:
        assert image.n_frames == 2 and image.size == (6, 4)
    assert asset.size_bytes == len(plain)


def test_carrying_chunks_keeps_every_suggested_palette():
    """sPLT may repeat: each one survives, in order, not just the last."""
    splt = [_chunk(b"sPLT", name + b"\x00\x08" + b"\x10\x20\x30\xff\x00\x01") for name in
            (b"first", b"second")]
    original = _rgb_png(*splt)
    rendered = _rgb_png()
    carried = media_png.carry_chunks(original, rendered, swap_axes=False)
    kinds = [kind for kind, _ in media_png._chunks(carried)]
    assert kinds.count(b"sPLT") == 2
    assert carried.index(splt[0]) < carried.index(splt[1]) < carried.index(b"IDAT")
