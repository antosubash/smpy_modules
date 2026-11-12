"""``POST /campaigns/{id}/test-send`` over HTTP."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sm_newsletter.core import constants
from sm_newsletter.sending.transport import console

from tests.support.app import build_app
from tests.support.records_seed import restrict_list, seed_list

API = constants.ROUTE_PREFIX_API
EDIT = {"x-perms": f"{constants.PERM_VIEW},{constants.PERM_EDIT}"}
SEND = {"x-perms": f"{constants.PERM_VIEW},{constants.PERM_SEND}"}
# The addresses these tests send to are vouched for by the allow-list; the
# recipient rule itself is test_test_send_recipients'.
VOUCHED = ["a@example.org", "b@example.org", *(f"{c}@x.org" for c in "abcde")]
SENDER = {
    "transport": "console",
    "from_address": "news@example.org",
    "physical_address": "1 Main Street",
    "test_send_extra_recipients": VOUCHED,
}


@pytest_asyncio.fixture
async def built():
    app, state = await build_app(settings=SENDER)
    app.state.sm.settings.public_base_url = "https://news.example.org"
    await seed_list(state, "default")
    yield app, state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def client(built):
    app, _ = built
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest_asyncio.fixture
async def cid(client) -> int:
    res = await client.post(
        f"{API}/campaigns",
        json={"name": "n", "list_type_key": "news", "subject": "Hi"},
        headers=EDIT,
    )
    return res.json()["id"]


def _url(cid: int) -> str:
    return f"{API}/campaigns/{cid}/test-send"


async def test_sends_and_answers_per_recipient(client, cid):
    res = await client.post(_url(cid), json={"recipients": ["a@example.org"]}, headers=SEND)
    assert res.status_code == 200, res.text
    assert res.json() == {
        "results": [
            {
                "recipient": "a@example.org",
                "outcome": "accepted",
                "code": "smtp_250",
            }
        ]
    }
    assert [m.subject for m in console.captured("default")] == ["[TEST] Hi"]


async def test_six_addresses_422(client, cid):
    six = [f"u{i}@example.org" for i in range(6)]
    res = await client.post(_url(cid), json={"recipients": six}, headers=SEND)
    assert (res.status_code, res.json()["code"]) == (422, "invalid_campaign")
    empty = await client.post(_url(cid), json={"recipients": []}, headers=SEND)
    assert empty.status_code == 422
    assert console.captured("default") == []


async def test_dedup_and_lowercase(client, cid):
    # Six raw entries, five distinct after normalising: within the cap.
    raw = [" A@x.org", "a@X.org", "b@x.org", "c@x.org", "d@x.org", "e@x.org"]
    res = await client.post(_url(cid), json={"recipients": raw}, headers=SEND)
    assert res.status_code == 200, res.text
    got = [r["recipient"] for r in res.json()["results"]]
    assert got == ["a@x.org", "b@x.org", "c@x.org", "d@x.org", "e@x.org"]
    one = await client.post(_url(cid), json={"recipients": [" A@x.org", "a@X.org"]}, headers=SEND)
    assert [r["recipient"] for r in one.json()["results"]] == ["a@x.org"]


@pytest.mark.parametrize(
    "bad", ["a@example.org\r\nBcc: victim@example.org", "a@example.org\nX", "not-an-address"]
)
async def test_crlf_address_422(client, cid, bad):
    res = await client.post(_url(cid), json={"recipients": [bad]}, headers=SEND)
    assert (res.status_code, res.json()["code"]) == (422, "invalid_campaign")
    assert "victim" not in res.text and bad not in res.text
    assert console.captured("default") == []


async def test_edit_without_send_403(client, cid):
    res = await client.post(_url(cid), json={"recipients": ["a@example.org"]}, headers=EDIT)
    assert res.status_code == 403
    assert console.captured("default") == []


async def test_restricted_list_test_send_is_404(client, built, cid):
    _, state = built
    await restrict_list(state, "default", "news", ["x"])
    body = {"recipients": ["a@example.org"]}
    assert (await client.post(_url(cid), json=body, headers=SEND)).status_code == 404
    allowed = {**SEND, "x-roles": "x"}
    assert (await client.post(_url(cid), json=body, headers=allowed)).status_code == 200


async def test_budget_exhausted_is_429(built, client, cid):
    app, _ = built
    app.state.sm_newsletter.settings.daily_limit = 1
    body = {"recipients": ["a@example.org", "b@example.org"]}
    res = await client.post(_url(cid), json=body, headers=SEND)
    assert (res.status_code, res.json()["code"]) == (429, "send_budget_exhausted")


async def test_only_vouched_recipients_are_sent(client, cid):
    # The caller's own address (the auth stub's user) and the allow-list pass;
    # anyone else is refused for that address alone (#348).
    body = {"recipients": ["U@example.com", "stranger@example.net", "a@example.org"]}
    res = await client.post(_url(cid), json=body, headers=SEND)
    assert res.status_code == 200, res.text
    assert res.json()["results"] == [
        {"recipient": "u@example.com", "outcome": "accepted", "code": "smtp_250"},
        {"recipient": "stranger@example.net", "outcome": "recipient_not_allowed", "code": None},
        {"recipient": "a@example.org", "outcome": "accepted", "code": "smtp_250"},
    ]
    assert sorted(m.to for m in console.captured("default")) == ["a@example.org", "u@example.com"]
