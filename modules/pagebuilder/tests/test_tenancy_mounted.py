"""The real pagebuilder app, mounted as a child of a multi-tenant parent (#192).

The child has no ``TenantMiddleware`` of its own, so it detects ``SINGLE``;
the parent resolves the tenant. Every request must run in the parent's
tenant, and a public page served that way must stay out of shared caches.
"""

from __future__ import annotations

import pytest
from conftest import _build_app
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pagebuilder import tenancy
from pagebuilder.tenancy import TenancyMode
from tenant_app import HeaderTenant, as_tenant

pytestmark = [pytest.mark.asyncio, pytest.mark.unbound_tenant]

API = "/child/api/pagebuilder/pages"


@pytest.fixture
async def parent(tmp_path):
    child, cleanup = await _build_app(
        tmp_path, requires_auth=True, csrf_protect=False, inject_user=True
    )
    assert tenancy.detect_mode(child) is TenancyMode.SINGLE
    app = FastAPI()
    app.add_middleware(HeaderTenant)
    app.mount("/child", child)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            client.child = child  # type: ignore[attr-defined]
            yield client
    finally:
        await cleanup()


async def _publish(client: AsyncClient, tenant: str, slug: str, title: str) -> None:
    headers = as_tenant(tenant)
    body = {"title": title, "slug": slug, "draft_data": {"content": []}}
    page = await client.post(API, json=body, headers=headers)
    assert page.status_code == 201, page.text
    done = await client.post(f"{API}/{page.json()['id']}/publish", json={}, headers=headers)
    assert done.status_code == 200, done.text


def _sign_out(child: FastAPI) -> None:
    """Drop the stub user, so the next request is an anonymous visitor's —
    the one whose copy a shared cache would otherwise keep."""
    from conftest import _StubAuthMiddleware

    child.user_middleware = [m for m in child.user_middleware if m.cls is not _StubAuthMiddleware]
    child.middleware_stack = None  # rebuilt on the next request


async def test_a_public_page_served_for_the_parents_tenant_is_private(parent):
    await _publish(parent, "acme", "about", "About Acme")
    _sign_out(parent.child)
    response = await parent.get("/child/p/about", headers=as_tenant("acme"))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"].startswith("private"), response.headers
    assert "Cookie" in response.headers["vary"]


async def test_another_tenant_does_not_see_it(parent):
    await _publish(parent, "acme", "about", "About Acme")
    assert (await parent.get("/child/p/about", headers=as_tenant("globex"))).status_code == 404
    listed = await parent.get(API, headers=as_tenant("globex"))
    assert listed.status_code == 200, listed.text
    assert "About Acme" not in listed.text
