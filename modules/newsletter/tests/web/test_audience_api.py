"""``GET /lists/{key}/audience-count`` over HTTP."""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sm_newsletter.core import constants

from tests.support.app import build_app
from tests.support.records_seed import TAGS, restrict_list, seed_list, seed_subscriber

API = constants.ROUTE_PREFIX_API
VIEW = {"x-perms": constants.PERM_VIEW}


@pytest_asyncio.fixture
async def built():
    app, state = await build_app()
    await seed_list(state, "default", fields=[TAGS])
    await seed_subscriber(state, "default", "a@example.org", "confirmed", data={"tags": ["vip"]})
    await seed_subscriber(state, "default", "b@example.org", "confirmed", data={"tags": []})
    await seed_subscriber(state, "default", "c@example.org", "pending", data={"tags": ["vip"]})
    yield app, state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def client(built):
    app, _ = built
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _count(client, audience, key="news", headers=VIEW):
    url = f"{API}/lists/{key}/audience-count"
    return client.get(url, params={"audience": audience}, headers=headers)


async def test_counts_all_and_tag(client):
    res = await _count(client, "all")
    assert (res.status_code, res.json()) == (200, {"count": 2})
    res = await _count(client, "tag:vip")
    assert (res.status_code, res.json()) == (200, {"count": 1})
    res = await _count(client, "tag:nope")
    assert (res.status_code, res.json()["code"]) == (422, "unknown_tag")


async def test_unreadable_list_404(built, client):
    _, state = built
    assert (await _count(client, "all", key="nope")).status_code == 404
    await restrict_list(state, "default", "news", ["editor"])
    assert (await _count(client, "all")).status_code == 404
    ok = await _count(client, "all", headers={**VIEW, "x-roles": "editor"})
    assert ok.status_code == 200


async def test_long_audience_422_does_not_echo(client):
    audience = "tag:" + "SECRET" * 30
    res = await _count(client, audience)
    assert (res.status_code, res.json()["code"]) == (422, "invalid_audience")
    assert "SECRET" not in res.text
