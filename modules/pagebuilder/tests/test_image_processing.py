"""Tests for server-side image processing.

Covers dimension extraction, webp thumbnail generation, the "no
regression for animated GIF / decode failure" requirement, and variant
cleanup on delete.
"""

from __future__ import annotations

import io

import pytest
from fastapi import UploadFile
from pagebuilder.media_service import MediaService
from pagebuilder.models import Base
from pagebuilder.settings import PagebuilderSettings
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.asyncio.session import async_sessionmaker


def _png_bytes(width: int, height: int) -> bytes:
    """A real, decodable PNG so Pillow can actually process it."""
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(128, 64, 32)).save(buf, format="PNG")
    return buf.getvalue()


def _animated_gif_bytes() -> bytes:
    """Two-frame GIF — Pillow flags this as ``is_animated``.

    The frames need visually-distinct content; Pillow optimizes away a
    second frame that's pixel-identical to the first, leaving a 1-frame
    GIF that doesn't trip ``is_animated``.
    """
    buf = io.BytesIO()
    frame_a = Image.new("RGB", (10, 10), color=(255, 0, 0)).convert("P")
    frame_b = Image.new("RGB", (10, 10), color=(0, 255, 0)).convert("P")
    frame_a.save(
        buf,
        format="GIF",
        save_all=True,
        append_images=[frame_b],
        duration=100,
        loop=0,
        disposal=2,
    )
    return buf.getvalue()


def _make_upload(content: bytes, *, filename: str, content_type: str) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        headers={"content-type": content_type},  # type: ignore[arg-type]
    )


@pytest.fixture
async def db_session(tmp_path) -> AsyncSession:  # type: ignore[no-untyped-def]
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def media_service(db_session: AsyncSession, tmp_path) -> MediaService:  # type: ignore[no-untyped-def]
    settings = PagebuilderSettings(
        media_root=tmp_path / "media",
        # Pick widths that exercise both "under source" and "over source"
        # branches given a 1500px-wide test fixture.
        media_thumbnail_widths=(320, 640, 1280, 1920),
    )
    return MediaService(db_session, settings)


async def test_upload_records_dimensions(media_service: MediaService) -> None:
    upload = _make_upload(
        _png_bytes(800, 600), filename="hero.png", content_type="image/png"
    )
    asset = await media_service.upload(upload)
    assert asset.width == 800
    assert asset.height == 600


async def test_upload_generates_webp_thumbnails(media_service: MediaService) -> None:
    upload = _make_upload(
        _png_bytes(1500, 1000), filename="hero.png", content_type="image/png"
    )
    asset = await media_service.upload(upload)
    # 1500px source → widths 320, 640, 1280 qualify; 1920 is skipped
    # because we never upscale.
    assert set(asset.variants.keys()) == {"w320", "w640", "w1280"}
    w640 = asset.variants["w640"]
    assert w640["content_type"] == "image/webp"
    assert w640["width"] == 640
    # 1500x1000 → aspect-preserving height at 640 width is round(640*1000/1500) = 427
    assert w640["height"] == 427
    # File actually exists on disk under the variant name.
    variant_path = media_service.storage_root / w640["filename"]
    assert variant_path.is_file()
    assert variant_path.stat().st_size > 0


async def test_upload_skips_thumbnails_smaller_than_smallest_width(
    media_service: MediaService,
) -> None:
    # 200px source: every configured width >= source, so no variants.
    upload = _make_upload(
        _png_bytes(200, 100), filename="tiny.png", content_type="image/png"
    )
    asset = await media_service.upload(upload)
    assert asset.width == 200
    assert asset.variants == {}


async def test_animated_gif_skips_thumbnails(media_service: MediaService) -> None:
    upload = _make_upload(
        _animated_gif_bytes(), filename="loop.gif", content_type="image/gif"
    )
    asset = await media_service.upload(upload)
    # Animated GIFs land in storage as-is; we capture dimensions so the
    # Image block can still emit width/height, but skip transcoding so
    # animation is preserved.
    assert asset.variants == {}
    assert asset.width == 10
    assert asset.height == 10
    # Original still saved.
    assert (media_service.storage_root / asset.filename).is_file()


async def test_to_read_exposes_variant_urls(media_service: MediaService) -> None:
    upload = _make_upload(
        _png_bytes(1024, 768), filename="hero.png", content_type="image/png"
    )
    asset = await media_service.upload(upload)
    read = media_service.to_read(asset)
    assert read.width == 1024
    assert read.height == 768
    assert "w640" in read.variants
    variant = read.variants["w640"]
    assert variant.url.endswith(variant.filename)
    assert variant.url.startswith(media_service.settings.media_url_prefix)


async def test_delete_removes_variant_files(media_service: MediaService) -> None:
    upload = _make_upload(
        _png_bytes(1024, 768), filename="hero.png", content_type="image/png"
    )
    asset = await media_service.upload(upload)
    variant_paths = [
        media_service.storage_root / meta["filename"]
        for meta in asset.variants.values()
    ]
    original_path = media_service.storage_root / asset.filename
    assert variant_paths and all(p.is_file() for p in variant_paths)
    assert asset.id is not None
    await media_service.delete(asset.id)
    assert not original_path.exists()
    for p in variant_paths:
        assert not p.exists(), f"variant {p.name} leaked after delete"


async def test_disabling_thumbnail_widths_skips_generation(
    db_session: AsyncSession, tmp_path
) -> None:
    settings = PagebuilderSettings(
        media_root=tmp_path / "media",
        media_thumbnail_widths=(),
    )
    service = MediaService(db_session, settings)
    upload = _make_upload(
        _png_bytes(1024, 768), filename="hero.png", content_type="image/png"
    )
    asset = await service.upload(upload)
    # Dimensions still captured — that's a separate concern from
    # generating derivatives.
    assert asset.width == 1024
    assert asset.variants == {}
