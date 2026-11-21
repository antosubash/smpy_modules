"""A write that changes nothing writes nothing: no revision, no history, no bus event."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sm_events.content import bus
from sm_events.content.events_write import update_event
from sm_events.content.overrides import set_override
from sm_events.contracts import events as contract
from sm_events.core.errors import Stale
from sm_events.web.schemas.events_in import EventPatch
from sm_events.web.schemas.overrides import OverrideIn

from tests.support.access import seed_calendars
from tests.support.writes import LOCALES, OWNER_P, make, recording, revision_count

WEEKLY = "FREQ=WEEKLY;BYDAY=WE"
SECOND = datetime(2026, 7, 8, 8, tzinfo=UTC)  # the 2nd Wednesday, 10:00 Vienna
SAME = {
    "times": {"timezone": "Europe/Vienna", "start": "2026-07-01T10:00", "end": "2026-07-01T11:00"},
    "texts": {"en": {"title": "Concert"}},
    "venue_name": "Hall",
    "cancelled": False,
}


async def event_of(db, **kw):
    """A published event (what announces itself on the bus when it changes)."""
    cal = (await seed_calendars(db))["I"]
    event = await make(db, OWNER_P, cal, venue_name="Hall", **kw)
    event.status, event.published_at = "published", datetime.now(UTC)
    await db.flush()
    return event


async def patch(db, event, **fields):
    return await update_event(
        db,
        OWNER_P,
        event.id,
        EventPatch(expected_revision=event.revision, **fields),
        locales=LOCALES,
    )


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"venue_name": "Hall"},
        {"cancelled": False},
        {"times": SAME["times"]},
        {"texts": SAME["texts"]},
        SAME,
    ],
)
async def test_an_empty_or_unchanged_patch_writes_nothing(db, fields):
    event = await event_of(db)
    rec = recording(db)
    before = await revision_count(db, event.id)
    got = await patch(db, event, **fields)
    await bus.commit(db)
    assert got.revision == 1
    await db.refresh(event)
    assert event.revision == 1
    assert await revision_count(db, event.id) == before
    assert rec.seen == []


async def test_an_unchanged_patch_with_a_stale_revision_is_still_stale(db):
    event = await event_of(db)
    with pytest.raises(Stale):
        await update_event(db, OWNER_P, event.id, EventPatch(expected_revision=7), locales=LOCALES)


async def test_a_real_change_after_a_noop_still_bumps_once(db):
    event = await event_of(db)
    await patch(db, event)
    got = await patch(db, event, venue_name="Elsewhere")
    assert got.revision == 2 and await revision_count(db, event.id) == 2


# ---- overrides ----


def override(rev, kind="skipped", **kw):
    return OverrideIn(expected_revision=rev, original_start=SECOND, kind=kind, **kw)


async def test_the_same_override_twice_writes_and_emits_nothing(db):
    event = await event_of(db, rrule=WEEKLY)
    rec = recording(db)
    first = await set_override(db, OWNER_P, event.id, override(1, "cancelled", note="n"))
    await bus.commit(db)
    assert [type(e) for e in rec.seen] == [contract.EventCancelled] and event.revision == 2
    again = await set_override(db, OWNER_P, event.id, override(2, "cancelled", note="n"))
    await bus.commit(db)
    assert again.id == first.id
    await db.refresh(event)
    assert event.revision == 2  # nothing bumped
    assert await revision_count(db, event.id) == 2  # created + the one override_set
    assert len(rec.seen) == 1  # no second EventCancelled


async def test_a_re_move_reports_the_previous_slot_as_old(db):
    event = await event_of(db, rrule=WEEKLY)
    rec = recording(db)
    first = {"kind": "moved", "start": "2026-07-09T11:00", "end": "2026-07-09T12:00"}
    await set_override(db, OWNER_P, event.id, override(1, **first))
    await bus.commit(db)
    again = {"kind": "moved", "start": "2026-07-10T15:00", "end": "2026-07-10T16:00"}
    await set_override(db, OWNER_P, event.id, override(2, **again))
    await bus.commit(db)
    one, two = rec.seen
    assert (one.old_start, one.old_end) == (SECOND, datetime(2026, 7, 8, 9, tzinfo=UTC))
    assert (two.old_start, two.old_end) == (
        datetime(2026, 7, 9, 9, tzinfo=UTC),
        datetime(2026, 7, 9, 10, tzinfo=UTC),
    )
    assert two.new_start == datetime(2026, 7, 10, 13, tzinfo=UTC)
