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


async def test_a_jpeg_whose_markers_do_not_walk_is_refused(db, tmp_path):
    """No EOI before the junk: Pillow decodes it, but its end cannot be found."""
    data = _clean_jpeg()[:-2] + b"\x00" * 512
    with Image.open(io.BytesIO(data)) as probe:
        probe.load()
    service = _service(db, tmp_path)
    with pytest.raises(HTTPException) as refused:
        await service.upload(_upload(data, "image/jpeg", "bad.jpg"))
    assert refused.value.status_code == 415
    assert refused.value.detail["code"] == "image_metadata_not_removed"
    assert list(service.tenant_dir().iterdir()) == []
