"""The JPEG segment walk: exact sizes for kept headers, the ICC profile anywhere (#356).

Split from ``test_media_metadata_jpeg.py`` for the 300-line cap.
"""

from __future__ import annotations

import io

import pytest
from pagebuilder.media import media_jpeg
from PIL import Image

from tests.support.metadata_images import ICC, _exif, _service, _stored

_HIDDEN = b"GPS 48.2N hidden"


def _segment(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + (len(payload) + 2).to_bytes(2, "big") + payload


def _segments(data: bytes):
    """``(offset, marker, whole segment)`` for each segment before the first scan."""
    pos = 2
    while data[pos + 1] != 0xDA:
        length = int.from_bytes(data[pos + 2 : pos + 4], "big")
        yield pos, data[pos + 1], data[pos : pos + 2 + length]
        pos += 2 + length


def _grown(data: bytes, marker: int) -> bytes:
    """*data* with :data:`_HIDDEN` appended inside its first *marker* segment."""
    for pos, found, segment in _segments(data):
        if found == marker:
            grown = _segment(marker, segment[4:] + _HIDDEN)
            return data[:pos] + grown + data[pos + len(segment) :]
    raise AssertionError(f"no {marker:#x} segment")


def _jpeg(mode: str = "RGB", **options) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (16, 16), (10, 200, 30, 0)[: len(mode)]).save(buf, format="JPEG", **options)
    return buf.getvalue()


@pytest.mark.parametrize(
    ("mode", "marker"), [("RGB", 0xE0), ("CMYK", 0xEE)], ids=["jfif", "adobe"]
)
async def test_a_kept_header_longer_than_defined_is_metadata(db, tmp_path, mode, marker):
    clean = _jpeg(mode)
    assert media_jpeg.scan(clean).metadata is False  # the exact-size header is kept
    data = _grown(clean, marker)
    assert media_jpeg.scan(data).metadata is True
    _asset, path = await _stored(_service(db, tmp_path), data, "image/jpeg", "a.jpg")
    raw = path.read_bytes()
    assert _HIDDEN not in raw
    assert media_jpeg.scan(raw).metadata is False


def _icc_fragment(number: int, count: int, body: bytes) -> bytes:
    return _segment(0xE2, b"ICC_PROFILE\x00" + bytes([number, count]) + body)


async def test_an_icc_profile_after_the_frame_header_survives_the_re_save(db, tmp_path):
    """Pillow assembles the profile at SOF; fragments after it are the walk's to find."""
    plain = _jpeg(exif=_exif())  # metadata: this file is re-saved
    half = len(ICC) // 2
    first, second = _icc_fragment(1, 2, ICC[:half]), _icc_fragment(2, 2, ICC[half:])
    sof = next(pos + len(seg) for pos, marker, seg in _segments(plain) if marker == 0xC0)
    # Fragment 2 before the frame header, fragment 1 after it: order by number.
    data = plain[:2] + second + plain[2:sof] + first + plain[sof:]
    with Image.open(io.BytesIO(data)) as probe:
        assert probe.info.get("icc_profile") != ICC  # Pillow alone would lose it
    assert media_jpeg.scan(data).icc == ICC

    _asset, path = await _stored(_service(db, tmp_path), data, "image/jpeg", "a.jpg")
    assert b"SecretCam" not in path.read_bytes()
    with Image.open(path) as image:
        assert image.info["icc_profile"] == ICC


def test_icc_fragments_that_do_not_assemble_are_metadata():
    plain = _jpeg()
    data = plain[:2] + _icc_fragment(1, 2, ICC) + plain[2:]  # fragment 2 of 2 missing
    walked = media_jpeg.scan(data)
    assert walked.icc is None and walked.metadata is True
