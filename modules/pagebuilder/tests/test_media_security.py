"""Security tests for media upload validation (issues #4, #5)."""

from __future__ import annotations

import io

import pytest
from fastapi import HTTPException, UploadFile
from pagebuilder.media_images import sniff_content_type
from pagebuilder.media_service import MediaService
from pagebuilder.models import Base, MediaAsset  # noqa: F401 — register metadata
from pagebuilder.settings import PagebuilderSettings
from sqlalchemy.ext.asyncio import AsyncSession

# Real PNG header (8-byte signature) followed by an IHDR-ish chunk.
_PNG_HEADER = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 16
_JPEG_HEADER = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 16
_GIF_HEADER = b"GIF89a" + b"\x00" * 16
_WEBP_HEADER = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 16
_PHP_PAYLOAD = b"<?php echo 'pwn'; ?>" + b"\x00" * 32
_SVG_PAYLOAD = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


def test_sniff_png() -> None:
    assert sniff_content_type(_PNG_HEADER) == "image/png"


def test_sniff_jpeg() -> None:
    assert sniff_content_type(_JPEG_HEADER) == "image/jpeg"


def test_sniff_gif() -> None:
    assert sniff_content_type(_GIF_HEADER) == "image/gif"


def test_sniff_webp() -> None:
    assert sniff_content_type(_WEBP_HEADER) == "image/webp"


def test_sniff_rejects_php_disguised_as_png() -> None:
    assert sniff_content_type(_PHP_PAYLOAD) is None


def test_sniff_rejects_svg() -> None:
    # SVG isn't in our sniffer's allowlist — even if a host re-enables
    # the content-type, the sniffer won't match it.
    assert sniff_content_type(_SVG_PAYLOAD) is None


def test_svg_not_in_default_allowed_types() -> None:
    settings = PagebuilderSettings()
    assert "image/svg+xml" not in settings.media_allowed_content_types


def _make_upload(content: bytes, *, filename: str, content_type: str) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        headers={"content-type": content_type},  # type: ignore[arg-type]
    )


@pytest.fixture
def db_session(db: AsyncSession) -> AsyncSession:
    """``db_fixture``'s session: its listeners stamp each row's tenant."""
    return db


@pytest.fixture
def media_service(db_session: AsyncSession, tmp_path) -> MediaService:  # type: ignore[no-untyped-def]
    settings = PagebuilderSettings(media_root=tmp_path / "media")
    return MediaService(db_session, settings)


async def test_upload_rejects_declared_svg(media_service: MediaService) -> None:
    upload = _make_upload(_SVG_PAYLOAD, filename="x.svg", content_type="image/svg+xml")
    with pytest.raises(HTTPException) as exc:
        await media_service.upload(upload)
    assert exc.value.status_code == 415


async def test_upload_rejects_php_declared_as_png(media_service: MediaService) -> None:
    upload = _make_upload(_PHP_PAYLOAD, filename="evil.png", content_type="image/png")
    with pytest.raises(HTTPException) as exc:
        await media_service.upload(upload)
    assert exc.value.status_code == 415


async def test_upload_rejects_mime_mismatch(media_service: MediaService) -> None:
    # Real PNG bytes, but the client claims it's a JPEG.
    upload = _make_upload(_PNG_HEADER, filename="real.png", content_type="image/jpeg")
    with pytest.raises(HTTPException) as exc:
        await media_service.upload(upload)
    assert exc.value.status_code == 415


async def test_upload_accepts_real_png(media_service: MediaService) -> None:
    upload = _make_upload(_PNG_HEADER, filename="real.png", content_type="image/png")
    asset = await media_service.upload(upload)
    assert asset.content_type == "image/png"
    assert asset.filename.endswith(".png")


async def test_upload_pins_extension_to_sniffed_type(
    media_service: MediaService,
) -> None:
    # PNG bytes uploaded under a .jpg filename should be stored as .png.
    upload = _make_upload(
        _PNG_HEADER, filename="real-but-renamed.jpg", content_type="image/png"
    )
    asset = await media_service.upload(upload)
    assert asset.filename.endswith(".png")
