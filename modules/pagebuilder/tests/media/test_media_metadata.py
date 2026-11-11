"""Uploaded originals lose their camera metadata (#356).

A phone photo's EXIF holds GPS coordinates and the device, and the media
library publishes the original. With ``media_strip_metadata`` on (the default)
a JPEG, PNG or WebP is stored without EXIF, XMP, IPTC or comments, turned
upright first, its ICC profile kept. WebP and animated PNG: see their own files.
"""

from __future__ import annotations

import io

import pytest
from fastapi import HTTPException
from pagebuilder.media.media_webp import is_lossless
from PIL import Image, PngImagePlugin

from tests.support.metadata_images import (
    ICC,
    XMP,
    _exif,
    _jpeg,
    _service,
    _stored,
    _two_tone,
    _upload,
)


async def test_a_phone_jpeg_loses_gps_and_device_but_stays_upright(db, tmp_path):
    service = _service(db, tmp_path)
    asset, path = await _stored(service, _jpeg(), "image/jpeg", "photo.jpg")

    raw = path.read_bytes()
    for secret in (b"SecretCam", b"Jane Example", b"GPSLatitude"):
        assert secret not in raw
    with Image.open(path) as image:
        assert len(image.getexif()) == 0
        assert not {"exif", "xmp", "comment"} & set(image.info)
        assert image.info["icc_profile"] == ICC
        # Orientation 6 (turn 90° clockwise) applied: 40x20 became 20x40, and
        # the left (red) half is now on top.
        assert image.size == (20, 40)
        red, _, blue = image.convert("RGB").getpixel((10, 5))
        assert red > 200 and blue < 60
        red, _, blue = image.convert("RGB").getpixel((10, 35))
        assert blue > 200 and red < 60
    assert (asset.width, asset.height) == (20, 40)
    assert asset.size_bytes == path.stat().st_size
    # The thumbnail is cut from the upright file too.
    assert asset.variants["w16"]["height"] == 32


async def test_a_png_loses_its_text_and_exif_but_keeps_transparency(db, tmp_path):
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "Jane Example")
    palette = _two_tone().convert("P")
    buf = io.BytesIO()
    palette.save(buf, format="PNG", pnginfo=info, exif=_exif(), transparency=0)
    asset, path = await _stored(_service(db, tmp_path), buf.getvalue(), "image/png", "a.png")

    raw = path.read_bytes()
    assert b"Jane Example" not in raw and b"SecretCam" not in raw
    with Image.open(path) as image:
        assert "Author" not in image.info and "exif" not in image.info
        assert image.info["transparency"] == 0
        assert image.mode == "P"
    assert asset.size_bytes == path.stat().st_size


@pytest.mark.parametrize("lossless", [True, False])
async def test_a_webp_loses_exif_and_xmp_and_keeps_its_compression(db, tmp_path, lossless):
    buf = io.BytesIO()
    _two_tone().save(buf, format="WEBP", lossless=lossless, exif=_exif(), xmp=XMP)
    asset, path = await _stored(_service(db, tmp_path), buf.getvalue(), "image/webp", "a.webp")

    raw = path.read_bytes()
    assert b"SecretCam" not in raw and b"GPSLatitude" not in raw
    assert is_lossless(path.read_bytes()) is lossless
    assert asset.size_bytes == path.stat().st_size


async def test_an_animated_gif_is_left_as_uploaded(db, tmp_path):
    buf = io.BytesIO()
    frames = [Image.new("RGB", (10, 10), c) for c in ((255, 0, 0), (0, 255, 0))]
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=100,
                   comment=b"Jane Example")
    original = buf.getvalue()
    asset, path = await _stored(_service(db, tmp_path), original, "image/gif", "loop.gif")
    assert path.read_bytes() == original
    assert asset.size_bytes == len(original)


async def test_the_setting_off_keeps_the_upload_byte_for_byte(db, tmp_path):
    original = _jpeg()
    service = _service(db, tmp_path, media_strip_metadata=False)
    asset, path = await _stored(service, original, "image/jpeg", "photo.jpg")
    assert path.read_bytes() == original
    assert asset.size_bytes == len(original)


async def test_a_multi_picture_jpeg_keeps_only_its_primary_picture(db, tmp_path):
    """MPO, as phones save photos: Pillow calls it animated, but it is a photo."""
    buf = io.BytesIO()
    second = Image.new("RGB", (40, 20), (0, 255, 0))
    _two_tone().save(buf, format="MPO", save_all=True, append_images=[second],
                     exif=_exif(orientation=6), icc_profile=ICC)
    content = buf.getvalue()
    with Image.open(io.BytesIO(content)) as probe:
        assert probe.format == "MPO" and probe.n_frames == 2
    asset, path = await _stored(_service(db, tmp_path), content, "image/jpeg", "phone.jpg")

    assert b"SecretCam" not in path.read_bytes()
    assert asset.content_type == "image/jpeg" and path.suffix == ".jpg"
    with Image.open(path) as image:
        assert image.format == "JPEG"
        assert getattr(image, "n_frames", 1) == 1
        assert len(image.getexif()) == 0
        assert image.info["icc_profile"] == ICC
        assert image.size == (20, 40)
    assert asset.size_bytes == path.stat().st_size


async def test_a_clean_file_is_left_byte_for_byte(db, tmp_path):
    """Idempotent: a restored bundle's clean JPEG keeps its digest."""
    buf = io.BytesIO()
    _two_tone().save(buf, format="JPEG", icc_profile=ICC)
    original = buf.getvalue()
    _asset, path = await _stored(_service(db, tmp_path), original, "image/jpeg", "a.jpg")
    assert path.read_bytes() == original


async def test_a_file_that_cannot_be_cleaned_is_refused(db, tmp_path):
    """Fails closed: an original is cleaned or not stored at all."""
    service = _service(db, tmp_path)
    bogus = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    with pytest.raises(HTTPException) as refused:
        await service.upload(_upload(bogus, "image/png", "x.png"))
    assert refused.value.status_code == 415
    assert refused.value.detail["code"] == "image_metadata_not_removed"
    assert list(service.tenant_dir().iterdir()) == []


async def test_an_image_over_the_pixel_limit_is_refused_not_stored(db, tmp_path, monkeypatch):
    """Never decoded to strip it, and never stored unstripped either."""
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    service = _service(db, tmp_path)
    with pytest.raises(HTTPException) as refused:
        await service.upload(_upload(_jpeg(), "image/jpeg", "big.jpg"))
    assert refused.value.status_code == 413
    assert list(service.tenant_dir().iterdir()) == []


async def test_with_the_setting_off_an_undecodable_file_still_uploads(db, tmp_path):
    bogus = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    service = _service(db, tmp_path, media_strip_metadata=False)
    asset, path = await _stored(service, bogus, "image/png", "x.png")
    assert path.read_bytes() == bogus
    assert asset.width is None


def test_a_jpeg_keeps_its_resolution_and_progressive_encoding():
    from pagebuilder.media.media_metadata import clean_bytes

    exif = Image.Exif()
    exif[0x010F] = "SecretCam"
    out = io.BytesIO()
    Image.new("RGB", (32, 32), (200, 10, 10)).save(
        out, "JPEG", exif=exif, dpi=(300, 300), progressive=True
    )

    cleaned = clean_bytes(out.getvalue(), "image/jpeg")

    assert cleaned is not None and b"SecretCam" not in cleaned
    with Image.open(io.BytesIO(cleaned)) as image:
        assert image.info["dpi"] == (300, 300)
        assert image.info.get("progressive")
