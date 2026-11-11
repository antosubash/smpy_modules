"""Images with camera metadata, and the media service the #356 tests upload to.

Shared by ``tests/media/test_media_metadata*.py``, split for the 300-line cap.
"""

from __future__ import annotations

import io
import struct
import zlib

from fastapi import UploadFile
from pagebuilder.core.settings import PagebuilderSettings
from pagebuilder.media.media_service import MediaService
from PIL import Image, ImageCms
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


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
