"""A cleaned animation is decoded frame by frame before it is stored (#356).

Decoding only the first frame would store a WebP or APNG whose later frames
are broken; decoding them all is bounded by a total pixel budget.
"""

from __future__ import annotations

import io
import struct
import zlib

import pytest
from fastapi import HTTPException
from PIL import Image

from tests.support.metadata_images import _chunk, _service, _stored, _upload

_COLOURS = ((255, 0, 0), (0, 255, 0), (0, 0, 255))


def _animation(fmt: str, frames: int = 2, size: tuple[int, int] = (10, 10)) -> bytes:
    images = [Image.new("RGB", size, _COLOURS[i % 3]) for i in range(frames)]
    buf = io.BytesIO()
    images[0].save(buf, format=fmt, save_all=True, append_images=images[1:], duration=100)
    return buf.getvalue()


def _with_comment(fmt: str, data: bytes) -> bytes:
    """Something to strip, so the cleaned bytes are written and verified."""
    if fmt == "PNG":
        at = 8 + 25  # after IHDR
        return data[:at] + _chunk(b"tEXt", b"Author\x00Jane Example") + data[at:]
    out = data + b"EXIF" + struct.pack("<I", 4) + b"Jane"
    return out[:4] + struct.pack("<I", len(out) - 8) + out[8:]


def _broken_second_frame(fmt: str) -> bytes:
    if fmt == "PNG":
        data = _animation(fmt)
        # The second frame's fdAT: a sequence number, then zlib data. Replace
        # the data with garbage of the same length and a valid CRC.
        at = data.index(b"fdAT") - 4
        (length,) = struct.unpack(">I", data[at : at + 4])
        body = data[at + 8 : at + 8 + 4] + b"\xff" * (length - 4)
        return data[:at] + _chunk(b"fdAT", body) + data[at + 12 + length :]
    # Lossless noise, so the second frame's bitstream is long enough to break
    # past its header: the file still opens, and only that frame fails.
    noise = [Image.effect_noise((32, 32), 50).convert("RGB") for _ in range(2)]
    buf = io.BytesIO()
    noise[0].save(buf, format="WEBP", save_all=True, append_images=noise[1:], duration=100,
                  lossless=True)
    data = buf.getvalue()
    at = data.index(b"VP8L", data.index(b"ANMF", data.index(b"ANMF") + 4)) + 8 + 10
    return data[:at] + bytes(b ^ 0xFF for b in data[at : at + 8]) + data[at + 8 :]


@pytest.mark.parametrize("fmt", ["PNG", "WEBP"])
async def test_an_animation_with_a_broken_later_frame_is_refused(db, tmp_path, fmt):
    data = _with_comment(fmt, _broken_second_frame(fmt))
    with Image.open(io.BytesIO(data)) as probe:
        probe.load()  # the first frame alone decodes fine
    service = _service(db, tmp_path)
    kind = f"image/{fmt.lower()}"
    with pytest.raises(HTTPException) as refused:
        await service.upload(_upload(data, kind, "loop"))
    assert refused.value.status_code == 415
    assert refused.value.detail["code"] == "image_metadata_not_removed"
    assert list(service.tenant_dir().iterdir()) == []


@pytest.mark.parametrize("fmt", ["PNG", "WEBP"])
async def test_a_sound_two_frame_animation_is_stored(db, tmp_path, fmt):
    data = _with_comment(fmt, _animation(fmt))
    _asset, path = await _stored(_service(db, tmp_path), data, f"image/{fmt.lower()}", "loop")
    assert b"Jane" not in path.read_bytes()
    with Image.open(path) as image:
        assert image.n_frames == 2


async def test_frames_over_the_total_pixel_budget_are_refused(db, tmp_path, monkeypatch):
    """Each frame is within the limit; twelve of them are over ten times it."""
    data = _with_comment("PNG", _animation("PNG", frames=12))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    service = _service(db, tmp_path)
    with pytest.raises(HTTPException) as refused:
        await service.upload(_upload(data, "image/png", "loop.png"))
    assert refused.value.status_code == 413
    assert refused.value.detail["code"] == "image_too_many_pixels"
    assert list(service.tenant_dir().iterdir()) == []


async def test_frames_exactly_at_the_total_pixel_budget_are_stored(db, tmp_path, monkeypatch):
    """Ten 100-pixel frames are the budget itself (ten times 100), not over it."""
    data = _with_comment("PNG", _animation("PNG", frames=10))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    _asset, path = await _stored(_service(db, tmp_path), data, "image/png", "loop.png")
    with Image.open(path) as image:
        assert image.n_frames == 10


def test_the_broken_frame_fixture_breaks_only_that_frame():
    """Guards the fixture: the CRC is valid, so only decoding can tell."""
    data = _broken_second_frame("PNG")
    at = data.index(b"fdAT") - 4
    (length,) = struct.unpack(">I", data[at : at + 4])
    body = data[at + 4 : at + 8 + length]
    assert struct.unpack(">I", data[at + 8 + length : at + 12 + length])[0] == zlib.crc32(body)
