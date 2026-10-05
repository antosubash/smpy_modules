"""Per-tenant media storage (#38): paths, URLs, the mount, legacy files, orphans.

Files live at ``media_root/<tenant>/<filename>`` and are served at
``<prefix>/<tenant>/<filename>``. Content saved before this change carries the
flat ``<prefix>/<filename>``, which must keep working.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, UploadFile
from httpx import ASGITransport, AsyncClient
from pagebuilder import media_usage
from pagebuilder.media_files import (
    MediaFiles,
    adopt_legacy_files,
    media_url,
    tenant_media_dir,
    warn_on_orphaned_media,
)
from pagebuilder.media_service import MediaService
from pagebuilder.models import MediaAsset, Page
from pagebuilder.settings import PagebuilderSettings
from pagebuilder.snapshots.capture import _media_maps
from pagebuilder.tenancy import TenancyMode
from pg_support import make_db_state
from PIL import Image
from simple_module_db import tenant_context

PREFIX = "/media/pagebuilder"


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color=(1, 2, 3)).save(buf, format="PNG")
    return buf.getvalue()


def _upload() -> UploadFile:
    return UploadFile(
        file=io.BytesIO(_png()),
        filename="hero.png",
        headers={"content-type": "image/png"},  # type: ignore[arg-type]
    )


def _settings(tmp_path: Path) -> PagebuilderSettings:
    return PagebuilderSettings(media_root=tmp_path / "media", media_thumbnail_widths=())


# --- paths and URLs -----------------------------------------------------------


def test_tenant_dir_and_url(tmp_path: Path) -> None:
    assert tenant_media_dir(tmp_path, "acme") == tmp_path / "acme"
    assert media_url(PREFIX + "/", "x.png", "acme") == f"{PREFIX}/acme/x.png"
    with tenant_context("globex"):
        assert tenant_media_dir(tmp_path) == tmp_path / "globex"
        assert media_url(PREFIX, "x.png") == f"{PREFIX}/globex/x.png"


def test_a_malformed_tenant_never_becomes_a_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        tenant_media_dir(tmp_path, "../etc")


@pytest.mark.unbound_tenant
def test_no_bound_tenant_is_refused_rather_than_guessed(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        tenant_media_dir(tmp_path)


async def test_upload_lands_in_the_tenant_dir_with_a_tenant_url(db, tmp_path: Path) -> None:
    service = MediaService(db, _settings(tmp_path))
    asset = await service.upload(_upload())
    assert (tmp_path / "media" / "default" / asset.filename).is_file()
    assert not (tmp_path / "media" / asset.filename).exists()
    assert service.to_read(asset).url == f"{PREFIX}/default/{asset.filename}"
    assert service.legacy_url_for(asset.filename) == f"{PREFIX}/{asset.filename}"


async def test_same_filename_in_two_tenants(db, tmp_path: Path, monkeypatch) -> None:
    """The unique key is ``(tenant_id, filename)`` and each tenant has a
    directory, so a colliding name is two files, not an overwrite."""
    fixed = uuid.UUID("0" * 32)
    monkeypatch.setattr("pagebuilder.media_service.uuid.uuid4", lambda: fixed)
    service = MediaService(db, _settings(tmp_path))
    with tenant_context("acme"):
        a = await service.upload(_upload())
    with tenant_context("globex"):
        b = await service.upload(_upload())
    assert a.filename == b.filename
    assert (tmp_path / "media" / "acme" / a.filename).is_file()
    assert (tmp_path / "media" / "globex" / b.filename).is_file()
    with tenant_context("acme"):
        await service.delete(a.id)
    assert not (tmp_path / "media" / "acme" / a.filename).exists()
    assert (tmp_path / "media" / "globex" / b.filename).is_file()


async def test_usage_finds_legacy_flat_urls(db) -> None:
    db.add(Page(slug="old", title="Old", draft_data={"src": f"{PREFIX}/abc.png"}))
    await db.flush()
    _, total = await media_usage.find(db, [f"{PREFIX}/default/abc.png", f"{PREFIX}/abc.png"])
    assert total == 1


async def test_capture_maps_both_urls_to_the_asset(db, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    (tmp_path / "media" / "default").mkdir(parents=True)
    (tmp_path / "media" / "default" / "u1.png").write_bytes(b"x")
    db.add(MediaAsset(filename="u1.png", original_filename="hero.png", content_type="image/png"))
    await db.flush()
    url_to_name, _present, missing = await _media_maps(db, settings)
    assert url_to_name == {f"{PREFIX}/default/u1.png": "hero.png", f"{PREFIX}/u1.png": "hero.png"}
    assert missing == []


# --- the mount ----------------------------------------------------------------


class _BindTenant:
    """Stands in for ``TenantMiddleware``: binds the ``x-tenant`` header."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        headers = dict(scope.get("headers") or [])
        tenant = headers.get(b"x-tenant")
        if tenant is None:
            await self.app(scope, receive, send)
            return
        with tenant_context(tenant.decode()):
            await self.app(scope, receive, send)


def _app(root: Path, mode: TenancyMode) -> FastAPI:
    app = FastAPI()
    app.state.pagebuilder = SimpleNamespace(tenancy=mode)
    app.mount(PREFIX, MediaFiles(directory=root), name="media")
    app.add_middleware(_BindTenant)
    return app


async def _get(app: FastAPI, path: str, tenant: str | None = None) -> int:
    headers = {"x-tenant": tenant} if tenant else {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        return (await client.get(path, headers=headers)).status_code


def _seed(root: Path) -> None:
    for tenant in ("acme", "globex", "default"):
        (root / tenant).mkdir(parents=True, exist_ok=True)
        (root / tenant / f"{tenant}.png").write_bytes(b"png")


@pytest.mark.unbound_tenant
async def test_multi_mode_serves_only_the_bound_tenant(tmp_path: Path) -> None:
    _seed(tmp_path)
    app = _app(tmp_path, TenancyMode.MULTI)
    assert await _get(app, f"{PREFIX}/acme/acme.png", "acme") == 200
    assert await _get(app, f"{PREFIX}/globex/globex.png", "acme") == 404
    assert await _get(app, f"{PREFIX}/globex/globex.png", "globex") == 200
    # A legacy flat URL resolves inside the request's own tenant only.
    assert await _get(app, f"{PREFIX}/acme.png", "acme") == 200
    assert await _get(app, f"{PREFIX}/globex.png", "acme") == 404
    # No tenant resolved: nothing is served.
    assert await _get(app, f"{PREFIX}/acme/acme.png") == 404
    assert await _get(app, f"{PREFIX}/acme/x/acme.png", "acme") == 404


@pytest.mark.unbound_tenant
async def test_single_mode_serves_default_and_legacy_urls(tmp_path: Path) -> None:
    _seed(tmp_path)
    app = _app(tmp_path, TenancyMode.SINGLE)
    assert await _get(app, f"{PREFIX}/default/default.png") == 200
    assert await _get(app, f"{PREFIX}/default.png") == 200
    assert await _get(app, f"{PREFIX}/acme/acme.png") == 404


# --- legacy files and the orphan scan -----------------------------------------


def test_legacy_move_is_idempotent_and_never_overwrites(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_bytes(b"old-a")
    (tmp_path / "b.png").write_bytes(b"old-b")
    (tmp_path / "acme").mkdir()
    (tmp_path / "default").mkdir()
    (tmp_path / "default" / "b.png").write_bytes(b"new-b")

    assert adopt_legacy_files(tmp_path) == 1
    assert (tmp_path / "default" / "a.png").read_bytes() == b"old-a"
    assert (tmp_path / "default" / "b.png").read_bytes() == b"new-b"
    assert (tmp_path / "b.png").read_bytes() == b"old-b"  # left, not clobbered
    assert (tmp_path / "acme").is_dir()
    assert adopt_legacy_files(tmp_path) == 0
    assert adopt_legacy_files(tmp_path / "missing") == 0


async def test_mount_media_adopts_legacy_media_and_blobs(tmp_path: Path) -> None:
    from pagebuilder import boot

    settings = PagebuilderSettings(
        media_root=tmp_path / "media", snapshot_root=tmp_path / "snapshots"
    )
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "old.png").write_bytes(b"x")
    blobs = tmp_path / "snapshots" / "blobs"
    blobs.mkdir(parents=True)
    (blobs / ("a" * 64)).write_bytes(b"blob")
    (blobs / ("b" * 64 + ".partial")).write_bytes(b"half")

    await boot.mount_media(FastAPI(), settings)

    assert (tmp_path / "media" / "default" / "old.png").is_file()
    assert (blobs / "default" / ("a" * 64)).is_file()
    assert (blobs / ("b" * 64 + ".partial")).is_file()  # not a digest: untouched


@pytest.mark.unbound_tenant
async def test_orphan_scan_checks_each_rows_own_tenant_dir(tmp_path: Path) -> None:
    state = await make_db_state()
    state.tenant_strict = True
    try:
        for tenant in ("acme", "globex"):
            with tenant_context(tenant):
                async with state.session_factory() as session:
                    session.add(
                        MediaAsset(
                            filename=f"{tenant}.png",
                            original_filename="x.png",
                            content_type="image/png",
                        )
                    )
                    await session.commit()
        root = tmp_path / "media"
        (root / "acme").mkdir(parents=True)
        (root / "acme" / "acme.png").write_bytes(b"x")
        # globex's file sits in acme's directory: still missing for globex.
        (root / "acme" / "globex.png").write_bytes(b"x")
        assert await warn_on_orphaned_media(state.session_factory, root) == 1
        (root / "globex").mkdir()
        (root / "globex" / "globex.png").write_bytes(b"x")
        assert await warn_on_orphaned_media(state.session_factory, root) == 0
    finally:
        await state.engine.dispose()
