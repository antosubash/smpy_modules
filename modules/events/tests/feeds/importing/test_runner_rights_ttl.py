"""The rights captured at apply expire: a worker cannot re-check the importer."""

from __future__ import annotations

from datetime import timedelta

from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.core.tenancy import tenant_scope
from sm_events.models import EventImport
from sqlalchemy import update

from tests.feeds.importing import corpus
from tests.feeds.importing.runner_support import queue, read, run, stage

TTL = constants.IMPORT_GRANTS_TTL


async def _queued(state, n=3, *, until=None):
    _cal, import_id = await stage(state, corpus.simple(n))
    await run(state, import_id)
    await queue(state, import_id, until=until)
    return import_id


async def test_a_slice_just_inside_the_window_writes(events_app):
    _app, state = events_app
    until = utcnow() + TTL
    import_id = await _queued(state, until=until)
    assert await run(state, import_id, now=lambda: until - timedelta(seconds=1)) == "done"
    imp, _items, events = await read(state, import_id)
    assert (imp.status, imp.created, len(events)) == ("done", 3, 3)


async def test_a_slice_just_past_the_window_writes_nothing(events_app):
    _app, state = events_app
    until = utcnow() + TTL
    import_id = await _queued(state, until=until)
    assert await run(state, import_id, now=lambda: until + timedelta(seconds=1)) == "done"
    imp, items, events = await read(state, import_id)
    assert (imp.status, imp.error_code) == ("failed", "rights_expired")
    assert events == [] and all(i.outcome is None for i in items)


async def test_a_queued_import_picked_up_after_the_ttl_writes_nothing(events_app):
    _app, state = events_app
    import_id = await _queued(state)
    later = utcnow() + TTL + timedelta(minutes=1)
    await run(state, import_id, now=lambda: later)
    imp, _items, events = await read(state, import_id)
    assert (imp.status, imp.error_code, events) == ("failed", "rights_expired", [])


async def test_a_later_slice_of_a_long_import_stops_at_the_deadline(events_app, monkeypatch):
    _app, state = events_app
    monkeypatch.setattr(constants, "IMPORT_APPLY_BATCH", 2)
    until = utcnow() + TTL
    import_id = await _queued(state, 5, until=until)
    ticks = iter(range(10**6))

    def spent() -> float:
        return next(ticks) * 1000.0

    before = until - timedelta(seconds=1)
    assert await run(state, import_id, now=lambda: before, clock=spent) == "more"
    await run(state, import_id, now=lambda: until + timedelta(seconds=1), clock=spent)
    imp, items, events = await read(state, import_id)
    assert (imp.status, imp.error_code, len(events)) == ("failed", "rights_expired", 2)
    assert [i.outcome for i in items] == ["created", "created", None, None, None]


async def test_an_import_with_no_deadline_is_expired(events_app):
    _app, state = events_app
    import_id = await _queued(state)
    with tenant_scope("default"):
        async with state.session_factory() as db:
            await db.execute(update(EventImport.__table__).values(rights_until=None))
            await db.commit()
    await run(state, import_id)
    imp, _items, events = await read(state, import_id)
    assert (imp.error_code, events) == ("rights_expired", [])
