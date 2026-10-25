"""A host running pagebuilder *and* news, for the content-bundle tests (#80).

Pagebuilder's Import / Export API is what the tests drive, so this mounts
pagebuilder the way its own harness does (pre-seeded settings rooted in
``tmp_path``, stub admin, no CSRF) on a database holding both modules' tables,
then registers news' bundle section exactly as ``NewsModule.on_startup`` does.
News' own routes are not mounted: articles are seeded through the model.
A plain module (``tests`` is on ``pythonpath``), like ``tenant_app``.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.templating import Jinja2Templates
from httpx import ASGITransport, AsyncClient
from news.constants import PERM_EDIT, PERM_PUBLISH, PERM_VIEW
from news.integrations.pagebuilder import register_bundle_section
from news.models import NewsArticle
from pagebuilder.module import PagebuilderModule
from pagebuilder.permissions import ALL_PERMISSIONS as PB_PERMISSIONS
from pagebuilder.settings import PagebuilderSettings
from pg_support import make_db_state
from settings.module_registry import ModuleSettingsRegistry
from simple_module_core.permissions import PermissionRegistry
from simple_module_db import tenant_context
from simple_module_inertia import InertiaConfig, inertia_dependency_factory
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from stub_auth import stub_user

SNAPSHOTS = "/api/pagebuilder/snapshots"
PAGES = "/api/pagebuilder/pages"
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 16


ROLES = {
    # Pagebuilder's whole Import / Export, and nothing of news'.
    "pb": list(PB_PERMISSIONS),
    "pb-news-edit": [*PB_PERMISSIONS, PERM_VIEW, PERM_EDIT],
    "pb-news": [*PB_PERMISSIONS, PERM_VIEW, PERM_EDIT, PERM_PUBLISH],
}


def as_role(role: str) -> dict[str, str]:
    """Headers making a request run as a user holding only *role* (default: admin)."""
    return {"x-roles": role}


class RolesAuth(BaseHTTPMiddleware):
    """The stub user, with the roles an ``x-roles`` header names (``admin`` otherwise)."""

    async def dispatch(self, request, call_next):  # type: ignore[override]
        roles = request.headers.get("x-roles", "admin")
        request.state.user = stub_user(tuple(roles.split(",")))
        return await call_next(request)


class HeaderTenant:
    """Bind the tenant an ``x-tenant`` header names, as ``TenantMiddleware`` would."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        raw = dict(scope.get("headers") or []).get(b"x-tenant") if scope["type"] == "http" else None
        if raw is None:
            await self.app(scope, receive, send)
            return
        scope.setdefault("state", {})["tenant_id"] = raw.decode()
        with tenant_context(raw.decode()):
            await self.app(scope, receive, send)


async def _build(tmp_path: Path, *, news: bool, multi: bool) -> tuple[FastAPI, Any]:
    module = PagebuilderModule()
    module.settings = PagebuilderSettings(
        media_root=tmp_path / "media",
        snapshot_root=tmp_path / "snapshots",
        requires_auth=True,
        csrf_protect=False,
    )
    (tmp_path / "media").mkdir(parents=True, exist_ok=True)
    app = FastAPI()
    app.state.settings = SimpleNamespace(module_registry=ModuleSettingsRegistry())
    module.register_settings(app)
    module.register_middleware(app)
    api = APIRouter(prefix=module.meta.route_prefix)
    views = APIRouter(prefix=module.meta.view_prefix)
    module.register_routes(api, views)
    app.include_router(api)
    app.include_router(views)
    db_state = await make_db_state()
    registry = PermissionRegistry()
    for role, permissions in ROLES.items():
        registry.map_role(role, permissions)
    app.state.sm = SimpleNamespace(db=db_state, permissions=registry)
    templates = tmp_path / "templates"
    templates.mkdir(exist_ok=True)
    (templates / "index.html").write_text('<html lang="en"></html>')
    app.state.inertia_dependency = inertia_dependency_factory(
        InertiaConfig(
            environment="development",
            version="1.0",
            dev_url="http://localhost:5050",
            templates=Jinja2Templates(directory=str(templates)),
            root_template_filename="index.html",
            entrypoint_filename="main.tsx",
            root_directory=".",
            use_flash_errors=True,
        )
    )
    app.add_middleware(RolesAuth)
    app.add_middleware(SessionMiddleware, secret_key="news-bundle-tests")
    if multi:
        from pagebuilder import tenancy
        from simple_module_hosting.middleware import TenantMiddleware

        app.add_middleware(HeaderTenant)
        app.add_middleware(TenantMiddleware)
        assert tenancy.configure(app) is tenancy.TenancyMode.MULTI
        db_state.tenant_strict = True
    await module.on_startup(app)
    if news:
        assert register_bundle_section(app) is True
    return app, db_state


@asynccontextmanager
async def bundle_host(
    tmp_path: Path, *, news: bool = True, multi: bool = False
) -> AsyncIterator[AsyncClient]:
    """An admin client on a pagebuilder host, with news' section unless ``news=False``."""
    app, state = await _build(tmp_path, news=news, multi=multi)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            c.db_state = state  # type: ignore[attr-defined]
            yield c
    finally:
        await state.engine.dispose()


def session(client: AsyncClient) -> Any:
    return client.db_state.session_factory()  # type: ignore[attr-defined]


async def add(client: AsyncClient, *rows: Any) -> list[Any]:
    """Insert *rows* (any news model) in one committed session; return them refreshed."""
    async with session(client) as db:
        db.add_all(rows)
        await db.commit()
        for row in rows:
            await db.refresh(row)
    return list(rows)


async def article(client: AsyncClient, slug: str, **fields: Any) -> NewsArticle:
    fields.setdefault("title", slug.title())
    fields.setdefault("draft_data", {"content": [{"type": "Paragraph", "props": {"text": slug}}]})
    [row] = await add(client, NewsArticle(slug=slug, **fields))
    return row


async def take(client: AsyncClient, headers: dict | None = None) -> dict:
    response = await client.post(SNAPSHOTS, json={}, headers=headers or {})
    assert response.status_code == 201, response.text
    return response.json()


async def download(client: AsyncClient, snapshot_id: int, headers: dict | None = None) -> bytes:
    response = await client.get(f"{SNAPSHOTS}/{snapshot_id}/download", headers=headers or {})
    assert response.status_code == 200, response.text
    return response.content


async def upload(client: AsyncClient, data: bytes, headers: dict | None = None):
    return await client.post(
        f"{SNAPSHOTS}/upload", files={"file": ("b.zip", data)}, headers=headers or {}
    )


async def stage(client: AsyncClient, snapshot_id: int, headers: dict | None = None):
    return await client.post(f"{SNAPSHOTS}/{snapshot_id}/restore", headers=headers or {})


async def approve(client: AsyncClient, import_id: int, headers: dict | None = None):
    return await client.post(f"/api/pagebuilder/imports/{import_id}/approve", headers=headers or {})


async def restore(client: AsyncClient, snapshot_id: int, headers: dict | None = None) -> dict:
    """Stage and approve; return the plan."""
    staged = await stage(client, snapshot_id, headers)
    assert staged.status_code == 201, staged.text
    applied = await approve(client, staged.json()["id"], headers)
    assert applied.status_code == 200, applied.text
    return staged.json()["plan"]


def bundle_dir(client: AsyncClient, snapshot_id: int) -> Path:
    root = client.app.state.pagebuilder.settings.snapshot_root  # type: ignore[attr-defined]
    return root / "snapshots" / str(snapshot_id)


def news_files(client: AsyncClient, snapshot_id: int) -> dict[str, Any]:
    """Every file under the snapshot's ``news/``, parsed, by relative path."""
    base = bundle_dir(client, snapshot_id) / "news"
    return {
        p.relative_to(base).as_posix(): json.loads(p.read_text())
        for p in sorted(base.rglob("*.json"))
    }


def rezip(data: bytes, replace: dict[str, Any]) -> bytes:
    """*data* (a bundle zip) with members replaced (``None`` drops one; dict/list is JSON)."""
    source = zipfile.ZipFile(io.BytesIO(data))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as out:
        for info in source.infolist():
            if info.filename not in replace:
                out.writestr(info, source.read(info.filename))
        for name, value in replace.items():
            if value is not None:
                out.writestr(name, value if isinstance(value, bytes) else json.dumps(value))
    return buffer.getvalue()


async def update(client: AsyncClient, model: Any, row_id: int, **fields: Any) -> None:
    """Set *fields* on one row, committed."""
    async with session(client) as db:
        row = await db.get(model, row_id)
        for name, value in fields.items():
            setattr(row, name, value)
        await db.commit()


def plan_lines(plan: dict) -> dict[str, dict]:
    """The news section's plan lines, by the last segment of their label key."""
    [news] = plan["sections"]
    return {line["label_key"].rsplit(".", 1)[1]: line for line in news["lines"]}
