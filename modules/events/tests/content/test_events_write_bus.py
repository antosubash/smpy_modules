"""What a write announces on the bus: only live events, only after the commit."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sm_events.content import bus
from sm_events.content.events_write import update_event
from sm_events.contracts import events as contract
from sm_events.core.errors import Stale
from sm_events.web.schemas.events_in import EventPatch

from tests.support.access import seed_calendars
from tests.support.calendars import seed_event
from tests.support.writes import LOCALES, OWNER, OWNER_P, make, recording, times


async def update(db, who, event, rev=None, **kw):
    return await update_event(
        db,
        who,
        event.id,
        EventPatch(expected_revision=event.revision if rev is None else rev, **kw),
        locales=LOCALES,
    )


async def cals(db):
    return await seed_calendars(db)


async def test_draft_write_no_bus(db):
    cal = (await cals(db))["I"]
    event = await make(db, OWNER, cal)
    rec = recording(db)
    await update(
        db, OWNER, event, times=times("2026-07-05T10:00", "2026-07-05T11:00"), cancelled=True
    )
    await bus.commit(db)
    assert rec.seen == []


async def test_published_reschedule_emits(db):
    cal = (await cals(db))["I"]
    event = await seed_event(db, cal, status="published", published_at=datetime.now(UTC))
    old = (event.starts_at, event.ends_at)
    rec = recording(db)
    await update(
        db,
        OWNER_P,
        event,
        times={"timezone": "UTC", "start": "2026-07-02T10:00", "end": "2026-07-02T12:00"},
    )
    assert rec.seen == []  # not before the commit
    await bus.commit(db)
    (got,) = rec.seen
    assert isinstance(got, contract.EventRescheduled)
    assert got.original_start is None and got.rule_changed is False
    assert (got.old_start, got.old_end) == old
    assert got.new_start == datetime(2026, 7, 2, 10, tzinfo=UTC)
    assert got.new_end == datetime(2026, 7, 2, 12, tzinfo=UTC)
    assert got.event_id == event.id and got.uid == event.uid and got.tenant_id == "default"


async def test_rule_change_flags_it(db):
    cal = (await cals(db))["I"]
    event = await make(db, OWNER_P, cal, rrule="FREQ=WEEKLY;BYDAY=WE")
    event.status, event.published_at = "published", datetime.now(UTC)
    await db.flush()
    rec = recording(db)
    await update(db, OWNER_P, event, rrule="FREQ=WEEKLY;BYDAY=WE;INTERVAL=2")
    await bus.commit(db)
    (got,) = rec.seen
    assert got.rule_changed is True


async def test_cancel_emits_cancelled(db):
    cal = (await cals(db))["I"]
    event = await seed_event(db, cal, status="published", published_at=datetime.now(UTC))
    rec = recording(db)
    await update(db, OWNER_P, event, cancelled=True)
    await bus.commit(db)
    (got,) = rec.seen
    assert isinstance(got, contract.EventCancelled) and got.original_start is None
    await update(db, OWNER_P, event, cancelled=False)  # reinstating announces nothing
    await bus.commit(db)
    assert len(rec.seen) == 1


async def test_a_refused_write_publishes_nothing(db):
    cal = (await cals(db))["I"]
    event = await seed_event(db, cal, status="published", published_at=datetime.now(UTC))
    rec = recording(db)
    with pytest.raises(Stale):
        await update(db, OWNER_P, event, rev=9, cancelled=True)
    await bus.commit(db)
    assert rec.seen == []
