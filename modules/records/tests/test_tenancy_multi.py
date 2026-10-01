"""A multi-tenant host: the admin surface refuses, the public one 404s — K7.

The harness is built with ``tenancy="multi"``: the framework's own
``TenantMiddleware`` reading ``X-Tenant-ID``, and ``X-Test-Tenant`` as the
signed-in user's ``tenant_id``. ``acme`` and ``globex`` each hold a public
type keyed ``post`` with one published record.

* A user with a tenant works in it, and a header cannot move them.
* A user with **no** tenant is 403 ``tenant_required`` on the API and on the
  screens, with or without a header — unless ``admin_header_tenant`` is on and
  they hold ``admin``, in which case the header's tenant is theirs.
* An anonymous read with no tenant is the public surface's one 404, body and
  all; with a header it reads that tenant only.

Runs **unbound** (``@pytest.mark.unbound_tenant``): the suite-wide ``default``
binding would otherwise sit under every request that resolved no tenant,
masking exactly the case these tests are about.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from simple_module_db.listeners import current_tenant_id
from sm_records import boot, constants
from sm_records.models import RecordStatus
from sm_records.tenancy import tenant_scope

from tests.app_harness import (
    ADMIN,
    ROLE_MANAGER,
    TEST_TENANT_HEADER,
    build_app,
    roles,
    seed_record,
    seed_type,
)

pytestmark = pytest.mark.unbound_tenant

_INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}
_PUBLIC = "/api/records/public"


@pytest_asyncio.fixture
async def multi(tmp_path) -> AsyncIterator[AsyncClient]:
    app, db_state = await build_app(tmp_path, tenancy="multi")
    boot.mount_public_router(app, getattr(app.state, constants.PACKAGE).settings)
    uuids = {}
    for tenant in ("acme", "globex"):
        with tenant_scope(tenant):
            rtype = await seed_type(db_state, "post", [], is_public=True, label=tenant)
            record = await seed_record(db_state, rtype, {}, status=RecordStatus.PUBLISHED)
            uuids[tenant] = record.uuid
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        client.app = app  # type: ignore[attr-defined]
        client.uuids = uuids  # type: ignore[attr-defined]
        yield client
    await db_state.engine.dispose()


def _as(tenant: str | None, *role_names: str, header: str | None = None) -> dict[str, str]:
    headers = roles(*(role_names or (ADMIN,)))
    if tenant is not None:
        headers[TEST_TENANT_HEADER] = tenant
    if header is not None:
        headers["X-Tenant-ID"] = header
    return headers


async def _type_labels(client: AsyncClient, headers: dict[str, str]) -> list[str]:
    response = await client.get("/api/records/types", headers=headers)
    assert response.status_code == 200, response.text
    return [item["label"] for item in response.json()["items"]]


async def test_a_user_works_in_their_own_tenant_and_a_header_cannot_move_them(multi):
    assert await _type_labels(multi, _as("acme")) == ["acme"]
    assert await _type_labels(multi, _as("globex")) == ["globex"]
    assert await _type_labels(multi, _as("acme", header="globex")) == ["acme"]
    assert current_tenant_id.get() is None


async def test_a_write_lands_in_the_users_tenant(multi):
    created = await multi.post(
        "/api/records/types/post/records", json={"data": {}}, headers=_as("globex")
    )
    assert created.status_code == 201, created.text
    uuid = created.json()["uuid"]
    assert (
        await multi.get(f"/api/records/types/post/records/{uuid}", headers=_as("globex"))
    ).status_code == 200
    assert (
        await multi.get(f"/api/records/types/post/records/{uuid}", headers=_as("acme"))
    ).status_code == 404


_ADMIN_SURFACE = [
    ("GET", "/api/records/types"),
    ("POST", "/api/records/types"),
    ("GET", "/api/records/types/post/records"),
    ("GET", "/admin/records/"),
    ("GET", "/admin/records/post"),
    ("GET", "/admin/records/types/post"),
]


@pytest.mark.parametrize("header", [None, "acme"])
@pytest.mark.parametrize(("method", "path"), _ADMIN_SURFACE)
async def test_a_user_without_a_tenant_is_refused_header_or_not(multi, method, path, header):
    headers = {**_as(None, header=header), **_INERTIA}
    body = {"key": "page", "label": "Page", "fields": []} if method == "POST" else None
    response = await multi.request(method, path, headers=headers, json=body)
    assert response.status_code == 403, response.text
    if path.startswith("/api/"):
        assert response.json()["code"] == "tenant_required"
    assert current_tenant_id.get() is None


def _header_tenant(client: AsyncClient, on: bool) -> None:
    settings = getattr(client.app.state, constants.PACKAGE).settings  # type: ignore[attr-defined]
    settings.admin_header_tenant = on


async def test_admin_header_tenant_lets_an_admin_without_a_tenant_use_the_header(multi):
    _header_tenant(multi, True)
    assert await _type_labels(multi, _as(None, header="globex")) == ["globex"]
    screen = await multi.get("/admin/records/", headers={**_as(None, header="acme"), **_INERTIA})
    assert screen.status_code == 200
    assert screen.json()["props"]["tenant"] == "acme"
    # Their own tenant still wins when they have one — the setting is only
    # for the account that has none.
    assert await _type_labels(multi, _as("acme", header="globex")) == ["acme"]


@pytest.mark.parametrize(
    ("role", "header"),
    [(ADMIN, None), (ADMIN, "not a tenant"), (ROLE_MANAGER, "acme")],
    ids=["admin-no-header", "admin-bad-header", "non-admin"],
)
async def test_admin_header_tenant_still_refuses_everyone_else(multi, role, header):
    _header_tenant(multi, True)
    response = await multi.get("/api/records/types", headers=_as(None, role, header=header))
    assert response.status_code == 403
    assert response.json()["code"] == "tenant_required"


async def test_the_screens_say_which_tenant_and_mode(multi):
    response = await multi.get("/admin/records/post", headers={**_as("globex"), **_INERTIA})
    assert response.status_code == 200
    props = response.json()["props"]
    assert (props["tenant"], props["tenancy_mode"]) == ("globex", "multi")


async def test_an_anonymous_read_with_no_tenant_is_the_public_404(multi):
    unknown = await multi.get(f"{_PUBLIC}/nope", headers={"X-Tenant-ID": "acme"})
    for headers in ({}, {"X-Tenant-ID": "a b"}):
        missing = await multi.get(f"{_PUBLIC}/post", headers=headers)
        assert (missing.status_code, missing.json()) == (unknown.status_code, unknown.json())
        assert missing.status_code == 404
        one = await multi.get(f"{_PUBLIC}/post/{multi.uuids['acme']}", headers=headers)
        assert (one.status_code, one.json()) == (404, unknown.json())
    assert current_tenant_id.get() is None


async def test_an_anonymous_read_sees_the_header_tenant_only(multi):
    for tenant, other in (("acme", "globex"), ("globex", "acme")):
        listed = await multi.get(f"{_PUBLIC}/post", headers={"X-Tenant-ID": tenant})
        assert [item["uuid"] for item in listed.json()["items"]] == [multi.uuids[tenant]]
        foreign = await multi.get(
            f"{_PUBLIC}/post/{multi.uuids[other]}", headers={"X-Tenant-ID": tenant}
        )
        assert foreign.status_code == 404
