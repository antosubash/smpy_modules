"""``POST /lists`` over HTTP (R11)."""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sm_newsletter.core import constants

from tests.support.app import build_app
from tests.support.import_http import EDIT, MANAGE
from tests.support.records_seed import seed_list

URL = f"{constants.ROUTE_PREFIX_API}/lists"


@pytest_asyncio.fixture
async def client():
    app, state = await build_app()
    await seed_list(state, "default", "taken")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    await state.engine.dispose()


async def test_create_then_listed(client):
    res = await client.post(URL, json={"key": "weekly", "label": "Weekly"}, headers=MANAGE)
    assert res.status_code == 201, res.text
    assert res.json() == {"key": "weekly"}
    assert "weekly" in (await client.get(URL, headers=MANAGE)).json()


async def test_duplicate_is_409(client):
    res = await client.post(URL, json={"key": "taken", "label": "Again"}, headers=MANAGE)
    assert (res.status_code, res.json()["code"]) == (409, "list_exists")


async def test_bad_keys_are_422(client):
    for body in (
        {"key": "Not A Key!", "label": "x"},
        {"key": "", "label": "x"},
        {"key": "k" * 65, "label": "x"},
        {"key": "ok", "label": ""},
        {"key": "ok"},
    ):
        res = await client.post(URL, json=body, headers=MANAGE)
        assert (res.status_code, res.json()["code"]) == (422, "invalid_list_key"), body


async def test_edit_permission_is_not_enough(client):
    res = await client.post(URL, json={"key": "weekly", "label": "W"}, headers=EDIT)
    assert res.status_code == 403
