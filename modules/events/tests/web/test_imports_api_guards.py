"""The import API's guards: the body ceiling, CSRF and tenant isolation."""

from __future__ import annotations

import pytest
from sm_events.feeds.importing import launch as launch_module
from sm_events.models import EventImport
from sm_events.module import EventsModule
from sqlalchemy import select

from tests.support.access import seed_calendars
from tests.web.test_imports_api import BASE, MGR, upload


@pytest.fixture(autouse=True)
def _eager(monkeypatch):
    monkeypatch.setattr(launch_module, "celery_eager", lambda: True)


@pytest.fixture
async def world(client):
    async with client.db_state.session_factory() as db:
        cals = await seed_calendars(db)
        await db.commit()
    return client, cals


async def test_body_limit_registered(world):
    """A 22 MB body is refused by the framework before the handler runs."""
    from simple_module_core.body_limits import BodyLimitRegistry
    from simple_module_hosting._body_limit import BodyLimitMiddleware

    client, _cals = world
    registry = BodyLimitRegistry()
    EventsModule().register_body_limits(registry)
    client.app.add_middleware(BodyLimitMiddleware, max_bytes=1024 * 1024, registry=registry)
    big = await client.post(
        BASE,
        content=b"x" * (22 * 1024 * 1024),
        headers={**MGR, "content-type": "multipart/form-data; boundary=b"},
    )
    assert big.status_code == 413
    async with client.db_state.session_factory() as db:
        assert (await db.execute(select(EventImport))).scalars().all() == []


async def test_writes_need_csrf(csrf_client):
    client = csrf_client
    async with client.db_state.session_factory() as db:
        cals = await seed_calendars(db)
        await db.commit()
    refused = await upload(client, cals["P"])
    assert refused.status_code == 403 and "CSRF" in refused.json()["detail"]
    token = (await client.get("/token")).json()["token"]
    ok = await upload(client, cals["P"], headers={**MGR, "X-CSRF-Token": token})
    assert ok.status_code == 202
    url = f"{BASE}/{ok.json()['id']}"
    assert (
        await client.post(f"{url}/apply", json={"publish": False}, headers=MGR)
    ).status_code == 403
    assert (await client.delete(url, headers=MGR)).status_code == 403
    assert (await client.delete(url, headers={**MGR, "X-CSRF-Token": token})).status_code == 204


@pytest.mark.unbound_tenant
async def test_tenant_isolation(multi_client):
    from sm_events.core.tenancy import tenant_scope

    client = multi_client
    cals = {}
    for tenant in ("a", "b"):
        with tenant_scope(tenant):
            async with client.db_state.session_factory() as db:
                cals[tenant] = await seed_calendars(db)
                await db.commit()
    in_a, in_b = {**MGR, "X-Test-Tenant": "a"}, {**MGR, "X-Test-Tenant": "b"}
    made = await upload(client, cals["a"]["P"], headers=in_a)
    assert made.status_code == 202
    url = f"{BASE}/{made.json()['id']}"
    for method, suffix, extra in (
        ("get", "", {}),
        ("get", "/items", {}),
        ("post", "/apply", {"json": {"publish": False}}),
        ("delete", "", {}),
    ):
        got = await getattr(client, method)(url + suffix, headers=in_b, **extra)
        assert got.status_code == 404, (method, suffix)
    assert (await client.get(BASE, headers=in_b)).json()["total"] == 0
    # A calendar of another tenant is no target.
    other = await upload(client, cals["a"]["I"], headers=in_b)
    assert other.status_code == 404
    assert (
        await client.post(f"{url}/apply", json={"publish": False}, headers=in_a)
    ).status_code == 202
