"""``/api/newsletter/campaigns`` and ``/api/newsletter/lists`` over HTTP."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from simple_module_hosting.csrf import CSRF_HEADER
from sm_newsletter.core import constants

from tests.support.app import build_app
from tests.support.records_seed import restrict_list, seed_list

BASE = f"{constants.ROUTE_PREFIX_API}/campaigns"
LISTS = f"{constants.ROUTE_PREFIX_API}/lists"
VIEW = {"x-perms": constants.PERM_VIEW}
EDIT = {"x-perms": f"{constants.PERM_VIEW},{constants.PERM_EDIT}"}


@pytest_asyncio.fixture
async def built():
    app, state = await build_app()
    await seed_list(state, "default")
    yield app, state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def client(built):
    app, _ = built
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _create(client, **extra) -> dict:
    res = await client.post(
        BASE, json={"name": "Spring", "list_type_key": "news", **extra}, headers=EDIT
    )
    assert res.status_code == 201, res.text
    return res.json()


async def test_crud_round_trip(client):
    created = await _create(client, subject="Hello")
    assert created["status"] == "draft"
    assert created["revision"] == 1
    assert created["body"] == []
    cid = created["id"]

    listed = (await client.get(BASE, headers=VIEW)).json()
    assert listed["total"] == 1
    assert [c["id"] for c in listed["items"]] == [cid]
    assert "body" not in listed["items"][0]

    body = [{"type": "Divider", "props": {"id": "a"}}]
    patch = {"expected_revision": 1, "subject": "Hi", "body": body, "reply_to": "r@example.com"}
    res = await client.patch(f"{BASE}/{cid}", json=patch, headers=EDIT)
    assert res.status_code == 200, res.text
    assert res.json()["revision"] == 2
    assert res.json()["reply_to"] == "r@example.com"

    got = (await client.get(f"{BASE}/{cid}", headers=VIEW)).json()
    assert (got["subject"], got["body"]) == ("Hi", body)

    stale = await client.patch(f"{BASE}/{cid}", json={"expected_revision": 1}, headers=EDIT)
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale"

    assert (await client.delete(f"{BASE}/{cid}", headers=EDIT)).status_code == 204
    assert (await client.get(f"{BASE}/{cid}", headers=VIEW)).status_code == 404

    assert (await client.get(LISTS, headers=VIEW)).json() == ["news"]


@pytest.mark.parametrize(
    ("method", "path", "headers"),
    [
        ("POST", "", VIEW),
        ("PATCH", "/1", VIEW),
        ("DELETE", "/1", VIEW),
        ("GET", "", {}),
        ("GET", "/1", {}),
    ],
)
async def test_permissions(client, method, path, headers):
    await _create(client)
    body = {"name": "x", "list_type_key": "news"} if method == "POST" else None
    if method == "PATCH":
        body = {"expected_revision": 1, "name": "x"}
    res = await client.request(method, f"{BASE}{path}", json=body, headers=headers)
    assert res.status_code == 403
    assert (await client.get(LISTS, headers={})).status_code == 403


async def test_create_unknown_and_forbidden_lists(client, built):
    _, state = built
    await seed_list(state, "default", "vip", allowed_roles=["x"])
    res = await client.post(BASE, json={"name": "a", "list_type_key": "nope"}, headers=EDIT)
    assert (res.status_code, res.json()["code"]) == (422, "unknown_list")
    res = await client.post(BASE, json={"name": "a", "list_type_key": "vip"}, headers=EDIT)
    assert (res.status_code, res.json()["code"]) == (403, "list_forbidden")
    assert (await client.get(LISTS, headers=VIEW)).json() == ["news"]
    assert (await client.get(LISTS, headers={**VIEW, "x-roles": "x"})).json() == ["news", "vip"]


async def test_restricted_list_after_create_is_404(client, built):
    _, state = built
    cid = (await _create(client))["id"]
    await restrict_list(state, "default", "news", ["x"])
    assert (await client.get(f"{BASE}/{cid}", headers=VIEW)).status_code == 404
    res = await client.patch(f"{BASE}/{cid}", json={"expected_revision": 1}, headers=EDIT)
    assert res.status_code == 404
    assert (await client.delete(f"{BASE}/{cid}", headers=EDIT)).status_code == 404
    send = {"x-perms": constants.PERM_SEND}
    test_send = {"recipients": ["a@example.org"]}
    res = await client.post(f"{BASE}/{cid}/test-send", json=test_send, headers=send)
    assert res.status_code == 404
    assert (await client.get(BASE, headers=VIEW)).json() == {"items": [], "total": 0}
    allowed = {**VIEW, "x-roles": "x"}
    assert (await client.get(f"{BASE}/{cid}", headers=allowed)).status_code == 200


@pytest.mark.unbound_tenant
async def test_multi_tenant_without_tenant_403_tenant_required():
    app, state = await build_app(multi=True)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            for res in (
                await c.get(BASE, headers=EDIT),
                await c.post(BASE, json={"name": "a", "list_type_key": "news"}, headers=EDIT),
                await c.get(LISTS, headers=EDIT),
            ):
                assert res.status_code == 403
                assert res.json()["code"] == "tenant_required"
    finally:
        await state.engine.dispose()


@pytest.mark.unbound_tenant
async def test_multi_tenant_reads_the_resolved_tenant():
    app, state = await build_app(multi=True)
    try:
        await seed_list(state, "a")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            in_a = {**EDIT, "x-tenant": "a"}
            res = await c.post(BASE, json={"name": "a", "list_type_key": "news"}, headers=in_a)
            assert res.status_code == 201, res.text
            cid = res.json()["id"]
            assert (
                await c.get(f"{BASE}/{cid}", headers={**EDIT, "x-tenant": "b"})
            ).status_code == 404
            assert (await c.get(f"{BASE}/{cid}", headers=in_a)).status_code == 200
    finally:
        await state.engine.dispose()


async def test_write_without_csrf_403():
    app, state = await build_app(session=True)
    try:
        await seed_list(state, "default")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            token = (await c.get("/token")).json()["token"]
            body = {"name": "a", "list_type_key": "news"}
            refused = await c.post(BASE, json=body, headers=EDIT)
            assert refused.status_code == 403
            assert "CSRF" in refused.json()["detail"]
            assert (await c.get(BASE, headers=VIEW)).json()["total"] == 0
            ok = await c.post(BASE, json=body, headers={**EDIT, CSRF_HEADER: token})
            assert ok.status_code == 201, ok.text
    finally:
        await state.engine.dispose()


@pytest.mark.parametrize("field", ["subject", "preheader", "from_name", "reply_to"])
async def test_crlf_subject_422(client, field):
    cid = (await _create(client))["id"]
    value = "a@example.com\r\nBcc: victim@example.com"
    res = await client.patch(
        f"{BASE}/{cid}", json={"expected_revision": 1, field: value}, headers=EDIT
    )
    assert res.status_code == 422
    assert "victim" not in res.text
    assert field in res.json()["detail"]
    if field in ("subject", "preheader"):
        res = await client.post(
            BASE, json={"name": "a", "list_type_key": "news", field: value}, headers=EDIT
        )
        assert res.status_code == 422
        assert "victim" not in res.text


async def test_invalid_payloads_422(client):
    cid = (await _create(client))["id"]
    url = f"{BASE}/{cid}"
    for body in (
        {"name": "x"},  # no expected_revision
        {"expected_revision": 1, "name": ""},
        {"expected_revision": 1, "name": None},
        {"expected_revision": 1, "reply_to": "not-an-address"},
        {"expected_revision": 1, "audience": "segment:1"},
        {"expected_revision": 1, "body": "nope"},
        [],
    ):
        res = await client.patch(url, json=body, headers=EDIT)
        assert res.status_code == 422, (body, res.text)
    res = await client.get(BASE, params={"limit": 101}, headers=VIEW)
    assert res.status_code == 422
