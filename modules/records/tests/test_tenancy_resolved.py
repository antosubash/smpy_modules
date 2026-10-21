"""#112: the records admin surface binds the tenant the *framework* resolved.

Pagebuilder, news and billing bind ``request.state.tenant_id``; records used to
bind ``user.tenant_id`` instead, so a member whose active organisation was not
the one on their user object edited records in a different tenant from their
pages and articles. Now every module follows one rule:

* single-tenant host → ``default``;
* multi-tenant host → whatever ``TenantMiddleware`` resolved — here a
  registered ``tenant_resolver``, standing in for the tenants module's
  membership lookup, whose answer is final;
* nothing resolved → 403 ``tenant_required``, pagebuilder's status and code.

The resolver reads ``X-Test-Active-Tenant`` (``-`` for none), and the stub
user's own ``tenant_id`` is deliberately set to the *other* tenant on every
request, so a test passes only if records ignores it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from simple_module_db.listeners import current_tenant_id
from simple_module_hosting.middleware import TenantMiddleware, TenantResolution
from sm_records import boot, constants
from sm_records.models import RecordStatus
from sm_records.tenancy import (
    TenancyMode,
    bind_admin,
    bind_public,
    configure,
    detect_mode,
    tenant_scope,
)

from tests.app_harness import ADMIN, TEST_TENANT_HEADER, build_app, roles, seed_record, seed_type

pytestmark = pytest.mark.unbound_tenant

_INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}
_ACTIVE = "X-Test-Active-Tenant"
_OTHER = {"acme": "globex", "globex": "acme"}
_FIELDS = [{"key": "title", "type": "text", "label": "Title"}]


async def _membership_resolver(request) -> TenantResolution:
    raw = request.headers.get(_ACTIVE)
    return TenantResolution(None if raw in (None, "-") else raw, "session")


@pytest_asyncio.fixture
async def resolved(tmp_path) -> AsyncIterator[AsyncClient]:
    app, db_state = await build_app(tmp_path, tenancy="multi")
    boot.mount_public_router(app, getattr(app.state, constants.PACKAGE).settings)
    app.state.tenant_resolver = _membership_resolver
    uuids = {}
    for tenant in ("acme", "globex"):
        with tenant_scope(tenant):
            rtype = await seed_type(db_state, "post", _FIELDS, label=tenant, is_public=True)
            record = await seed_record(
                db_state, rtype, {"title": tenant}, status=RecordStatus.PUBLISHED
            )
            uuids[tenant] = record.uuid
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        client.uuids = uuids  # type: ignore[attr-defined]
        yield client
    await db_state.engine.dispose()


def _in(active: str) -> dict[str, str]:
    """Signed in as ``admin``, active in ``active``, user object saying the other."""
    return {**roles(ADMIN), _ACTIVE: active, TEST_TENANT_HEADER: _OTHER.get(active, "acme")}


@pytest.mark.parametrize("tenant", ["acme", "globex"])
async def test_every_admin_read_sees_the_active_tenant_only(resolved, tenant):
    headers = _in(tenant)
    mine, theirs = resolved.uuids[tenant], resolved.uuids[_OTHER[tenant]]  # type: ignore[attr-defined]

    types = await resolved.get("/api/records/types", headers=headers)
    assert [t["label"] for t in types.json()["items"]] == [tenant]
    one_type = await resolved.get("/api/records/types/post", headers=headers)
    assert one_type.json()["label"] == tenant
    export = await resolved.get("/api/records/types/post/export", headers=headers)
    assert export.status_code == 200, export.text
    listed = await resolved.get("/api/records/types/post/records", headers=headers)
    assert [r["uuid"] for r in listed.json()["items"]] == [mine]
    assert (
        await resolved.get(f"/api/records/types/post/records/{mine}", headers=headers)
    ).status_code == 200
    assert (
        await resolved.get(f"/api/records/types/post/records/{theirs}", headers=headers)
    ).status_code == 404

    for path in ("/admin/records/", "/admin/records/post", f"/admin/records/post/{mine}"):
        screen = await resolved.get(path, headers={**headers, **_INERTIA})
        assert screen.status_code == 200, (path, screen.text)
        assert screen.json()["props"]["tenant"] == tenant
    foreign = await resolved.get(f"/admin/records/post/{theirs}", headers={**headers, **_INERTIA})
    assert foreign.status_code == 404
    assert current_tenant_id.get() is None


async def test_writes_land_in_the_active_tenant(resolved):
    created = await resolved.post(
        "/api/records/types/post/records", json={"data": {"title": "new"}}, headers=_in("globex")
    )
    assert created.status_code == 201, created.text
    uuid = created.json()["uuid"]
    path = f"/api/records/types/post/records/{uuid}"
    assert (await resolved.get(path, headers=_in("globex"))).status_code == 200
    assert (await resolved.get(path, headers=_in("acme"))).status_code == 404


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/records/types"),
        ("GET", "/api/records/types/post/records"),
        ("POST", "/api/records/types/post/records"),
        ("GET", "/admin/records/"),
        ("GET", "/admin/records/post"),
    ],
)
async def test_nothing_resolved_is_pagebuilders_403_whatever_the_user_object_says(
    resolved, method, path
):
    # The user object names a tenant and so does the framework's header; the
    # resolver answered none, and that answer is final.
    headers = {**_in("-"), TEST_TENANT_HEADER: "acme", "X-Tenant-ID": "acme", **_INERTIA}
    body = {"data": {}} if method == "POST" else None
    response = await resolved.request(method, path, headers=headers, json=body)
    assert response.status_code == 403, response.text
    if path.startswith("/api/"):
        assert response.json()["code"] == "tenant_required"
    assert current_tenant_id.get() is None


async def test_the_public_read_follows_the_same_resolution(resolved):
    for tenant in ("acme", "globex"):
        listed = await resolved.get("/api/records/public/post", headers={_ACTIVE: tenant})
        assert [r["uuid"] for r in listed.json()["items"]] == [resolved.uuids[tenant]]  # type: ignore[attr-defined]
    nothing = await resolved.get("/api/records/public/post", headers={_ACTIVE: "-"})
    assert nothing.status_code == 404


async def test_a_child_app_detected_single_still_binds_the_parents_tenant():
    """Fail closed at request time (#192): the child app has no
    ``TenantMiddleware`` of its own, so its detection says SINGLE, but the
    parent's middleware resolved a tenant first — that one is bound, never
    ``default``."""
    child = FastAPI()
    for path, dependency in (("/admin", bind_admin), ("/public", bind_public)):
        router = APIRouter(dependencies=[Depends(dependency)])

        @router.get(path)
        async def seen() -> dict:
            return {"tenant": current_tenant_id.get()}

        child.include_router(router)
    configure(child)
    assert detect_mode(child) is TenancyMode.SINGLE

    parent = FastAPI()
    parent.state.tenant_resolver = _membership_resolver
    parent.mount("/child", child)
    parent.add_middleware(TenantMiddleware, header="X-Tenant-ID")
    async with AsyncClient(transport=ASGITransport(app=parent), base_url="http://t") as client:
        for path in ("/child/admin", "/child/public"):
            got = await client.get(path, headers={_ACTIVE: "acme"})
            assert got.json() == {"tenant": "acme"}, path
            # Nothing upstream: the single-tenant default fills the gap.
            assert (await client.get(path)).json() == {"tenant": "default"}
    assert current_tenant_id.get() is None
