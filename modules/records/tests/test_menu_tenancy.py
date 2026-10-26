"""Per-tenant sidebar entries on a multi-tenant host (upstream #340).

The per-type entries come from a provider the framework evaluates per request,
after tenant resolution, so each organisation's sidebar lists its own
``show_in_menu`` types — and none of another's, whichever tenant the previous
request on this worker was for. Before the provider existed a multi-tenant host
showed no per-type entries at all.

The resolver stands in for the tenants module's membership lookup, as in
``test_tenancy_resolved.py``: ``X-Test-Active-Tenant`` names the active
organisation (``-`` for none).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from simple_module_hosting.middleware import TenantResolution
from sm_records.settings import RecordsSettings
from sm_records.tenancy import tenant_scope

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_VIEWER, build_app, roles, seed_type

pytestmark = pytest.mark.unbound_tenant

_INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}
_ACTIVE = "X-Test-Active-Tenant"


async def _membership_resolver(request) -> TenantResolution:
    raw = request.headers.get(_ACTIVE)
    return TenantResolution(None if raw in (None, "-") else raw, "session")


@pytest_asyncio.fixture
async def multi(tmp_path) -> AsyncIterator[AsyncClient]:
    """``acme`` shows Products, ``globex`` shows Secrets (narrowed to editors);
    both also have a type that did not ask for an entry."""
    app, db_state = await build_app(tmp_path, tenancy="multi", menus=True)
    app.state.tenant_resolver = _membership_resolver
    with tenant_scope("acme"):
        await seed_type(db_state, "product", [], label_plural="Products", show_in_menu=True)
        await seed_type(db_state, "quiet", [], label_plural="Quiets")
    with tenant_scope("globex"):
        await seed_type(
            db_state,
            "secret",
            [],
            label_plural="Secrets",
            show_in_menu=True,
            allowed_roles=[ROLE_EDITOR],
        )
        await seed_type(db_state, "quiet", [], label_plural="Quiets")
    module = app.state.records_module
    await module.on_startup(app)
    # The default window, so a second request for a tenant is served from
    # the per-tenant cache: the leakage these tests look for is the cache's.
    module.settings = RecordsSettings(menu_refresh_seconds=300)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client
    await db_state.engine.dispose()


async def _sidebar(client: AsyncClient, active: str, *names: str) -> list[str]:
    resp = await client.get(
        "/admin/records/", headers={**roles(*names), _ACTIVE: active, **_INERTIA}
    )
    assert resp.status_code == 200, resp.text
    return [item["label"] for item in resp.json()["props"]["menus"]["adminSidebar"]]


async def test_each_organisation_sees_its_own_types(multi):
    assert await _sidebar(multi, "acme", ROLE_EDITOR) == ["All record types", "Products"]
    assert await _sidebar(multi, "globex", ROLE_EDITOR) == ["All record types", "Secrets"]


async def test_nothing_leaks_between_requests_for_different_tenants(multi):
    for _ in range(2):  # the second round is served from the per-tenant cache
        assert await _sidebar(multi, "globex", ROLE_EDITOR) == ["All record types", "Secrets"]
        assert await _sidebar(multi, "acme", ROLE_EDITOR) == ["All record types", "Products"]


async def test_narrowing_applies_within_the_tenant(multi):
    # A viewer is not on Secrets' ``allowed_roles``; nor is an admin.
    assert await _sidebar(multi, "globex", ROLE_VIEWER) == ["All record types"]
    assert await _sidebar(multi, "globex", ADMIN) == ["All record types"]
    assert await _sidebar(multi, "acme", ADMIN) == ["All record types", "Products"]
