"""Media serving: root anchoring, cache headers, orphan detection (#13, #14).

The cwd-relative ``media_root`` default meant two differently-launched
processes read and wrote different media directories against one database;
rows outlived their files and every photo 404'd — as ``text/html`` — while
the picker still listed the assets. These tests pin the three defenses:
project-root anchoring, an honest plain-text 404 with immutable caching on
hits, and the startup orphan count.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pagebuilder.media_files import (
    MediaFiles,
    count_missing_media_files,
    resolve_media_root,
)
from pagebuilder.models import MediaAsset
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


# --- resolve_media_root -----------------------------------------------------


def test_absolute_media_root_passes_through(tmp_path: Path) -> None:
    assert resolve_media_root(tmp_path / "media") == (tmp_path / "media").resolve()


def test_relative_root_anchors_to_sm_project_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SM_PROJECT_ROOT", str(tmp_path))
    assert resolve_media_root(Path("var/media")) == (tmp_path / "var/media").resolve()


def test_relative_root_walks_up_to_a_project_sentinel(tmp_path: Path, monkeypatch) -> None:
    """From a subdirectory of the project, the same directory is chosen."""
    monkeypatch.delenv("SM_PROJECT_ROOT", raising=False)
    (tmp_path / "pyproject.toml").write_text("")
    subdir = tmp_path / "host" / "somewhere"
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)
    assert resolve_media_root(Path("var/media")) == (tmp_path / "var/media").resolve()


# --- MediaFiles responses ---------------------------------------------------


def _media_app(root: Path) -> FastAPI:
    app = FastAPI()
    app.mount("/media", MediaFiles(directory=root), name="media")
    return app


async def test_served_file_gets_immutable_cache_control(tmp_path: Path) -> None:
    (tmp_path / "photo.jpg").write_bytes(b"\xff\xd8jpeg")
    transport = ASGITransport(app=_media_app(tmp_path))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/media/photo.jpg")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"


async def test_missing_file_is_a_plain_text_404(tmp_path: Path) -> None:
    """Not the HTML app shell — an <img> 404 must look like one to monitoring."""
    transport = ASGITransport(app=_media_app(tmp_path))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/media/gone.jpg")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/plain")


# --- orphan detection -------------------------------------------------------


@pytest.fixture
def db_session(db: AsyncSession) -> AsyncSession:
    """``db_fixture``'s session: its listeners stamp each row's tenant."""
    return db


def _asset(filename: str, variants: dict | None = None) -> MediaAsset:
    return MediaAsset(
        filename=filename,
        original_filename=filename,
        content_type="image/jpeg",
        size_bytes=4,
        variants=variants or {},
    )


async def test_counts_rows_whose_file_is_gone(db_session: AsyncSession, tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    (root / "present.jpg").write_bytes(b"ok")
    db_session.add(_asset("present.jpg"))
    db_session.add(_asset("gone.jpg"))
    await db_session.commit()

    assert await count_missing_media_files(db_session, root) == 1


async def test_a_missing_variant_counts_as_missing(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    root = tmp_path / "media"
    root.mkdir()
    (root / "photo.jpg").write_bytes(b"ok")
    db_session.add(
        _asset("photo.jpg", variants={"w320": {"filename": "photo_w320.webp"}})
    )
    await db_session.commit()

    assert await count_missing_media_files(db_session, root) == 1


async def test_intact_library_counts_zero(db_session: AsyncSession, tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    (root / "photo.jpg").write_bytes(b"ok")
    (root / "photo_w320.webp").write_bytes(b"ok")
    db_session.add(
        _asset("photo.jpg", variants={"w320": {"filename": "photo_w320.webp"}})
    )
    await db_session.commit()

    assert await count_missing_media_files(db_session, root) == 0
