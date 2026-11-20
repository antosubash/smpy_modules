"""Every way to start a fetch goes through one decision: the floor since the last attempt, an
unexpired lease never cleared, resume only from a stop, and the rate limits cover every route."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from simple_module_core.rate_limit import RateLimitRegistry
from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.feeds.subscriptions import lease
from sm_events.models import Subscription
from sm_events.module import EventsModule
from sqlalchemy import update

from tests.support.calendars import OWNER
from tests.support.subscriptions_http import SUBS, add, app_client, calendar, row, stub_launch


@pytest.fixture
def launched(monkeypatch):
    return stub_launch(monkeypatch)


@pytest.fixture
async def http():
    async with app_client() as client:
        yield client


async def _set(http, **values):
    async with http.db_state.session_factory() as db:
        await db.execute(update(Subscription).values(**values))
        await db.commit()


async def _made(http):
    cid = await calendar(http)
    return (await add(http, cid, OWNER)).json()["id"]


async def test_fifty_resumes_start_at_most_one_fetch(http, launched):
    sid = await _made(http)
    launched.clear()
    await http.post(f"{SUBS}/{sid}/pause", headers=OWNER)
    await _set(http, updated_at=utcnow() - timedelta(hours=1))
    codes = [
        (await http.post(f"{SUBS}/{sid}/resume", headers=OWNER)).status_code for _ in range(50)
    ]
    assert codes[0] == 200 and set(codes[1:]) == {409}
    assert len(launched) == 1


async def test_a_pause_resume_loop_cannot_start_a_fetch_each_time(http, launched):
    sid = await _made(http)
    launched.clear()
    answers = []
    for _ in range(20):
        await http.post(f"{SUBS}/{sid}/pause", headers=OWNER)
        answers.append((await http.post(f"{SUBS}/{sid}/resume", headers=OWNER)).status_code)
    assert set(answers) == {200}  # a mistaken pause is undone at once ...
    assert launched == []  # ... but it is never fetched before the floor
    sub = await row(http, sid)
    assert sub.status == "pending" and sub.next_fetch_at >= utcnow() + timedelta(seconds=250)


async def test_resume_during_an_unexpired_lease_does_not_clear_it(http, launched):
    sid = await _made(http)
    until = utcnow() + timedelta(minutes=1)
    await _set(http, status="paused", lease_owner="worker", lease_until=until)
    await _set(http, updated_at=utcnow() - timedelta(hours=1))
    got = await http.post(f"{SUBS}/{sid}/resume", headers=OWNER)
    assert got.status_code == 200
    sub = await row(http, sid)
    assert (sub.lease_owner, sub.status) == ("worker", "pending")
    assert sub.next_fetch_at >= until  # due after the in-flight fetch
    async with http.db_state.session_factory() as db:
        assert await lease.claim(db, uuid.UUID(sid), owner="second", now=utcnow()) is False


async def test_a_url_edit_inside_the_floor_is_due_only_after_it(http, launched):
    sid = await _made(http)
    launched.clear()
    await _set(http, last_fetched_at=utcnow() - timedelta(seconds=10), lease_owner="w",
               lease_until=utcnow() + timedelta(minutes=1))  # fmt: skip
    got = await http.patch(
        f"{SUBS}/{sid}", json={"url": "https://other.example.test/a.ics"}, headers=OWNER
    )
    assert got.status_code == 200
    sub = await row(http, sid)
    assert sub.lease_owner == "w"  # an in-flight fetch finishes
    assert sub.next_fetch_at >= utcnow() + timedelta(seconds=250)
    assert launched == []  # nothing is started now; the beat picks it up when due


async def test_a_stopped_subscription_resumes_once(http, launched):
    sid = await _made(http)
    await _set(http, status="disabled", consecutive_failures=10, error_code="timeout",
               updated_at=utcnow() - timedelta(hours=1))  # fmt: skip
    launched.clear()
    first = await http.post(f"{SUBS}/{sid}/resume", headers=OWNER)
    again = await http.post(f"{SUBS}/{sid}/resume", headers=OWNER)
    assert (first.status_code, first.json()["status"]) == (200, "pending")
    assert (again.status_code, again.json()["code"]) == (409, "subscription_not_paused")
    assert len(launched) == 1


def test_the_rate_limit_covers_every_route_that_can_start_a_fetch():
    registry = RateLimitRegistry()
    EventsModule().register_rate_limits(registry)
    one = uuid.uuid4()
    for method, path in (
        ("POST", f"/api/events/calendars/{one}/subscriptions"),
        ("PATCH", f"/api/events/subscriptions/{one}"),
        ("POST", f"/api/events/subscriptions/{one}/refresh"),
        ("POST", f"/api/events/subscriptions/{one}/resume"),
    ):
        rule = registry.match(method, path)
        assert rule is not None, (method, path)
        assert rule.key == "user"
    assert constants.SUBSCRIPTION_REFRESH_RATE
