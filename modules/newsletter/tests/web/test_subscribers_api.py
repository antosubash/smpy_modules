"""``/lists/{key}/subscribers`` over HTTP (PR 6, Task 8; C5, G15)."""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sm_newsletter.core import constants
from starlette.middleware.base import BaseHTTPMiddleware

from tests.support.app import build_app
from tests.support.lift_world import rows, seed_row
from tests.support.records_seed import TAGS, restrict_list, seed_list, seed_subscriber

API = constants.ROUTE_PREFIX_API
SEARCH = f"{API}/lists/news/subscribers/search"
VIEW = {"x-perms": f"{constants.PERM_VIEW},{constants.PERM_RECORDS_VIEW}"}
ADA, BOB = "ada@example.org", "bob@example.org"
SEEN: list[str] = []


class _Record(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        SEEN.append(str(request.url))
        return await call_next(request)


@pytest_asyncio.fixture
async def built():
    SEEN.clear()
    app, state = await build_app()
    app.add_middleware(_Record)
    await seed_list(state, "default", fields=[TAGS])
    ada = await seed_subscriber(state, "default", ADA, "confirmed", data={"tags": ["vip"]})
    await seed_subscriber(state, "default", BOB, "pending")
    yield app, state, ada
    await state.engine.dispose()


@pytest_asyncio.fixture
async def client(built):
    app = built[0]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_needs_records_view(client):
    only = {"x-perms": constants.PERM_VIEW}
    assert (await client.post(SEARCH, json={}, headers=only)).status_code == 403
    assert (await client.post(SEARCH, json={}, headers=VIEW)).status_code == 200


async def test_list_round_trip(built, client):
    ada = built[2]
    res = await client.post(SEARCH, json={"status": "confirmed"}, headers=VIEW)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1 and body["counts"]["pending"] == 1
    assert body["items"][0] | {} == {
        "uuid": ada,
        "email": ADA,
        "status": "confirmed",
        "first_name": None,
        "last_name": None,
        "tags": ["vip"],
        "confirmed_at": body["items"][0]["confirmed_at"],
        "trashed": False,
        "suppressed": False,
    }
    assert body["records_url"].endswith("/news")
    one = await client.get(f"{API}/lists/news/subscribers/{ada}", headers=VIEW)
    assert one.status_code == 200, one.text
    detail = one.json()
    assert detail["subscriber"]["email"] == ADA
    assert detail["engagement"] == {
        "campaigns_sent": 0,
        "last_sent_at": None,
        "last_campaign_name": None,
        "opened_campaigns": 0,
        "clicked_campaigns": 0,
    }
    assert detail["suppressions"] == [] and detail["records_url"].endswith(ada)
    assert "sends" not in detail and "campaign_id" not in one.text


async def test_invalid_query_never_echoes(client):
    for body in (
        {"status": "SECRETSTATUS"},
        {"q": "SECRET" * 40},
        {"q": "SECRET\x00"},  # records refuses a NUL with a ValueError: never a 500
        {"tag": "SECRET" * 40},
        {"segment": 0},
        {"limit": 0},
        {"limit": 101},
        {"offset": 100_001},
        {"nope": "SECRET"},
    ):
        res = await client.post(SEARCH, json=body, headers=VIEW)
        assert (res.status_code, res.json()["code"]) == (422, "invalid_query"), body
        assert "SECRET" not in res.text


async def test_search_is_a_post_body(client):
    res = await client.post(SEARCH, json={"q": "ada@"}, headers=VIEW)
    assert [i["email"] for i in res.json()["items"]] == [ADA]
    posted = list(SEEN)
    got = await client.get(f"{API}/lists/news/subscribers?q=ada@", headers=VIEW)
    assert got.status_code in (404, 405)
    assert posted and not any("ada" in url or "q=" in url for url in posted)


async def test_bad_uuid_404(client):
    for bad in ("nope", "A" * 32, "a" * 31):
        res = await client.get(f"{API}/lists/news/subscribers/{bad}", headers=VIEW)
        assert res.status_code == 404, bad


async def test_unreadable_opt_out_still_marks_suppressed(built, client):
    _, state, ada = built
    await seed_list(state, "default", key="other")
    await seed_row(state, "default", ADA, "unsubscribed", key="other")
    await restrict_list(state, "default", "other", ["editor"])
    res = await client.get(f"{API}/lists/news/subscribers/{ada}", headers=VIEW)
    body = res.json()
    assert res.status_code == 200, res.text
    assert body["subscriber"]["suppressed"] is True and body["suppressions"] == []


async def test_unreadable_list_discloses_only_a_boolean(built, client):
    """TL1: the tenant-wide flag is the whole disclosure; nothing about list A's rows."""
    _, state, ada = built
    await seed_list(state, "default", key="secretlist")
    await seed_row(
        state, "default", ADA, "unsubscribed", key="secretlist", source="unsubscribe_page"
    )
    await restrict_list(state, "default", "secretlist", ["editor"])
    stored = await rows(state, "default")
    assert len(stored) == 1
    secrets = [
        "secretlist",
        "unsubscribe_page",
        "fingerprint",
        '"reason"',
        '"list_type_key"',
        '"source"',
        '"version"',
    ]
    for r in stored:
        secrets += [r.email_hash[:12], r.created_at.isoformat()]
    for res in (
        await client.get(f"{API}/lists/news/subscribers/{ada}", headers=VIEW),
        await client.post(SEARCH, json={}, headers=VIEW),
    ):
        assert res.status_code == 200, res.text
        for needle in secrets:
            assert needle not in res.text, needle
    detail = (await client.get(f"{API}/lists/news/subscribers/{ada}", headers=VIEW)).json()
    assert detail["subscriber"]["suppressed"] is True and detail["suppressions"] == []
    page = (await client.post(SEARCH, json={}, headers=VIEW)).json()
    by = {i["email"]: i for i in page["items"]}
    assert by[ADA]["suppressed"] is True and by[BOB]["suppressed"] is False
    assert set(by[ADA]) == {
        "uuid",
        "email",
        "status",
        "first_name",
        "last_name",
        "tags",
        "confirmed_at",
        "trashed",
        "suppressed",
    }
