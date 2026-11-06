"""``/suppressions``: the listing, the lookup and the audited lift over HTTP."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sm_newsletter.core import constants
from sm_newsletter.core.suppression import email_hash

from tests.support.app import build_app
from tests.support.lift_world import seed_row

API = constants.ROUTE_PREFIX_API
BASE = f"{API}/suppressions"
MANAGE = {"x-perms": f"{constants.PERM_VIEW},{constants.PERM_MANAGE}"}
VIEW = {"x-perms": constants.PERM_VIEW}
ADA, BOB = "ada@example.org", "bob@example.org"
NOW = datetime.now(UTC)


@pytest_asyncio.fixture
async def built():
    app, state = await build_app()
    await seed_row(state, "default", ADA, "hard_bounce", at=NOW - timedelta(days=2))
    await seed_row(state, "default", BOB, "complaint", at=NOW - timedelta(days=1))
    yield app, state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def client(built):
    app, _ = built
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _ada(client) -> dict:
    page = (await client.get(BASE, headers=MANAGE)).json()
    return next(i for i in page["items"] if i["fingerprint"] == email_hash(ADA)[:12])


async def test_listing_shape(client):
    res = await client.get(BASE, headers=MANAGE)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 2
    assert body["counts"] == {
        "hard_bounce": 1,
        "complaint": 1,
        "imported_cleaned": 0,
        "unsubscribed": 0,
    }
    first, second = body["items"]
    assert (first["reason"], first["liftable"]) == ("complaint", False)
    assert (second["reason"], second["liftable"]) == ("hard_bounce", True)
    assert second["fingerprint"] == email_hash(ADA)[:12]
    assert "email_hash" not in second and ADA not in res.text
    only = (await client.get(f"{BASE}?reason=complaint&limit=1", headers=MANAGE)).json()
    assert [i["reason"] for i in only["items"]] == ["complaint"] and only["total"] == 1


async def test_permissions(client):
    item = await _ada(client)
    body = {"version": item["version"], "email": ADA, "note": "n"}
    assert (await client.get(BASE, headers=VIEW)).status_code == 403
    assert (
        await client.post(f"{BASE}/lookup", json={"email": ADA}, headers=VIEW)
    ).status_code == 403
    assert (
        await client.post(f"{BASE}/{item['id']}/lift", json=body, headers=VIEW)
    ).status_code == 403
    assert (await client.get(f"{BASE}/lifts", headers=VIEW)).status_code == 403


async def test_lookup_is_a_post_and_never_echoes_the_address(client):
    assert (await client.get(f"{BASE}/lookup", headers=MANAGE)).status_code in (404, 405, 422)
    res = await client.post(f"{BASE}/lookup", json={"email": " ADA@example.org"}, headers=MANAGE)
    assert res.status_code == 200, res.text
    assert [i["reason"] for i in res.json()] == ["hard_bounce"]
    assert "ada@" not in res.text.lower()
    bad = await client.post(f"{BASE}/lookup", json={"email": 5}, headers=MANAGE)
    assert bad.status_code == 422


async def test_lift_round_trip_and_lifts_page(client):
    item = await _ada(client)
    body = {"version": item["version"], "email": ADA, "note": "fixed mailbox"}
    res = await client.post(f"{BASE}/{item['id']}/lift", json=body, headers=MANAGE)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["fingerprint"] == email_hash(ADA)[:12]
    assert (out["reason"], out["note"], out["lifted_by"]) == ("hard_bounce", "fixed mailbox", "u")
    assert ADA not in res.text
    assert (await client.get(BASE, headers=MANAGE)).json()["total"] == 1
    page = (await client.get(f"{BASE}/lifts?limit=10", headers=MANAGE)).json()
    assert page["total"] == 1 and page["items"][0]["id"] == out["id"]


async def test_lift_errors(client):
    item = await _ada(client)
    url = f"{BASE}/{item['id']}/lift"
    wrong = await client.post(
        url, json={"version": item["version"], "email": BOB, "note": "n"}, headers=MANAGE
    )
    assert (wrong.status_code, wrong.json()["code"]) == (422, "lift_email_mismatch")
    assert BOB not in wrong.text
    missing = await client.post(
        f"{BASE}/999999/lift",
        json={"version": item["version"], "email": ADA, "note": "n"},
        headers=MANAGE,
    )
    assert missing.status_code == 404
    blank = await client.post(
        url, json={"version": item["version"], "email": ADA, "note": " "}, headers=MANAGE
    )
    assert (blank.status_code, blank.json()["code"]) == (422, "invalid_query")


async def test_lift_with_stale_version_is_409(built, client):
    _, state = built
    item = await _ada(client)
    await seed_row(state, "default", ADA, "hard_bounce", at=NOW - timedelta(hours=1))
    res = await client.post(
        f"{BASE}/{item['id']}/lift",
        json={"version": item["version"], "email": ADA, "note": "n"},
        headers=MANAGE,
    )
    assert (res.status_code, res.json()["code"]) == (409, "suppression_changed")
    assert (await _ada(client))["id"] == item["id"]


async def test_bogus_reason_is_invalid_query(client):
    res = await client.get(f"{BASE}?reason=bogus", headers=MANAGE)
    assert (res.status_code, res.json()["code"]) == (422, "invalid_query")
    assert "bogus" not in res.text
    assert (await client.get(f"{BASE}?limit=101", headers=MANAGE)).status_code == 422
