"""Room for subscriptions: the per-member cap, what capacity reports, and what "refresh now" says
when the fetch is only queued."""

from __future__ import annotations

import pytest
from sm_events.core import constants

from tests.support.calendars import BASE, MANAGER, OWNER, VIEWER
from tests.support.subscriptions_http import SUBS, add, app_client, calendar, stub_launch


@pytest.fixture(autouse=True)
def _no_launch(monkeypatch):
    return stub_launch(monkeypatch)


@pytest.fixture
async def http():
    async with app_client() as client:
        yield client


async def test_one_member_cannot_take_the_whole_tenant_allowance(http, monkeypatch):
    monkeypatch.setattr(constants, "SUBSCRIPTIONS_PER_OWNER", 3)
    cid = await calendar(http)
    for n in range(3):  # at the limit
        made = await add(http, cid, OWNER, url=f"https://o{n}.example.test/x.ics")
        assert made.status_code == 201
    over = await add(http, cid, OWNER, url="https://o3.example.test/x.ics")
    assert (over.status_code, over.json()["code"]) == (409, "subscription_limit")  # past it
    colleague = await add(http, cid, MANAGER, url="https://m0.example.test/x.ics")
    assert colleague.status_code == 201  # another member's own count is separate
    gone = (await add(http, cid, MANAGER, url="https://m1.example.test/x.ics")).json()["id"]
    assert (await http.delete(f"{SUBS}/{gone}", headers=MANAGER)).status_code in (200, 204)


@pytest.mark.parametrize("eager", [False, True])
async def test_refresh_now_says_when_it_is_only_queued(http, monkeypatch, eager):
    from sm_events.feeds.subscriptions import launch

    monkeypatch.setattr(launch, "celery_eager", lambda: eager)
    cid = await calendar(http)
    sid = (await add(http, cid, OWNER)).json()["id"]
    got = (await http.post(f"{SUBS}/{sid}/refresh", headers=OWNER)).json()
    assert got["queued"] is (not eager)  # a message to a worker is queued; an inline run is not
    assert got["queued_minutes"] == (None if eager else constants.SUBSCRIPTION_QUEUED_MINUTES)
    other = (await http.get(f"{BASE}/{cid}/subscriptions", headers=OWNER)).json()[0]
    assert other["queued"] is False  # only the refresh answer carries it


async def test_capacity_says_how_much_room_each_limit_has(http, monkeypatch):
    monkeypatch.setattr(constants, "SUBSCRIPTIONS_PER_OWNER", 3)
    monkeypatch.setattr(constants, "SUBSCRIPTIONS_PER_CALENDAR", 2)
    cid = await calendar(http)
    other = await calendar(http)
    for n in range(2):
        assert (
            await add(http, cid, OWNER, url=f"https://c{n}.example.test/x.ics")
        ).status_code == 201
    got = await http.get(f"{BASE}/{cid}/subscriptions/capacity", headers=OWNER)
    assert got.status_code == 200
    assert got.json() == {
        "calendar": {"used": 2, "limit": 2},
        "owner": {"used": 2, "limit": 3},
        "tenant": {"used": 2, "limit": constants.SUBSCRIPTIONS_PER_TENANT},
    }
    # another calendar: its own count, the same member's and tenant's totals
    assert (await http.get(f"{BASE}/{other}/subscriptions/capacity", headers=OWNER)).json()[
        "calendar"
    ] == {"used": 0, "limit": 2}
    # what the capacity says is what create does
    over = await add(http, cid, OWNER, url="https://c9.example.test/x.ics")
    assert over.status_code == 409
    assert (
        await http.get(f"{BASE}/{cid}/subscriptions/capacity", headers=VIEWER)
    ).status_code == 404
