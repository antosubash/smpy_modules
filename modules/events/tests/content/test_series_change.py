"""Changing a series, the overrides it orphans, and the preview."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sm_events.content import schedule
from sm_events.content.events_write import update_event
from sm_events.content.overrides import set_override
from sm_events.content.series_change import orphans, preview
from sm_events.core.errors import NotFound, OverridesOrphaned
from sm_events.models import OccurrenceOverride, Revision
from sm_events.web.schemas.events_in import EventPatch, TimesIn
from sm_events.web.schemas.overrides import OverrideIn, PreviewIn
from sqlalchemy import select

from tests.support.access import seed_calendars
from tests.support.calendars import seed_event
from tests.support.writes import LOCALES, OWNER_P, VIEWER, make, times

WEEKLY = "FREQ=WEEKLY;BYDAY=WE"
SECOND = datetime(2026, 7, 8, 8, tzinfo=UTC)
THIRD = datetime(2026, 7, 15, 8, tzinfo=UTC)


async def with_override(db, rrule=WEEKLY):
    cal = (await seed_calendars(db))["I"]
    event = await make(db, OWNER_P, cal, rrule=rrule)
    await set_override(
        db,
        OWNER_P,
        event.id,
        OverrideIn(expected_revision=1, original_start=SECOND, kind="skipped"),
    )
    return event


async def patch(db, event, **kw):
    return await update_event(
        db, OWNER_P, event.id, EventPatch(expected_revision=event.revision, **kw), locales=LOCALES
    )


async def override_rows(db, event):
    found = await db.execute(
        select(OccurrenceOverride).where(OccurrenceOverride.event_id == event.id)
    )
    return found.scalars().all()


TUESDAYS = {"rrule": "FREQ=WEEKLY;BYDAY=TU", "times": times("2026-06-30T10:00", "2026-06-30T11:00")}


async def test_rule_change_reports_orphans(db):
    event = await with_override(db)
    assert event.revision == 2
    with pytest.raises(OverridesOrphaned) as raised:
        await patch(db, event, **TUESDAYS)
    assert raised.value.code == "overrides_orphaned"
    await db.refresh(event)
    assert event.revision == 2 and event.rrule == WEEKLY
    assert len(await override_rows(db, event)) == 1


async def test_drop_flag_deletes_and_notes(db):
    event = await with_override(db)
    await patch(db, event, drop_orphaned_overrides=True, **TUESDAYS)
    assert event.rrule == "FREQ=WEEKLY;BYDAY=TU" and event.revision == 3
    assert await override_rows(db, event) == []
    last = (
        await db.execute(
            select(Revision).where(Revision.event_id == event.id, Revision.number == 3)
        )
    ).scalar_one()
    assert last.action == "updated"
    assert last.note == "dropped overrides: 2026-07-08T08:00Z"
    assert last.snapshot["overrides"] == []


async def test_start_shift_orphans_all(db):
    event = await with_override(db)
    with pytest.raises(OverridesOrphaned):
        await patch(db, event, times=times("2026-07-01T11:00", "2026-07-01T12:00"))
    await db.refresh(event)
    await patch(
        db, event, times=times("2026-07-01T11:00", "2026-07-01T12:00"), drop_orphaned_overrides=True
    )
    assert await override_rows(db, event) == []


async def test_unchanged_rule_no_orphans(db):
    event = await with_override(db)
    await patch(db, event, rrule=WEEKLY, times=times())
    assert len(await override_rows(db, event)) == 1 and event.revision == 3
    await patch(db, event, venue_name="Hall")  # not a schedule change: not even looked at
    assert len(await override_rows(db, event)) == 1


async def test_a_rule_that_keeps_the_instant_keeps_the_override(db):
    event = await with_override(db)
    await patch(db, event, rrule="FREQ=WEEKLY;BYDAY=WE;COUNT=10")  # still has 8 July
    assert len(await override_rows(db, event)) == 1
    with pytest.raises(OverridesOrphaned):
        await patch(db, event, rrule="FREQ=WEEKLY;BYDAY=WE;COUNT=1")  # ends before it


async def test_becoming_a_one_off_orphans_every_override(db):
    event = await with_override(db)
    with pytest.raises(OverridesOrphaned):
        await patch(db, event, rrule=None)
    await db.refresh(event)
    await patch(db, event, rrule=None, drop_orphaned_overrides=True)
    assert event.rrule is None and event.recurrence_until is None


async def test_orphans_helper(db):
    event = await with_override(db)
    same = schedule.build(TimesIn(**times()), WEEKLY)
    assert await orphans(db, event, same) == []
    assert [
        o.original_start for o in await orphans(db, event, schedule.build(TimesIn(**times()), None))
    ] == [SECOND]


async def test_preview_next_n_after(db):
    data = PreviewIn(
        times=times(), rrule=WEEKLY, after=datetime(2026, 10, 20, tzinfo=UTC), count=10
    )
    got = await preview(None, OWNER_P, data)  # no event: no database
    assert len(got.occurrences) == 10 and got.recurrence_until is None
    first, last = got.occurrences[0], got.occurrences[-1]
    assert (first.start_local, first.end_local) == ("2026-10-21T10:00", "2026-10-21T11:00")
    assert first.start == datetime(2026, 10, 21, 8, tzinfo=UTC)  # still summer time
    assert got.occurrences[1].start == datetime(2026, 10, 28, 9, tzinfo=UTC)  # after 25 Oct
    assert got.occurrences[1].start_local == "2026-10-28T10:00"
    assert last.start_local == "2026-12-23T10:00"
    assert got.orphaned == []


async def test_preview_defaults_and_counts():
    ten = await preview(None, OWNER_P, PreviewIn(times=times(), rrule=WEEKLY))
    assert len(ten.occurrences) == 10
    assert ten.occurrences[0].start_local == "2026-07-01T10:00"
    finite = await preview(None, OWNER_P, PreviewIn(times=times(), rrule="FREQ=DAILY;COUNT=3"))
    assert len(finite.occurrences) == 3
    assert finite.recurrence_until == datetime(2026, 7, 3, 9, tzinfo=UTC)
    single = await preview(None, OWNER_P, PreviewIn(times=times()))
    assert len(single.occurrences) == 1 and single.recurrence_until is None
    with pytest.raises(ValueError):
        PreviewIn(times=times(), count=51)
    with pytest.raises(ValueError):
        PreviewIn(times=times(), count=0)


async def test_preview_all_day_uses_dates():
    got = await preview(
        None,
        OWNER_P,
        PreviewIn(
            times={
                "all_day": True,
                "timezone": "Europe/Vienna",
                "start": "2026-03-28",
                "end": "2026-03-29",
            },
            rrule="FREQ=WEEKLY;BYDAY=SA",
            count=2,
        ),
    )
    assert [(o.start_local, o.end_local) for o in got.occurrences] == [
        ("2026-03-28", "2026-03-29"),
        ("2026-04-04", "2026-04-05"),
    ]


async def test_preview_refuses_a_start_outside_its_rule():
    from sm_events.core.errors import InvalidRule

    with pytest.raises(InvalidRule) as raised:
        await preview(None, VIEWER, PreviewIn(times=times(), rrule="FREQ=WEEKLY;BYDAY=TH"))
    assert raised.value.code == "start_not_in_rule"


async def test_preview_shows_what_the_change_would_orphan(db):
    event = await with_override(db)
    data = PreviewIn(event_id=event.id, count=3, **TUESDAYS)
    got = await preview(db, OWNER_P, data)
    assert [o.original_start for o in got.orphaned] == [SECOND]
    assert got.orphaned[0].kind == "skipped"
    assert got.occurrences[0].start_local == "2026-06-30T10:00"
    unchanged = await preview(
        db, OWNER_P, PreviewIn(event_id=event.id, times=times(), rrule=WEEKLY)
    )
    assert unchanged.orphaned == []


async def test_preview_invisible_event_404(db):
    cal = (await seed_calendars(db))["P"]
    draft = await seed_event(db, cal)
    with pytest.raises(NotFound):
        await preview(db, VIEWER, PreviewIn(event_id=draft.id, times=times()))
    import uuid

    with pytest.raises(NotFound):
        await preview(db, OWNER_P, PreviewIn(event_id=uuid.uuid4(), times=times()))
