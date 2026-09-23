"""The request binding on the module's own routers — tenancy design §A.3, §A.4, K6.

Two things are pinned here:

* **The order.** ``bind_admin``/``bind_public`` are the *first* dependency of
  the admin API, the views and the public API. Yield dependencies exit in
  reverse, and ``get_db`` commits on its way out, so the binding has to outlive
  it or an unflushed ``add()`` reaches the database with no tenant. Proven with
  the routers' real dependency lists, and against a control that puts the
  binding second and is refused by the guard.
* **Single mode is the whole behaviour of a host without ``TenantMiddleware``**
  (K6): every request runs in ``default`` whatever the user's ``tenant_id`` or
  an ``X-Tenant-ID`` header says.

Every test runs **unbound**, so what binds the request is the router and not
``conftest._default_tenant``.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter, Depends
from simple_module_db.listeners import current_tenant_id
from sm_records import boot
from sm_records._tenant_guard import is_guarded
from sm_records.deps import request_db, require_view
from sm_records.endpoints.api import router as api_router
from sm_records.endpoints.api.public import router as public_router
from sm_records.endpoints.views import router as views_router
from sm_records.models import RecordType
from sm_records.settings import RecordsSettings
from sm_records.tenancy import (
    DEFAULT_TENANT,
    TenantUnbound,
    all_tenants,
    bind_admin,
    bind_public,
    tenant_scope,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.app_harness import ADMIN, TEST_TENANT_HEADER, roles, seed_record, seed_type
from tests.pg_support import make_db_state

pytestmark = pytest.mark.unbound_tenant

_INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}
_ELSEWHERE = {TEST_TENANT_HEADER: "acme", "X-Tenant-ID": "globex"}
"""A user row in ``acme`` and a header naming ``globex``: single mode ignores both."""


def test_the_binding_is_the_first_dependency_of_every_records_router():
    """First on the router is first on every route: FastAPI puts a parent
    router's dependencies ahead of an included one's, and ``views_types`` is
    included into ``views``."""
    assert api_router.dependencies[0].dependency is bind_admin
    assert views_router.dependencies[0].dependency is bind_admin
    assert public_router.dependencies[0].dependency is bind_public


def _probe(dependencies: list) -> APIRouter:
    """A route that adds a type and **never flushes**: only ``get_db``'s
    commit, on the way out, writes it."""
    router = APIRouter(dependencies=dependencies)

    @router.post("/probe/{key}")
    async def probe(key: str, db: AsyncSession = Depends(request_db)) -> dict:
        db.add(RecordType(key=key, label=key, label_plural=key, fields=[]))
        return {"bound": current_tenant_id.get()}

    return router


async def _stored(db_state, key: str) -> RecordType | None:
    async with db_state.session_factory() as session:
        stmt = all_tenants(select(RecordType).where(RecordType.key == key))
        return (await session.execute(stmt)).scalars().first()


async def test_an_unflushed_add_is_stamped_at_commit_and_the_tenant_reset_after(client):
    """The real admin router's dependency list, in front of a route of our own."""
    client.app.include_router(_probe([*api_router.dependencies, require_view]))
    response = await client.post("/probe/late", headers={**roles(ADMIN), **_ELSEWHERE})
    assert response.json() == {"bound": DEFAULT_TENANT}
    assert current_tenant_id.get() is None, "the request's tenant leaked into the test"
    stored = await _stored(client.db_state, "late")
    assert stored is not None and stored.tenant_id == DEFAULT_TENANT


async def test_the_control_binding_after_get_db_commits_unbound_and_is_refused(client):
    """What the order rule prevents: the permission check opens ``get_db``
    first, so it exits last, after the binding has already been reset."""
    client.app.include_router(_probe([require_view, Depends(bind_admin)]))
    with pytest.raises(TenantUnbound):
        await client.post("/probe/early", headers=roles(ADMIN))
    assert await _stored(client.db_state, "early") is None


async def test_single_mode_writes_through_the_api_land_in_default(client):
    created = await client.post(
        "/api/records/types",
        json={"key": "note", "label": "Note", "fields": []},
        headers={**roles(ADMIN), **_ELSEWHERE},
    )
    assert created.status_code == 201, created.text
    stored = await _stored(client.db_state, "note")
    assert stored is not None and stored.tenant_id == DEFAULT_TENANT

    listed = await client.get("/api/records/types", headers={**roles(ADMIN), **_ELSEWHERE})
    assert [item["key"] for item in listed.json()["items"]] == ["note"]
    assert current_tenant_id.get() is None


async def test_single_mode_ignores_a_type_in_another_tenant(client):
    """The migration leaves everything in ``default``; a row outside it is
    unreachable in single mode — the §J "multi → single" case."""
    with tenant_scope("acme"):
        await seed_type(client.db_state, "hidden", [])
    with tenant_scope(DEFAULT_TENANT):
        await seed_type(client.db_state, "shown", [])
    listed = await client.get("/api/records/types", headers={**roles(ADMIN), **_ELSEWHERE})
    assert [item["key"] for item in listed.json()["items"]] == ["shown"]
    missing = await client.get("/api/records/types/hidden", headers=roles(ADMIN))
    assert missing.status_code == 404


async def test_every_records_screen_carries_the_tenant_and_the_mode(client):
    with tenant_scope(DEFAULT_TENANT):
        rtype = await seed_type(client.db_state, "note", [])
        record = await seed_record(client.db_state, rtype, {})
    for path in (
        "/admin/records/",
        "/admin/records/types/new",
        "/admin/records/types/note",
        "/admin/records/note",
        "/admin/records/note/new",
        f"/admin/records/note/{record.uuid}",
    ):
        response = await client.get(path, headers={**roles(ADMIN), **_INERTIA, **_ELSEWHERE})
        assert response.status_code == 200, (path, response.text)
        props = response.json()["props"]
        assert (props["tenant"], props["tenancy_mode"]) == (DEFAULT_TENANT, "single"), path
    assert current_tenant_id.get() is None


async def test_single_mode_public_reads_run_in_default(client):
    boot.mount_public_router(client.app, RecordsSettings())
    with tenant_scope(DEFAULT_TENANT):
        await seed_type(client.db_state, "note", [], is_public=True)
    response = await client.get("/api/records/public/note", headers={"X-Tenant-ID": "acme"})
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
    assert current_tenant_id.get() is None


async def test_on_startup_puts_the_guard_on_the_hosts_session_class(client):
    """The harness installs it itself; a database it never saw shows that the
    module's own ``on_startup`` does, as it must in a real host."""
    fresh = await make_db_state()
    try:
        client.app.state.sm.db = fresh
        assert not is_guarded(fresh.sync_session_class)
        with tenant_scope(DEFAULT_TENANT):
            await client.app.state.records_module.on_startup(client.app)
        assert is_guarded(fresh.sync_session_class)
    finally:
        await fresh.engine.dispose()
