"""Registration settings: what a write may not do to the seats that exist, and the history."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sm_events.calendar.plugins import registry
from sm_events.content.events_write import update_event
from sm_events.core.errors_registration import (
    RegistrationHasSeats,
    RegistrationsOrphaned,
)
from sm_events.models import RegistrationSeat, Revision
from sm_events.web.schemas.events_in import EventPatch
from sqlalchemy import select

from tests.support.access import seed_calendars
from tests.support.providers import KNOWN_TARGET, PROVIDER_ID, install_provider, provider
from tests.support.writes import EDITOR, LOCALES, OWNER_P, make

BUILTIN = {"mode": "builtin", "provider": PROVIDER_ID, "target": KNOWN_TARGET}
WEEKLY = "FREQ=WEEKLY;BYDAY=WE"
NOW = datetime(2026, 7, 1, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _provider(monkeypatch):
    install_provider(monkeypatch, provider())
    yield
    registry.reset_registry()


@pytest.fixture
async def cal(db):
    return (await seed_calendars(db))["I"]


async def _refused(db, event, exc, who=OWNER_P, **body):
    """The write is refused; the savepoint's rollback expired the event, so reload it."""
    with pytest.raises(exc) as caught:
        await _patch(db, event, who=who, **body)
    await db.refresh(event)
    return caught.value


async def _patch(db, event, who=OWNER_P, **body):
    await update_event(
        db,
        who,
        event.id,
        EventPatch(expected_revision=event.revision, **body),
        locales=LOCALES,
        viewer=EDITOR,
    )
    await db.refresh(event)


async def _live(db, cal, **kw):
    event = await make(db, OWNER_P, cal, **kw)
    event.status, event.published_at = "published", NOW
    await db.flush()
    await db.refresh(event)
    return event


def _seat(event, key=None, holder="h1"):
    return RegistrationSeat(
        event_id=event.id,
        occurrence_key=key or str(event.id),
        provider=PROVIDER_ID,
        target=KNOWN_TARGET,
        holder=holder,
    )


async def test_has_seats_guard(db, cal):
    event = await make(db, OWNER_P, cal, registration=BUILTIN)
    db.add(_seat(event))
    await db.flush()
    for body in (
        {"mode": "none"},
        {"mode": "external", "url": "https://x.example/r"},
        {**BUILTIN, "target": "other-target"},
    ):
        got = await _refused(db, event, RegistrationHasSeats, registration=body)
        assert got.status_code == 409 and got.code == "registration_has_seats"
    await _patch(db, event, registration={**BUILTIN, "capacity": 3})  # settings may change
    assert event.registration_capacity == 3


async def test_has_seats_guard_is_per_event(db, cal):
    one = await make(db, OWNER_P, cal, registration=BUILTIN)
    two = await make(db, OWNER_P, cal, registration=BUILTIN)
    db.add(_seat(one))
    await db.flush()
    await _patch(db, two, registration={"mode": "none"})
    assert two.registration_mode == "none"


async def test_orphan_guard(db, cal):
    event = await make(db, OWNER_P, cal, rrule=WEEKLY, registration=BUILTIN)
    db.add(_seat(event, key=f"{event.id}:20260708T080000Z"))  # 8 July, 10:00 Vienna
    await db.flush()
    got = await _refused(
        db, event, RegistrationsOrphaned, rrule="FREQ=WEEKLY;BYDAY=WE;INTERVAL=2"
    )  # 1 and 15 July: no 8th
    assert got.status_code == 409 and got.code == "registrations_orphaned"
    assert event.rrule == WEEKLY  # nothing was written
    await _patch(db, event, rrule="FREQ=WEEKLY;BYDAY=WE,FR")  # keeps 8 July
    assert event.rrule == "FREQ=WEEKLY;BYDAY=WE,FR"
    await _refused(  # moving the start orphans every key
        db,
        event,
        RegistrationsOrphaned,
        times={"timezone": "Europe/Vienna", "start": "2026-07-01T11:00", "end": "2026-07-01T12:00"},
    )


async def test_orphan_guard_for_a_series_turned_into_a_one_off_and_back(db, cal):
    series = await make(db, OWNER_P, cal, rrule=WEEKLY, registration=BUILTIN)
    db.add(_seat(series, key=f"{series.id}:20260708T080000Z"))
    await db.flush()
    await _refused(db, series, RegistrationsOrphaned, rrule=None)
    one_off = await make(db, OWNER_P, cal, registration=BUILTIN)
    db.add(_seat(one_off, holder="h2"))  # the key of a one-off
    await db.flush()
    await _refused(db, one_off, RegistrationsOrphaned, rrule=WEEKLY)


async def test_a_one_offs_own_time_change_keeps_its_seats(db, cal):
    event = await make(db, OWNER_P, cal, registration=BUILTIN)
    db.add(_seat(event))
    await db.flush()
    await _patch(
        db,
        event,
        times={"timezone": "Europe/Vienna", "start": "2026-07-05T10:00", "end": "2026-07-05T11:00"},
    )
    assert event.starts_at.day == 5


async def test_seats_of_other_events_do_not_block_a_series_change(db, cal):
    other = await make(db, OWNER_P, cal, rrule=WEEKLY, registration=BUILTIN)
    mine = await make(db, OWNER_P, cal, rrule=WEEKLY, registration=BUILTIN)
    db.add(_seat(other, key=f"{other.id}:20260708T080000Z"))
    await db.flush()
    await _patch(db, mine, rrule="FREQ=WEEKLY;BYDAY=WE;INTERVAL=2")
    assert (await db.execute(select(RegistrationSeat))).scalars().one().event_id == other.id


async def test_a_registration_change_is_recorded_in_the_history(db, cal):
    event = await make(db, OWNER_P, cal, registration=BUILTIN)
    await _patch(db, event, registration={**BUILTIN, "capacity": 12})
    rows = (await db.execute(select(Revision).where(Revision.event_id == event.id))).scalars().all()
    latest = max(rows, key=lambda r: r.number)
    assert latest.action == "updated" and latest.snapshot["registration_capacity"] == 12
    assert latest.snapshot["registration_target"] == KNOWN_TARGET
