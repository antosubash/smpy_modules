"""Trash and restore."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sm_events.content import bus
from sm_events.content.events_trash import restore_event, trash_event
from sm_events.contracts import events as contract
from sm_events.core.access.events import visible_events
from sm_events.core.errors import NotFound, PublishRequired, Stale
from sm_events.models import Event, Revision
from sqlalchemy import select

from tests.support.access import seed_calendars
from tests.support.calendars import seed_event
from tests.support.writes import OWNER, OWNER_P, SE, make, recording, revision_count


async def visible_ids(db, who):
    return {e.id for e in (await db.execute(visible_events(who))).scalars()}


async def test_trash_restore(db):
    cal = (await seed_calendars(db))["I"]
    event = await seed_event(db, cal, status="published", published_at=datetime.now(UTC))
    rec = recording(db)
    await trash_event(db, OWNER_P, event.id, 1)
    assert event.revision == 2
    await bus.commit(db)
    (got,) = rec.seen
    assert isinstance(got, contract.EventDeleted) and got.was_published is True
    assert event.id not in await visible_ids(db, OWNER_P)
    actions = (
        await db.execute(
            select(Revision.number, Revision.action).where(Revision.event_id == event.id)
        )
    ).all()
    assert actions == [(2, "trashed")]
    back = await restore_event(db, OWNER_P, event.id, 2)
    assert back.status == "published" and back.is_deleted is False and back.revision == 3
    assert event.id in await visible_ids(db, OWNER_P)
    await bus.commit(db)
    assert len(rec.seen) == 1  # reinstating announces nothing


async def test_draft_trash_announces_nothing(db):
    cal = (await seed_calendars(db))["I"]
    event = await make(db, OWNER, cal)
    rec = recording(db)
    await trash_event(db, OWNER, event.id, 1)
    await bus.commit(db)
    assert rec.seen == []


async def test_trashed_then_unpublished_event_still_announces_deletion(db):
    cal = (await seed_calendars(db))["I"]
    event = await seed_event(db, cal, status="draft", published_at=datetime.now(UTC))
    rec = recording(db)
    await trash_event(db, OWNER, event.id, 1)
    await bus.commit(db)
    assert [e.was_published for e in rec.seen] == [False]


async def test_trash_is_stale_guarded(db):
    cal = (await seed_calendars(db))["I"]
    event = await make(db, OWNER, cal)
    with pytest.raises(Stale):
        await trash_event(db, OWNER, event.id, 5)
    await db.refresh(event)
    assert event.is_deleted is False and event.revision == 1
    await trash_event(db, OWNER, event.id, 1)
    with pytest.raises(Stale):
        await restore_event(db, OWNER, event.id, 1)
    with pytest.raises(NotFound):  # a trashed event is not trashable again
        await trash_event(db, OWNER, event.id, 2)


async def test_restore_of_a_live_event_is_not_found(db):
    cal = (await seed_calendars(db))["I"]
    event = await make(db, OWNER, cal)
    with pytest.raises(NotFound):
        await restore_event(db, OWNER, event.id, 1)


async def test_locked_trash_and_restore_need_publish(db):
    cal = (await seed_calendars(db))["P"]
    event = await seed_event(db, cal, status="published", published_at=datetime.now(UTC))
    with pytest.raises(PublishRequired):
        await trash_event(db, SE, event.id, 1)
    assert await revision_count(db, event.id) == 0
    await trash_event(db, OWNER_P, event.id, 1)
    with pytest.raises(PublishRequired):
        await restore_event(db, SE, event.id, 2)
    row = (
        await db.execute(
            select(Event).where(Event.id == event.id).execution_options(include_deleted=True)
        )
    ).scalar_one()
    assert row.is_deleted is True


async def test_events_of_a_trashed_calendar_are_invisible(db):
    cals = await seed_calendars(db)
    event = await make(db, OWNER, cals["I"])
    await db.delete(cals["I"])
    await db.flush()
    assert event.id not in await visible_ids(db, OWNER_P)
    with pytest.raises(NotFound):
        await trash_event(db, OWNER_P, event.id, 1)
