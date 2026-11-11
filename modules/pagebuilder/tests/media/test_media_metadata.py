"""Uploaded originals lose their camera metadata (#356).

A phone photo's EXIF holds GPS coordinates and the device, and the media
library publishes the original. With ``media_strip_metadata`` on (the default)
a JPEG, PNG or WebP is re-saved without EXIF, XMP, IPTC or comments, turned
upright first, its ICC profile kept. Animated images are left as they came.
"""

from __future__ import annotations

import io

import pytest
from fastapi import UploadFile
from pagebuilder.core.settings import PagebuilderSettings
from pagebuilder.media.media_metadata import _webp_is_lossless
from pagebuilder.media.media_service import MediaService
from PIL import Image, ImageCms, PngImagePlugin
from sqlalchemy.ext.asyncio import AsyncSession

ORIENTATION, MAKE, GPS = 0x0112, 0x010F, 0x8825
ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
XMP = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><exif:GPSLatitude>48,12N</exif:GPSLatitude></x:xmpmeta>'


def _exif(orientation: int | None = None) -> Image.Exif:
    exif = Image.Exif()
    exif[MAKE] = "SecretCam"
    exif[GPS] = {1: "N", 2: (48.0, 12.0, 30.0), 3: "E", 4: (16.0, 22.0, 5.0)}
    if orientation is not None:
        exif[ORIENTATION] = orientation
    return exif


def _two_tone(size: tuple[int, int] = (40, 20)) -> Image.Image:
    """Red on the left half, blue on the right, so a turn is visible."""
    image = Image.new("RGB", size, (0, 0, 255))
    image.paste((255, 0, 0), (0, 0, size[0] // 2, size[1]))
    return image


def _jpeg() -> bytes:
    buf = io.BytesIO()
    _two_tone().save(
        buf, format="JPEG", quality=90, exif=_exif(orientation=6), icc_profile=ICC,
        xmp=XMP, comment=b"Owner: Jane Example",
    )
    return buf.getvalue()


def _upload(content: bytes, content_type: str, name: str) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content), filename=name,
        headers={"content-type": content_type},  # type: ignore[arg-type]
    )


def _service(db: AsyncSession, tmp_path, **settings) -> MediaService:
    return MediaService(
        db, PagebuilderSettings(media_root=tmp_path / "media", media_thumbnail_widths=(16,),
                                **settings)
    )


async def _stored(service: MediaService, content: bytes, content_type: str, name: str):
    asset = await service.upload(_upload(content, content_type, name))
    path = service.tenant_dir() / asset.filename
    return asset, path


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
    assert _webp_is_lossless(path) is lossless
    assert asset.size_bytes == path.stat().st_size


async def test_an_animated_image_is_left_as_uploaded(db, tmp_path):
    buf = io.BytesIO()
    frames = [Image.new("RGB", (10, 10), c) for c in ((255, 0, 0), (0, 255, 0))]
    frames[0].save(buf, format="WEBP", save_all=True, append_images=frames[1:], duration=100,
                   exif=_exif())
    original = buf.getvalue()
    asset, path = await _stored(_service(db, tmp_path), original, "image/webp", "loop.webp")
    assert path.read_bytes() == original
    assert asset.size_bytes == len(original)


async def test_the_setting_off_keeps_the_upload_byte_for_byte(db, tmp_path):
    original = _jpeg()
    service = _service(db, tmp_path, media_strip_metadata=False)
    asset, path = await _stored(service, original, "image/jpeg", "photo.jpg")
    assert path.read_bytes() == original
    assert asset.size_bytes == len(original)


async def test_an_undecodable_file_is_kept_and_still_uploads(db, tmp_path):
    """Not refused here: the upload's own checks decide, as before."""
    bogus = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    asset, path = await _stored(_service(db, tmp_path), bogus, "image/png", "x.png")
    assert path.read_bytes() == bogus
    assert asset.width is None
