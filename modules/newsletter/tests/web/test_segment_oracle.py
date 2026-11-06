"""A segment on a list the caller cannot read answers exactly like one that does
not exist, on every surface that resolves a segment (Codex P2): audience count,
subscriber search and a campaign PATCH. ``segment_list_mismatch`` is kept for a
segment whose list the caller can read."""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sm_newsletter.core import constants

from tests.support.app import build_app
from tests.support.records_seed import TAGS, restrict_list, seed_list

API = constants.ROUTE_PREFIX_API
PERMS = [constants.PERM_VIEW, constants.PERM_EDIT, constants.PERM_RECORDS_VIEW]
CALLER = {"x-perms": ",".join(PERMS)}
EDITOR = {**CALLER, "x-roles": "editor"}
RULES = [{"field": "tags", "op": "any", "value": ["vip"]}]


@pytest_asyncio.fixture
async def built():
    app, state = await build_app()
    await seed_list(state, "default", fields=[TAGS])
    await seed_list(state, "default", key="secret", fields=[TAGS])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        seg = {"name": "Hidden", "list_type_key": "secret", "rules": RULES}
        res = await client.post(f"{API}/segments", json=seg, headers=CALLER)
        assert res.status_code == 201, res.text
        await restrict_list(state, "default", "secret", ["editor"])
        yield client, res.json()["id"]
    await state.engine.dispose()


async def _count(client, sid, headers=CALLER):
    url = f"{API}/lists/news/audience-count"
    return await client.get(url, params={"audience": f"segment:{sid}"}, headers=headers)


async def _search(client, sid, headers=CALLER):
    url = f"{API}/lists/news/subscribers/search"
    return await client.post(url, json={"segment": sid}, headers=headers)


async def _patch(client, sid, headers=CALLER):
    created = await client.post(
        f"{API}/campaigns", json={"name": "c", "list_type_key": "news"}, headers=headers
    )
    assert created.status_code == 201, created.text
    url = f"{API}/campaigns/{created.json()['id']}"
    body = {"expected_revision": 1, "audience": f"segment:{sid}"}
    return await client.patch(url, json=body, headers=headers)


def _answer(res):
    return res.status_code, res.json()


async def test_unreadable_segment_answers_like_a_missing_one(built):
    client, sid = built
    missing = sid + 1000
    for call in (_count, _search, _patch):
        hidden, absent = await call(client, sid), await call(client, missing)
        assert _answer(hidden) == _answer(absent), call.__name__
        assert _answer(hidden)[1]["code"] == "unknown_segment", call.__name__


async def test_readable_segment_on_another_list_is_a_mismatch(built):
    client, sid = built
    for call in (_count, _search, _patch):
        res = await call(client, sid, headers=EDITOR)
        assert (res.status_code, res.json()["code"]) == (422, "segment_list_mismatch")
