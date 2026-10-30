"""``images.collection`` through the framework's real ``/api/sharing/shares`` routes.

The sharing router binds no tenant of its own: it calls the loader images
registered (``resource_types``) inside a request no images dependency touched.
On a single-tenant host nothing is bound there, so the loader has to apply
images' tenancy rule itself (phase 2 review, P1-1) - and stay fail-closed on a
multi-tenant host that resolved no tenant.

Every test here is ``unbound_tenant``: the suite's autouse ``default`` binding
would hide exactly the bug these pin.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sharing.endpoints.api import router as sharing_router
from sharing.models import ResourceShare
from simple_module_core.resources import ResourceTypeRegistry
from simple_module_core.user_directory import DirectoryUser
from simple_module_db import tenant_context
from simple_module_db.listeners import TenantIsolationError
from sm_images import constants
from sm_images.models import Collection
from sm_images.tenancy import ALL_TENANTS, tenant_scope
from sm_images.tenancy import _mode as _tenancy_mode
from sqlalchemy import select
from starlette.applications import Starlette
from starlette.routing import Mount

from tests.support.isolation import ACME, GLOBEX, as_
from tests.support.stub_auth import as_user, user_uuid

pytestmark = pytest.mark.unbound_tenant

SHARES = "/api/sharing/shares"
RTYPE = "images.collection"
OWNER_PERMS = ("images.view", "images.create", "sharing.share")


class Directory:
    """Knows every header user: ``get_many`` is all the grant path asks."""

    entity_type = None

    async def get_many(self, db, ids, *, with_roles=False):
        return {i: DirectoryUser(id=i, email=f"{i}@x", full_name=None) for i in ids}

    async def search(self, db, term, *, limit):
        return []

    def match_ids(self, term):
        return None


def mount_sharing(app) -> None:
    """What ``create_app`` does for the sharing module and images' resource type."""
    registry = ResourceTypeRegistry()
    app.state.images_module.register_resource_types(registry)
    app.state.sm.resource_types = registry
    app.state.user_directory = Directory()
    app.include_router(sharing_router, prefix="/api/sharing")


async def make_collection(client, headers) -> str:
    made = await client.post(
        constants.ROUTE_PREFIX_API + "/collections", json={"name": "T"}, headers=headers
    )
    assert made.status_code == 201, made.text
    return made.json()["id"]


def grant_body(cid: str, who: str = "vic", role: str = "view") -> dict:
    return {"resource_type": RTYPE, "resource_id": cid, "subject_id": user_uuid(who), "role": role}


async def share_rows(client) -> list[ResourceShare]:
    async with client.db_state.session_factory() as s:
        stmt = select(ResourceShare).execution_options(all_tenants=True, **{ALL_TENANTS: True})
        return list((await s.execute(stmt)).scalars())


async def test_grant_list_revoke_on_a_single_tenant_host(client):
    mount_sharing(client.app)
    olga = as_user("olga", OWNER_PERMS)
    vic = as_user("vic", ("images.view",))
    cid = await make_collection(client, olga)
    assert (await client.get(f"/api/images/collections/{cid}", headers=vic)).status_code == 404

    granted = await client.post(SHARES, json=grant_body(cid), headers=olga)
    assert granted.status_code == 201, granted.text
    assert (await client.get(f"/api/images/collections/{cid}", headers=vic)).status_code == 200

    listed = await client.get(
        SHARES, params={"resource_type": RTYPE, "resource_id": cid}, headers=olga
    )
    assert listed.status_code == 200, listed.text
    assert [s["subject_id"] for s in listed.json()] == [user_uuid("vic")]
    assert [r.tenant_id for r in await share_rows(client)] == ["default"]

    revoked = await client.delete(f"{SHARES}/{granted.json()['id']}", headers=olga)
    assert revoked.status_code == 204, revoked.text
    assert await share_rows(client) == []
    assert (await client.get(f"/api/images/collections/{cid}", headers=vic)).status_code == 404


async def test_a_stranger_cannot_share_on_a_single_tenant_host(client):
    mount_sharing(client.app)
    cid = await make_collection(client, as_user("olga", OWNER_PERMS))
    sam = as_user("sam", ("images.view", "sharing.share"))
    got = await client.post(SHARES, json=grant_body(cid), headers=sam)
    assert got.status_code == 404, got.text
    listed = await client.get(
        SHARES, params={"resource_type": RTYPE, "resource_id": cid}, headers=sam
    )
    assert listed.status_code == 404


async def test_grant_list_revoke_stays_in_the_tenant_on_a_multi_tenant_host(two_tenants):
    client = two_tenants
    mount_sharing(client.app)
    olga = as_(ACME, "olga", OWNER_PERMS)
    cid = await make_collection(client, olga)

    granted = await client.post(SHARES, json=grant_body(cid), headers=olga)
    assert granted.status_code == 201, granted.text
    assert [r.tenant_id for r in await share_rows(client)] == [ACME]

    # globex, even holding manage, never reaches acme's collection: no grant, no list.
    boss = as_(GLOBEX, "gus", ("images.view", "images.manage", "sharing.share"))
    assert (await client.post(SHARES, json=grant_body(cid, "gil"), headers=boss)).status_code == 404
    query = {"resource_type": RTYPE, "resource_id": cid}
    assert (await client.get(SHARES, params=query, headers=boss)).status_code == 404
    assert len(await share_rows(client)) == 1

    listed = await client.get(SHARES, params=query, headers=olga)
    assert [s["subject_id"] for s in listed.json()] == [user_uuid("vic")]
    revoked = await client.delete(f"{SHARES}/{granted.json()['id']}", headers=olga)
    assert revoked.status_code == 204, revoked.text
    assert await share_rows(client) == []


async def test_multi_tenant_host_with_no_tenant_resolved_is_refused(two_tenants):
    """Fail closed: no fallback to ``default`` when the host is multi-tenant."""
    client = two_tenants
    mount_sharing(client.app)
    cid = await make_collection(client, as_(ACME, "olga", OWNER_PERMS))
    nobody = as_(None, "olga", OWNER_PERMS)
    got = await client.post(SHARES, json=grant_body(cid), headers=nobody)
    assert (got.status_code, got.json()["code"]) == (403, constants.TENANT_REQUIRED_CODE)
    assert await share_rows(client) == []


async def test_an_upstream_tenant_wins_over_a_single_detection(client):
    """A mis-detected child app: something upstream bound ``acme``; the loader
    reads in acme, never in ``default``."""
    mount_sharing(client.app)
    olga = as_user("olga", OWNER_PERMS)
    cid = await make_collection(client, olga)  # lands in "default"
    with tenant_context(ACME):
        got = await client.post(SHARES, json=grant_body(cid), headers=olga)
    assert got.status_code == 404, got.text


async def test_single_detection_on_a_strict_engine_fails_closed(client):
    """Images says single, the engine is strict (the host is multi-tenant) and
    nothing is bound: the read is refused, never answered from ``default``."""
    mount_sharing(client.app)
    olga = as_user("olga", OWNER_PERMS)
    cid = await make_collection(client, olga)
    client.db_state.tenant_strict = True
    with pytest.raises(TenantIsolationError):
        await client.post(SHARES, json=grant_body(cid), headers=olga)


class UpstreamTenant:
    """A layer that resolved ``acme`` onto ``request.state`` - as a parent's
    ``TenantMiddleware`` does - without binding the tenant contextvar."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope.setdefault("state", {})["tenant_id"] = ACME
        await self.app(scope, receive, send)


async def test_an_upstream_request_state_tenant_wins_over_a_single_detection(client):
    """Round 2: the loader follows ``request.state.tenant_id`` (what
    ``resolve_admin`` reads first), not images' boot-time mode."""
    client.app.add_middleware(UpstreamTenant)
    mount_sharing(client.app)
    with tenant_scope(ACME):
        async with client.db_state.session_factory() as s:
            row = Collection(slug="a", name="A", owner_id=user_uuid("olga"))
            s.add(row)
            await s.commit()
    olga = as_user("olga", OWNER_PERMS)
    got = await client.post(SHARES, json=grant_body(str(row.id)), headers=olga)
    assert got.status_code == 201, got.text


async def test_a_mounted_child_the_framework_cannot_answer_for_fails_closed(client, monkeypatch):
    """Round 2: a child app mounted under a parent, with no framework answer for
    its mode, is ``MULTI`` per request (``scope_mode``): no fallback to default."""
    mount_sharing(client.app)
    olga = as_user("olga", OWNER_PERMS)
    cid = await make_collection(client, olga)
    monkeypatch.setattr(_tenancy_mode, "_framework_mode", lambda app: None)
    parent = Starlette(routes=[Mount("/child", app=client.app)])
    async with AsyncClient(transport=ASGITransport(app=parent), base_url="http://p") as outer:
        got = await outer.post(f"/child{SHARES}", json=grant_body(cid), headers=olga)
    assert (got.status_code, got.json()["code"]) == (403, constants.TENANT_REQUIRED_CODE)
    assert await share_rows(client) == []
