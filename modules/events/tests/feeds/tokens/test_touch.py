"""``last_used_at``: coarse, harmless, and never in the way of the feed."""

from __future__ import annotations

from datetime import timedelta

from sm_events.feeds.tokens.resolve import lookup, touch_last_used

from tests.feeds.tokens.resolve_support import last_used
from tests.support.tokens import NOW


async def test_touch_coarse(world):
    _app, state, _cals, created, _ = world
    async with state.session_factory() as db:
        row = await lookup(db, created.secret)
    assert row is not None
    first = NOW
    await touch_last_used(state.session_factory, row, now=first)
    assert await last_used(state, row.id) == first
    await touch_last_used(state.session_factory, row, now=first + timedelta(minutes=59))
    assert await last_used(state, row.id) == first  # within the hour: no write
    later = first + timedelta(hours=1, minutes=1)
    await touch_last_used(state.session_factory, row, now=later)
    assert await last_used(state, row.id) == later


async def test_touch_swallows_and_logs_the_class(world, caplog):
    _app, state, _cals, created, _ = world
    async with state.session_factory() as db:
        row = await lookup(db, created.secret)

    def broken():
        raise ConnectionError(f"down: {created.secret}")

    with caplog.at_level("DEBUG"):
        await touch_last_used(broken, row, now=NOW)  # must not raise
    assert "ConnectionError" in caplog.text
    assert created.secret not in caplog.text
