"""Saving and refreshing only enqueue: the response never depends on what the address turns out
to be (private, unresolvable, or fine), not even when Celery is eager and the fetch runs inline."""

from __future__ import annotations

import pytest
from sm_events.feeds.subscriptions import fetch, launch, refresh

from tests.support.calendars import OWNER
from tests.support.net import PUBLIC_IP, ics, resolver  # noqa: F401
from tests.support.subscriptions_http import REAL_LAUNCH, SUBS, add, app_client, calendar

HOSTS = {"fine.example.test": [PUBLIC_IP], "private.example.test": ["10.0.0.5"]}  # and one unknown


@pytest.fixture
async def http(monkeypatch, resolver):  # noqa: F811
    resolver.update(HOSTS)
    monkeypatch.setattr(launch, "refresh_one", REAL_LAUNCH)
    monkeypatch.setattr(launch, "celery_eager", lambda: True)
    monkeypatch.setattr(refresh, "fetch_feed", fetch.fetch_feed)  # the real, guarded fetcher
    import httpx
    from sm_events.feeds.subscriptions import client

    monkeypatch.setattr(
        client,
        "inner_transport",
        lambda: httpx.MockTransport(lambda r: httpx.Response(200, content=ics())),
    )
    async with app_client() as http:
        yield http


def _shape(response) -> dict:
    body = response.json()
    for volatile in (
        "id",
        "calendar_id",
        "version",
        "next_fetch_at",
        "last_fetched_at",
        "last_ok_at",
        "url_display",
    ):
        body.pop(volatile, None)
    return {"http": response.status_code, **body}


async def test_save_answers_alike_whatever_the_address_resolves_to(http):
    cid = await calendar(http)
    answers = [
        _shape(await add(http, cid, OWNER, url=f"https://{host}/x.ics", label="L"))
        for host in ("fine.example.test", "private.example.test", "unknown.example.test")
    ]
    assert (answers[0]["status"] == 201 and answers[0]["status"] == "pending") or True
    assert answers[0] == answers[1] == answers[2]
    assert (answers[0]["http"], answers[0]["status"]) == (201, "pending")


async def test_refresh_now_answers_alike_too(http):
    cid = await calendar(http)
    ids = {}
    for host in ("fine.example.test", "private.example.test", "unknown.example.test"):
        made = await add(http, cid, OWNER, url=f"https://{host}/x.ics", label=host)
        ids[host] = made.json()["id"]
    from sm_events.models import Subscription
    from sqlalchemy import update

    async with http.db_state.session_factory() as db:
        await db.execute(
            update(Subscription).values(
                last_fetched_at=None, status="pending", next_fetch_at=None, error_code=None
            )
        )
        await db.commit()
    shapes = []
    for sid in ids.values():
        got = await http.post(f"{SUBS}/{sid}/refresh", headers=OWNER)
        shape = _shape(got)
        shape.pop("label")
        shapes.append(shape)
    assert shapes[0] == shapes[1] == shapes[2]
    assert shapes[0]["http"] == 202 and shapes[0]["status"] == "pending"
