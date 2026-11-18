"""The runner's edges: duplicate pairs, and a timeout inside a query on a shared connection."""

from __future__ import annotations

from sm_events.models import Calendar

from tests.calendar.test_plugin_runner import (
    Call,
    FakeSource,
    calendars,
    entry,
    item,
    ok,
    one,
    run,
    status,
)


async def test_the_same_pair_twice_gives_each_item_once(db):
    """Two calls for one source on one calendar (it was listed twice): no item is doubled."""
    cal = (await calendars(db))["I"]
    src = FakeSource(behave=ok(item("same")))
    result = await run(db, [Call(cal, entry(), src), Call(cal, entry(), src)])
    assert len(result.items) == 1 and len(result.statuses) == 2


async def test_a_timeout_inside_a_query_never_leaves_an_unusable_session(db, monkeypatch):
    """The shared-connection fallback: a statement cancelled by the timeout either leaves the
    session usable, or is reported as a broken session so the caller stops using it."""
    from sm_events.core import constants
    from sqlalchemy import select as sa_select
    from sqlalchemy import text

    monkeypatch.setattr(constants, "SOURCE_TIMEOUT_SECONDS", 0.3)
    monkeypatch.setattr(constants, "SOURCE_MIN_SLICE_SECONDS", 0.01)

    async def slow(ctx, start, end):
        await ctx.db.execute(
            text(
                "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 6000000) "
                "SELECT count(*) FROM n"
            )
        )
        return []

    result = await one(db, FakeSource(behave=slow))
    assert status(result) in (("timeout", None), ("failed", "session"))
    if status(result) == ("timeout", None):
        assert (await db.execute(sa_select(Calendar))).scalars().all()  # still usable
