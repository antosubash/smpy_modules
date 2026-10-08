"""A multi-tenant news app whose tenant comes from an ``x-tenant`` header.

Stands in for the framework's ``TenantMiddleware`` resolver: binds
``tenant_context`` and sets ``request.state.tenant_id``, as the real one does.
A plain module (``tests`` is on ``pythonpath``), like ``factories``; ported
from pagebuilder's ``tests/tenant_app.py``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from conftest import _build_app
from httpx import ASGITransport, AsyncClient
from news import tenancy
from news.tenancy import TenancyMode
from simple_module_db import tenant_context
from simple_module_hosting.middleware import TenantMiddleware

ARTICLES = "/api/news/articles"


class HeaderTenant:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        raw = dict(scope.get("headers") or []).get(b"x-tenant")
        if raw is None:
            await self.app(scope, receive, send)
            return
        tenant = raw.decode()
        scope.setdefault("state", {})["tenant_id"] = tenant
        with tenant_context(tenant):
            await self.app(scope, receive, send)


async def multi_client(user: Any, *, mount_public: bool = False) -> AsyncIterator[AsyncClient]:
    """A MULTI-mode news app on a strict database.

    ``mount_public=True`` runs ``on_startup``, whose own ``configure`` call
    sees no ``TenantMiddleware`` yet; the call below, after the middleware is
    added, is the one that stands.
    """
    app, state = await _build_app(user, mount_public=mount_public)
    app.add_middleware(HeaderTenant)  # inner: runs after TenantMiddleware
    app.add_middleware(TenantMiddleware)  # makes detect_mode say MULTI
    assert tenancy.configure(app) is TenancyMode.MULTI
    app.state.sm.db.tenant_strict = True
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            client.app = app  # type: ignore[attr-defined]
            client.db_state = state  # type: ignore[attr-defined]
            yield client
    finally:
        await state.engine.dispose()


def as_tenant(tenant: str) -> dict[str, str]:
    return {"x-tenant": tenant}


async def create_article(
    client: AsyncClient, headers: dict[str, str], slug: str, title: str, **extra: Any
) -> dict:
    response = await client.post(
        ARTICLES, json={"title": title, "slug": slug, **extra}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


async def publish(client: AsyncClient, headers: dict[str, str], article_id: int) -> None:
    response = await client.post(f"{ARTICLES}/{article_id}/publish", headers=headers)
    assert response.status_code == 200, response.text
