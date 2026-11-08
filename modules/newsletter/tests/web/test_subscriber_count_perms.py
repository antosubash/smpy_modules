"""A count over subscriber fields needs ``records.view``: a rule can name
``sm_email``, so a prefix count would list addresses to anyone with
``newsletter.view``. The whole-list count stays ``newsletter.view``, and the
send estimate leaves the tag/segment count out instead of refusing."""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sm_newsletter.core import constants

from tests.support.app import build_app
from tests.support.records_seed import TAGS, seed_list, seed_subscriber
from tests.support.sending import SENDER

API = constants.ROUTE_PREFIX_API
VIEW = {"x-perms": constants.PERM_VIEW}
READER = {"x-perms": f"{constants.PERM_VIEW},{constants.PERM_RECORDS_VIEW}"}
AUTHOR = {"x-perms": f"{constants.PERM_VIEW},{constants.PERM_EDIT},{constants.PERM_SEND}"}
FULL = {"x-perms": f"{AUTHOR['x-perms']},{constants.PERM_RECORDS_VIEW}"}
TAG_RULE = {"field": "tags", "op": "any", "value": ["vip"]}


@pytest_asyncio.fixture
async def client():
    app, state = await build_app(settings=SENDER)
    await seed_list(state, "default", fields=[TAGS])
    await seed_subscriber(state, "default", "a@example.org", "confirmed", data={"tags": ["vip"]})
    await seed_subscriber(state, "default", "b@example.org", "confirmed", data={"tags": []})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    await state.engine.dispose()


def _count(client, audience, headers):
    url = f"{API}/lists/news/audience-count"
    return client.get(url, params={"audience": audience}, headers=headers)


async def _segment(client) -> int:
    body = {"name": "A", "list_type_key": "news", "rules": [TAG_RULE]}
    res = await client.post(f"{API}/segments", json=body, headers=FULL)
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def test_segment_preview_needs_records_view(client):
    body = {"list_type_key": "news", "rules": [TAG_RULE]}
    res = await client.post(f"{API}/segments/preview", json=body, headers=VIEW)
    assert res.status_code == 403
    res = await client.post(f"{API}/segments/preview", json=body, headers=READER)
    assert (res.status_code, res.json()) == (200, {"count": 1})


async def test_tag_and_segment_counts_need_records_view(client):
    sid = await _segment(client)
    for audience in ("tag:vip", f"segment:{sid}"):
        assert (await _count(client, audience, VIEW)).status_code == 403, audience
        res = await _count(client, audience, READER)
        assert (res.status_code, res.json()) == (200, {"count": 1}), audience


async def test_whole_list_count_needs_only_newsletter_view(client):
    res = await _count(client, "all", VIEW)
    assert (res.status_code, res.json()) == (200, {"count": 2})


async def _campaign(client, audience: str) -> int:
    created = await client.post(
        f"{API}/campaigns", json={"name": "c", "list_type_key": "news"}, headers=FULL
    )
    assert created.status_code == 201, created.text
    cid = created.json()["id"]
    body = {"expected_revision": 1, "audience": audience}
    res = await client.patch(f"{API}/campaigns/{cid}", json=body, headers=FULL)
    assert res.status_code == 200, res.text
    return cid


async def test_estimate_hides_a_tag_count_without_records_view(client):
    cid = await _campaign(client, "tag:vip")
    hidden = await client.get(f"{API}/campaigns/{cid}/estimate", headers=AUTHOR)
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["recipients"] is None
    assert hidden.json()["estimated_finish"]
    shown = await client.get(f"{API}/campaigns/{cid}/estimate", headers=FULL)
    assert shown.json()["recipients"] == 1


async def test_estimate_of_the_whole_list_keeps_its_count(client):
    cid = await _campaign(client, "all")
    res = await client.get(f"{API}/campaigns/{cid}/estimate", headers=AUTHOR)
    assert res.json()["recipients"] == 2
