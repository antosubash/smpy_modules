"""Sub-events: one level, same calendar, never recurring."""

from __future__ import annotations

import pytest
from sm_events.content.events_trash import restore_event, trash_event
from sm_events.content.events_write import update_event
from sm_events.core.errors import HasSubEvents, InvalidParent
from sm_events.web.schemas.events_in import EventPatch

from tests.support.access import seed_calendars
from tests.support.writes import LOCALES, OWNER, make


async def test_child_same_calendar(db):
    cal = (await seed_calendars(db))["I"]
    parent = await make(db, OWNER, cal)
    child = await make(db, OWNER, cal, parent_id=parent.id)
    assert child.parent_id == parent.id


async def test_child_in_another_calendar_refused(db):
    cals = await seed_calendars(db)
    parent = await make(db, OWNER, cals["I"])
    with pytest.raises(InvalidParent):
        await make(db, OWNER, cals["U"], parent_id=parent.id)


async def test_unknown_parent_refused(db):
    import uuid

    cal = (await seed_calendars(db))["I"]
    with pytest.raises(InvalidParent):
        await make(db, OWNER, cal, parent_id=uuid.uuid4())


async def test_no_grandchildren(db):
    cal = (await seed_calendars(db))["I"]
    parent = await make(db, OWNER, cal)
    child = await make(db, OWNER, cal, parent_id=parent.id)
    with pytest.raises(InvalidParent):
        await make(db, OWNER, cal, parent_id=child.id)


async def test_recurring_parent_refused(db):
    cal = (await seed_calendars(db))["I"]
    series = await make(db, OWNER, cal, rrule="FREQ=WEEKLY;BYDAY=WE")
    with pytest.raises(InvalidParent):
        await make(db, OWNER, cal, parent_id=series.id)


async def test_recurring_child_refused(db):
    cal = (await seed_calendars(db))["I"]
    parent = await make(db, OWNER, cal)
    with pytest.raises(InvalidParent):
        await make(db, OWNER, cal, parent_id=parent.id, rrule="FREQ=WEEKLY;BYDAY=WE")


async def test_adding_rrule_to_a_parent_refused(db):
    cal = (await seed_calendars(db))["I"]
    parent = await make(db, OWNER, cal)
    await make(db, OWNER, cal, parent_id=parent.id)
    with pytest.raises(InvalidParent):
        await update_event(
            db, OWNER, parent.id,
            EventPatch(expected_revision=1, rrule="FREQ=WEEKLY;BYDAY=WE"), locales=LOCALES,
        )  # fmt: skip
    await db.refresh(parent)
    assert parent.revision == 1 and parent.rrule is None


async def test_adding_rrule_to_a_child_refused(db):
    cal = (await seed_calendars(db))["I"]
    parent = await make(db, OWNER, cal)
    child = await make(db, OWNER, cal, parent_id=parent.id)
    with pytest.raises(InvalidParent):
        await update_event(
            db, OWNER, child.id,
            EventPatch(expected_revision=1, rrule="FREQ=WEEKLY;BYDAY=WE"), locales=LOCALES,
        )  # fmt: skip


async def test_parent_with_children_cannot_be_trashed(db):
    cal = (await seed_calendars(db))["I"]
    parent = await make(db, OWNER, cal)
    child = await make(db, OWNER, cal, parent_id=parent.id)
    with pytest.raises(HasSubEvents) as raised:
        await trash_event(db, OWNER, parent.id, 1)
    assert raised.value.code == "has_sub_events"
    await db.refresh(parent)
    assert parent.revision == 1 and parent.is_deleted is False
    await trash_event(db, OWNER, child.id, 1)
    await trash_event(db, OWNER, parent.id, 1)


async def test_child_cannot_come_back_under_a_trashed_parent(db):
    cal = (await seed_calendars(db))["I"]
    parent = await make(db, OWNER, cal)
    child = await make(db, OWNER, cal, parent_id=parent.id)
    await trash_event(db, OWNER, child.id, 1)
    await trash_event(db, OWNER, parent.id, 1)
    child_id = child.id
    with pytest.raises(InvalidParent):
        await restore_event(db, OWNER, child_id, 2)
    await restore_event(db, OWNER, parent.id, 2)
    assert (await restore_event(db, OWNER, child_id, 2)).is_deleted is False
