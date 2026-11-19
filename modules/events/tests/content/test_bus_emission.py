"""Which write announces which event: the final list, and only for live events."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from simple_module_core.events import Event, EventBus
from sm_events.content import bus
from sm_events.content.events_trash import restore_event, trash_event
from sm_events.content.events_write import update_event
from sm_events.content.overrides import clear_override, set_override
from sm_events.content.workflow import transition
from sm_events.contracts import events as contract
from sm_events.models import OccurrenceOverride
from sm_events.web.schemas.events_in import EventPatch
from sm_events.web.schemas.overrides import OverrideIn
from sqlalchemy import select

from tests.support.access import seed_calendars
from tests.support.writes import LOCALES, OWNER_P, make, times

NOW = datetime(2026, 7, 1, 12, tzinfo=UTC)
SECOND = datetime(2026, 7, 8, 8, tzinfo=UTC)
ALL = (
    contract.EventPublished,
    contract.EventRescheduled,
    contract.EventCancelled,
    contract.EventDeleted,
    contract.EventUnpublished,
    contract.EventReinstated,
    contract.OccurrenceSkipped,
    contract.EventRestored,
    contract.EventUpdated,
)


class Seen:
    def __init__(self, db) -> None:
        self.bus = EventBus()
        self.items: list[Event] = []
        for cls in ALL:
            self.bus.subscribe(cls, self._on)
        bus.attach(db, self.bus)

    async def _on(self, event):
        self.items.append(event)


async def live(db, *, series=False, status="published"):
    cal = (await seed_calendars(db))["I"]
    event = await make(db, OWNER_P, cal, **({"rrule": "FREQ=WEEKLY;BYDAY=WE"} if series else {}))
    event.status = status
    event.published_at = NOW if status == "published" else None
    await db.flush()
    await db.refresh(event)
    return event


async def patch(db, event, **kw):
    await update_event(
        db, OWNER_P, event.id, EventPatch(expected_revision=event.revision, **kw), locales=LOCALES
    )
    await db.refresh(event)


async def finish(db, seen):
    await bus.commit(db)
    return seen.items


async def test_unpublish(db):
    event = await live(db)
    seen = Seen(db)
    await transition(db, OWNER_P, event.id, "unpublish", expected=event.revision, now=NOW)
    (got,) = await finish(db, seen)
    assert isinstance(got, contract.EventUnpublished) and got.was_scheduled is False
    assert got.event_id == event.id and got.tenant_id == "default" and got.uid == event.uid


async def test_unschedule(db):
    event = await live(db, status="in_review")
    event.publish_at = datetime(2026, 8, 1, tzinfo=UTC)
    await db.flush()
    await db.refresh(event)
    seen = Seen(db)
    await transition(db, OWNER_P, event.id, "unschedule", expected=event.revision, now=NOW)
    (got,) = await finish(db, seen)
    assert isinstance(got, contract.EventUnpublished) and got.was_scheduled is True


async def test_clearing_cancelled_flag_reinstates(db):
    event = await live(db)
    event.cancelled = True
    await db.flush()
    await db.refresh(event)
    seen = Seen(db)
    await patch(db, event, cancelled=False)
    (got,) = await finish(db, seen)
    assert isinstance(got, contract.EventReinstated) and got.original_start is None


async def _override(db, event, kind):
    await set_override(
        db,
        OWNER_P,
        event.id,
        OverrideIn(expected_revision=event.revision, original_start=SECOND, kind=kind),
    )
    await db.refresh(event)


async def test_clearing_a_cancelled_override_reinstates(db):
    event = await live(db, series=True)
    await _override(db, event, "cancelled")
    (row,) = (await db.execute(select(OccurrenceOverride))).scalars().all()
    seen = Seen(db)
    await clear_override(db, OWNER_P, event.id, row.id, event.revision)
    (got,) = await finish(db, seen)
    assert isinstance(got, contract.EventReinstated) and got.original_start == SECOND


async def test_replacing_a_cancelled_override_reinstates(db):
    event = await live(db, series=True)
    await _override(db, event, "cancelled")
    seen = Seen(db)
    await _override(db, event, "skipped")
    kinds = [type(e) for e in await finish(db, seen)]
    assert kinds == [contract.OccurrenceSkipped, contract.EventReinstated]


async def test_skipped_override(db):
    event = await live(db, series=True)
    seen = Seen(db)
    await _override(db, event, "skipped")
    (got,) = await finish(db, seen)
    assert isinstance(got, contract.OccurrenceSkipped) and got.original_start == SECOND


async def test_clearing_a_skip_is_an_update(db):
    event = await live(db, series=True)
    await _override(db, event, "skipped")
    (row,) = (await db.execute(select(OccurrenceOverride))).scalars().all()
    seen = Seen(db)
    await clear_override(db, OWNER_P, event.id, row.id, event.revision)
    (got,) = await finish(db, seen)
    assert isinstance(got, contract.EventUpdated) and got.changed == ("overrides",)


async def test_restoring_a_published_event(db):
    event = await live(db)
    rev = event.revision
    await trash_event(db, OWNER_P, event.id, rev)
    seen = Seen(db)
    await restore_event(db, OWNER_P, event.id, rev + 1)  # the trash bumped the revision
    (got,) = await finish(db, seen)
    assert isinstance(got, contract.EventRestored) and got.event_id == event.id


async def test_restoring_a_draft_is_silent(db):
    event = await live(db, status="draft")
    rev = event.revision
    await trash_event(db, OWNER_P, event.id, rev)
    seen = Seen(db)
    await restore_event(db, OWNER_P, event.id, rev + 1)  # the trash bumped the revision
    assert await finish(db, seen) == []


async def test_a_title_or_venue_change_is_an_update(db):
    event = await live(db)
    seen = Seen(db)
    await patch(db, event, venue_name="Hall", texts={"en": {"title": "New title"}})
    (got,) = await finish(db, seen)
    assert isinstance(got, contract.EventUpdated)
    assert got.changed == ("texts", "venue_name")


async def test_a_draft_write_is_silent(db):
    event = await live(db, status="draft")
    seen = Seen(db)
    await patch(db, event, venue_name="Hall")
    assert await finish(db, seen) == []


async def test_a_published_reschedule_is_only_a_reschedule(db):
    event = await live(db)
    seen = Seen(db)
    await patch(db, event, venue_name="Hall", times=times("2026-07-05T10:00", "2026-07-05T11:00"))
    (got,) = await finish(db, seen)
    assert isinstance(got, contract.EventRescheduled)


async def test_a_rolled_back_write_announces_nothing(db):
    event = await live(db)
    seen = Seen(db)
    with pytest.raises(Exception):  # noqa: B017 - a stale revision
        await update_event(
            db,
            OWNER_P,
            event.id,
            EventPatch(expected_revision=99, venue_name="Hall"),
            locales=LOCALES,
        )
    assert await finish(db, seen) == []
