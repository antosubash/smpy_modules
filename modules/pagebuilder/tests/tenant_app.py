"""A multi-tenant pagebuilder app whose tenant comes from an ``x-tenant`` header.

Stands in for the framework's ``TenantMiddleware`` resolver: binds
``tenant_context`` and sets ``request.state.tenant_id``, as the real one does.
A plain module (``tests`` is on ``pythonpath``), like ``page_helpers``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from conftest import _build_app, _client_for
from httpx import AsyncClient
from pagebuilder import tenancy
from pagebuilder.tenancy import TenancyMode
from simple_module_db import tenant_context
from simple_module_hosting.middleware import TenantMiddleware


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


async def multi_client(tmp_path, *, inject_user: bool = True) -> AsyncIterator[AsyncClient]:
    app, cleanup = await _build_app(
        tmp_path, requires_auth=True, csrf_protect=False, inject_user=inject_user
    )
    app.add_middleware(HeaderTenant)  # inner: runs after TenantMiddleware
    app.add_middleware(TenantMiddleware)  # makes detect_mode say MULTI
    assert tenancy.configure(app) is TenancyMode.MULTI
    app.state.sm.db.tenant_strict = True
    try:
        async with _client_for(app) as client:
            yield client
    finally:
        await cleanup()


def as_tenant(tenant: str) -> dict[str, str]:
    return {"x-tenant": tenant}
