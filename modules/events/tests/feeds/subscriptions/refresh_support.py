"""Support for the beat's tests: seeding in committed sessions, a scripted fetcher, readers."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sm_events.core import constants
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.subscriptions import refresh
from sm_events.feeds.subscriptions.errors import FetchFailure
from sm_events.feeds.subscriptions.fetch import FetchResult
from sm_events.models import ExternalItem, Subscription
from sqlalchemy import select

from tests.support.subscriptions import ics, seed_calendar, seed_subscription, vevent

NOW = datetime(2026, 11, 19, 12, tzinfo=UTC)
FEED = ics(vevent(UID="a@x", SUMMARY="Alpha"), vevent(UID="b@x", SUMMARY="Beta"))


def ok(body: bytes = FEED, **kw: Any) -> FetchResult:
    return FetchResult(
        "ok", body, kw.get("etag", '"v1"'), kw.get("last_modified"), 200, kw.get("max_age")
    )


def not_modified() -> FetchResult:
    return FetchResult("not_modified", b"", None, None, 304)


class Fetcher:
    """Stands in for ``fetch_feed``: ``script`` is a result, an exception, or a callable of the
    url; every call is recorded."""

    def __init__(self, script: Any = None) -> None:
        self.script = script if script is not None else ok()
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, url: str, **kw: Any) -> FetchResult:
        self.calls.append({"url": url, **kw})
        item = self.script(url) if callable(self.script) else self.script
        if isinstance(item, BaseException):
            raise item
        return item


async def seed(db_state, *, tenant: str = "default", count: int = 1, slug: str = "team", **fields):
    """``count`` due subscriptions on one calendar of ``tenant``, committed; their ids."""
    with tenant_scope(tenant):
        async with db_state.session_factory() as db:
            cal = await seed_calendar(db, slug)
            ids = []
            for n in range(count):
                label = fields.get("label", f"feed{n}")
                sub = await seed_subscription(
                    db,
                    cal,
                    **{
                        "url": f"https://{tenant}-{slug}-{n}.example/feed.ics",
                        "next_fetch_at": NOW - timedelta(minutes=1),
                        **fields,
                        "label": label,
                    },
                )
                ids.append(sub.id)
            await db.commit()
    return ids


async def load(db_state, sid: uuid.UUID, tenant: str = "default") -> Subscription:
    with tenant_scope(tenant):
        async with db_state.session_factory() as db:
            sub = (
                await db.execute(select(Subscription).where(Subscription.id == sid))
            ).scalar_one()
            db.expunge(sub)
            return sub


async def titles(db_state, sid: uuid.UUID, tenant: str = "default") -> list[str]:
    with tenant_scope(tenant):
        async with db_state.session_factory() as db:
            stmt = select(ExternalItem.title).where(ExternalItem.subscription_id == sid)
            return sorted((await db.execute(stmt.order_by(ExternalItem.title))).scalars())


async def tick(db_state, fetcher: Fetcher, **kw: Any) -> dict[str, int]:
    kw.setdefault("now", NOW)
    kw.setdefault("settings", EventsSettings())
    kw.setdefault("rng", random.Random(1))
    kw.setdefault("utc_now", lambda: kw["now"])
    return await refresh.refresh_async(db_state.session_factory, fetcher=fetcher, **kw)


def failure(code: str, **kw: Any) -> FetchFailure:
    return FetchFailure(code, **kw)


def in_minutes(minutes: float) -> timedelta:
    return timedelta(minutes=minutes)


MIN = constants.SUBSCRIPTION_MIN_REFRESH_MINUTES
