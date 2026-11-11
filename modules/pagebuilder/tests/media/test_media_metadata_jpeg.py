"""Bytes after a JPEG's end are removed too (#356).

A Samsung motion photo appends a video and an ``SEFT`` trailer after the
picture's ``EOI``. A JPEG with nothing else to remove is cut at its true end,
which is lossless; one that is re-saved has no trailer anyway.
"""

from __future__ import annotations

import io

import pytest
from fastapi import HTTPException
from pagebuilder.media import media_jpeg
from PIL import Image

from tests.support.metadata_images import ICC, _exif, _service, _stored, _two_tone, _upload

_TRAILER = b"motion-photo-video" + bytes(range(256)) * 4 + b"SEFH GPS 48.2N SEFT"


def _clean_jpeg(**options) -> bytes:
    buf = io.BytesIO()
    Image.merge("RGB", [Image.linear_gradient("L").resize((32, 32))] * 3).rotate(30).save(
        buf, format="JPEG", **options
    )
    return buf.getvalue()


def _pixels(data: bytes) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        return image.convert("RGB").tobytes()


@pytest.mark.parametrize("options", [{}, {"progressive": True}], ids=["baseline", "progressive"])
async def test_a_trailer_after_a_clean_jpeg_is_cut_off(db, tmp_path, options):
    clean = _clean_jpeg(**options)
    asset, path = await _stored(_service(db, tmp_path), clean + _TRAILER, "image/jpeg", "a.jpg")
    assert path.read_bytes() == clean  # cut at EOI: not re-encoded
    assert _pixels(path.read_bytes()) == _pixels(clean)
    assert asset.size_bytes == len(clean)


async def test_an_end_marker_inside_a_segment_is_not_the_end(db, tmp_path):
    """An ICC profile (APP2, kept) holding ``FFD9`` is skipped by its length."""
    clean = _clean_jpeg(icc_profile=b"\xff\xd9" * 64)
    _asset, path = await _stored(_service(db, tmp_path), clean + _TRAILER, "image/jpeg", "a.jpg")
    assert path.read_bytes() == clean


def test_an_exif_thumbnail_does_not_end_the_walk():
    """An APP1 thumbnail is a whole JPEG, ``FFD9`` included, inside a segment."""
    thumb = _clean_jpeg()
    body = b"Exif\x00\x00" + thumb
    app1 = b"\xff\xe1" + (len(body) + 2).to_bytes(2, "big") + body
    main = _clean_jpeg()
    data = main[:2] + app1 + main[2:]
    assert media_jpeg.image_end(data + _TRAILER) == len(data)


async def test_a_clean_jpeg_without_a_trailer_is_stored_byte_for_byte(db, tmp_path):
    clean = _clean_jpeg(icc_profile=ICC)
    _asset, path = await _stored(_service(db, tmp_path), clean, "image/jpeg", "a.jpg")
    assert path.read_bytes() == clean


async def test_a_geotagged_jpeg_with_a_trailer_loses_both(db, tmp_path):
    buf = io.BytesIO()
    _two_tone().save(buf, format="JPEG", exif=_exif())
    _asset, path = await _stored(
        _service(db, tmp_path), buf.getvalue() + _TRAILER, "image/jpeg", "a.jpg"
    )
    raw = path.read_bytes()
    assert b"SecretCam" not in raw and b"SEFT" not in raw
    assert media_jpeg.image_end(raw) == len(raw)


async def test_a_multi_picture_jpeg_with_a_trailer_keeps_only_its_first_picture(db, tmp_path):
    buf = io.BytesIO()
    second = Image.new("RGB", (40, 20), (0, 255, 0))
    _two_tone().save(buf, format="MPO", save_all=True, append_images=[second])
    _asset, path = await _stored(
        _service(db, tmp_path), buf.getvalue() + _TRAILER, "image/jpeg", "phone.jpg"
    )
    raw = path.read_bytes()
    assert b"SEFT" not in raw
    assert media_jpeg.image_end(raw) == len(raw)
    with Image.open(path) as image:
        assert image.format == "JPEG"


async def test_a_jpeg_without_a_proper_end_is_re_saved(db, tmp_path):
    """No EOI before the padding: its end cannot be found, but Pillow decodes it."""
    data = _clean_jpeg()[:-2] + b"\x00" * 512
    with Image.open(io.BytesIO(data)) as probe:
        probe.load()
    asset, path = await _stored(_service(db, tmp_path), data, "image/jpeg", "old.jpg")
    raw = path.read_bytes()
    assert raw != data and not raw.endswith(b"\x00" * 16)
    assert media_jpeg.image_end(raw) == len(raw)  # a fresh encode, ending at EOI
    assert asset.size_bytes == len(raw)


async def test_a_jpeg_neither_walk_nor_pillow_can_read_is_refused(db, tmp_path):
    data = _clean_jpeg()[:-120]  # cut short inside the scan: Pillow refuses it
    service = _service(db, tmp_path)
    with pytest.raises(HTTPException) as refused:
        await service.upload(_upload(data, "image/jpeg", "bad.jpg"))
    assert refused.value.status_code == 415
    assert refused.value.detail["code"] == "image_metadata_not_removed"
    assert list(service.tenant_dir().iterdir()) == []


def _segment(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + (len(payload) + 2).to_bytes(2, "big") + payload


def _insert_before_second_scan(data: bytes, *segments: bytes) -> bytes:
    at = data.index(b"\xff\xda", data.index(b"\xff\xda") + 2)
    return data[:at] + b"".join(segments) + data[at:]


async def test_metadata_between_the_scans_of_a_progressive_jpeg_is_removed(db, tmp_path):
    """Pillow's inventory stops at the first scan; the marker walk does not."""
    xmp = _segment(0xE1, b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta>GPS 48.2N</x:xmpmeta>")
    com = _segment(0xFE, b"Owner: Jane Example")
    data = _insert_before_second_scan(_clean_jpeg(progressive=True), xmp, com)
    with Image.open(io.BytesIO(data)) as probe:
        probe.load()
        assert "comment" not in probe.info and "xmp" not in probe.info  # Pillow missed them
    _asset, path = await _stored(_service(db, tmp_path), data, "image/jpeg", "p.jpg")
    raw = path.read_bytes()
    assert b"GPS 48.2N" not in raw and b"Jane Example" not in raw
    assert media_jpeg.scan(raw) == (len(raw), False)


def _jfif(thumbnail: tuple[int, int]) -> bytes:
    return _segment(0xE0, b"JFIF\x00\x01\x02\x00\x00\x01\x00\x01" + bytes(thumbnail)
                    + b"\x00" * (3 * thumbnail[0] * thumbnail[1]))


@pytest.mark.parametrize(
    "segment",
    [
        _segment(0xE0, b"JFXX\x00\x10" + b"\xff\xd8 thumbnail GPS 48.2N \xff\xd9"),
        _jfif((2, 1)),
    ],
    ids=["jfxx-extension", "jfif-thumbnail"],
)
async def test_an_app0_thumbnail_counts_as_metadata(db, tmp_path, segment):
    clean = _clean_jpeg()
    assert media_jpeg.scan(clean) == (len(clean), False)  # Pillow's own JFIF header
    data = clean[:2] + segment + clean[2:]
    assert media_jpeg.scan(data)[1] is True
    _asset, path = await _stored(_service(db, tmp_path), data, "image/jpeg", "t.jpg")
    raw = path.read_bytes()
    assert segment not in raw and b"JFXX" not in raw
    assert media_jpeg.scan(raw) == (len(raw), False)
