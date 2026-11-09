"""Tag and unsubscribe over HTTP: permissions, CSRF, the answer (PR 6, Task 9; G10)."""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from simple_module_hosting.csrf import CSRF_HEADER
from sm_newsletter.core import constants

from tests.support.app import build_app
from tests.support.records_seed import TAGS, seed_list, seed_subscriber

API = constants.ROUTE_PREFIX_API
ADA = "ada@example.org"
RV = constants.PERM_RECORDS_VIEW


def _h(*perms: str) -> dict[str, str]:
    return {"x-perms": ",".join(perms)}


@pytest_asyncio.fixture
async def built():
    app, state = await build_app(session=True)
    await seed_list(state, "default", fields=[TAGS])
    uuid = await seed_subscriber(state, "default", ADA, "confirmed", data={"tags": ["vip"]})
    yield app, state, uuid
    await state.engine.dispose()


@pytest_asyncio.fixture
async def client(built):
    async with AsyncClient(transport=ASGITransport(app=built[0]), base_url="http://t") as c:
        token = (await c.get("/token")).json()["token"]
        c.headers[CSRF_HEADER] = token
        yield c


def _tags(uuid):
    return f"{API}/lists/news/subscribers/{uuid}/tags"


def _unsub(uuid):
    return f"{API}/lists/news/subscribers/{uuid}/unsubscribe"


async def test_tags_permissions(built, client):
    uuid = built[2]
    body = {"add": ["events"], "remove": []}
    view = _h(constants.PERM_VIEW, RV)
    edit_only = _h(constants.PERM_EDIT)
    assert (await client.post(_tags(uuid), json=body, headers=view)).status_code == 403
    assert (await client.post(_tags(uuid), json=body, headers=edit_only)).status_code == 403
    res = await client.post(_tags(uuid), json=body, headers=_h(constants.PERM_EDIT, RV))
    assert res.status_code == 200, res.text
    assert res.json()["tags"] == ["vip", "events"] and res.json()["suppressed"] is False


async def test_unsubscribe_permissions(built, client):
    uuid = built[2]
    assert (
        await client.post(_unsub(uuid), json={}, headers=_h(constants.PERM_EDIT, RV))
    ).status_code == 403
    assert (
        await client.post(_unsub(uuid), json={}, headers=_h(constants.PERM_MANAGE))
    ).status_code == 403
    res = await client.post(_unsub(uuid), json={}, headers=_h(constants.PERM_MANAGE, RV))
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "unsubscribed" and res.json()["suppressed"] is True
    again = await client.post(_unsub(uuid), json={}, headers=_h(constants.PERM_MANAGE, RV))
    assert (again.status_code, again.json()["code"]) == (409, "not_subscribed")


async def test_bodies_and_errors_never_echo(built, client):
    uuid = built[2]
    head = _h(constants.PERM_EDIT, RV)
    for body in (
        {"add": ["SECRET"], "remove": []},
        {"add": [], "remove": [], "x": "SECRET"},
        {"add": "SECRET"},
    ):
        res = await client.post(_tags(uuid), json=body, headers=head)
        assert res.status_code == 422 and "SECRET" not in res.text, body
    for bad in ("nope", "A" * 32):
        assert (await client.post(_tags(bad), json={}, headers=head)).status_code == 404


async def test_csrf_required(built):
    app, _, uuid = built
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        for url, perms in (
            (_tags(uuid), _h(constants.PERM_EDIT, RV)),
            (_unsub(uuid), _h(constants.PERM_MANAGE, RV)),
        ):
            res = await c.post(url, json={}, headers=perms)
            assert res.status_code == 403 and "CSRF" in res.json()["detail"], url
