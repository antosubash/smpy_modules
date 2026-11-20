"""The whole path over a real loopback TLS socket: fetch, scan, store, the occurrences read, a
refresh that replaces the items, a broken feed that keeps them, and removal. The throwaway CA is
injected through the transport's trust seam; the guard is widened to loopback inside these tests
only, and production verification is untouched."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.subscriptions import fetch, refresh, service
from sm_events.models import ExternalItem, Subscription
from sqlalchemy import select, update

from tests.support.access import principal
from tests.support.occurrences import read
from tests.support.subscriptions import ics, seed_calendar, seed_subscription, vevent

pytestmark = pytest.mark.unbound_tenant
NOW = datetime(2026, 11, 19, 12, tzinfo=UTC)
OWNER = principal("o", "events.view", "events.edit")
SETTINGS = EventsSettings(
    allow_private_subscription_urls=True
)  # loopback stays widened by the test


def _feed(*titles: str) -> bytes:
    return ics(
        *(
            vevent(UID=f"{t}@x", SUMMARY=t, DTSTART="20261201T100000Z", DTEND="20261201T110000Z")
            for t in titles
        )
    )


async def _refresh(db_state, sid):
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            await db.execute(
                update(Subscription).values(
                    next_fetch_at=NOW, last_fetched_at=None, lease_until=None
                )
            )
            await db.commit()
    return await refresh.refresh_one_async(
        db_state.session_factory, tenant_id="default", subscription_id=sid, now=NOW,
        settings=SETTINGS, fetcher=fetch.fetch_feed, utc_now=lambda: NOW,
    )  # fmt: skip


async def _state(db_state, sid):
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            sub = (
                await db.execute(select(Subscription).where(Subscription.id == sid))
            ).scalar_one()
            titles = sorted((await db.execute(select(ExternalItem.title))).scalars())
            return sub.status, sub.error_code, titles


async def test_fetch_replace_break_and_remove(tls_server, db_state):
    port, seen = tls_server
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            cal = await seed_calendar(db)
            sub = await seed_subscription(
                db, cal, url=f"https://cal.example:{port}/private/SECRET-TOKEN-123/basic.ics",
                may_use_private=True,
            )  # fmt: skip
            sid = sub.id
            await db.commit()

    seen["body"] = _feed("Alpha", "Beta")
    assert await _refresh(db_state, sid) == "stored"
    assert await _state(db_state, sid) == ("ok", None, ["Alpha", "Beta"])
    assert seen["requests"][-1].startswith("GET /private/SECRET-TOKEN-123/basic.ics")
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            page = await read(
                db, OWNER, datetime(2026, 12, 1, tzinfo=UTC), datetime(2026, 12, 2, tzinfo=UTC)
            )
    assert sorted(i.title for i in page.items if i.source == "subscriptions") == ["Alpha", "Beta"]

    seen["body"] = _feed("Beta", "Gamma")  # an edited feed replaces the items
    assert await _refresh(db_state, sid) == "stored"
    assert await _state(db_state, sid) == ("ok", None, ["Beta", "Gamma"])

    seen["body"], seen["type"] = b"<html>sign in</html>", b"text/html"  # a broken answer
    assert await _refresh(db_state, sid) == "failed"
    assert await _state(db_state, sid) == ("error", "not_a_calendar", ["Beta", "Gamma"])
    seen["body"], seen["type"] = b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\x00\r\n", b"text/calendar"
    assert await _refresh(db_state, sid) == "failed"
    status, code, titles = await _state(db_state, sid)
    assert (status, code, titles) == (
        "error",
        "not_a_calendar",
        ["Beta", "Gamma"],
    )  # previous items kept

    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            await service.delete(db, OWNER, sid, now=NOW + timedelta(days=1))
            await db.commit()
            assert (await db.execute(select(ExternalItem))).scalars().all() == []
            page = await read(
                db, OWNER, datetime(2026, 12, 1, tzinfo=UTC), datetime(2026, 12, 2, tzinfo=UTC)
            )
    assert [i for i in page.items if i.source == "subscriptions"] == []
