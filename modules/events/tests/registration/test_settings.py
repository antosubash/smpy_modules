"""Registration settings on an event: validation, the wall clock, and what a write may not do.

Service level (no HTTP): ``create_event`` and ``update_event`` are what the API calls.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from simple_module_core.events import EventBus
from sm_events.calendar.plugins import registry
from sm_events.content import bus
from sm_events.content.events_write import update_event
from sm_events.contracts import events as contract
from sm_events.core import constants
from sm_events.core.errors import PublishRequired
from sm_events.core.errors_registration import (
    InvalidRegistration,
    RegistrationHasSeats,
    RegistrationsOrphaned,
    RegistrationUnavailable,
    UnknownRegistrationTarget,
)
from sm_events.models import RegistrationSeat, Revision
from sm_events.web.schemas.events_in import EventPatch
from sqlalchemy import select

from tests.support.access import seed_calendars
from tests.support.providers import KNOWN_TARGET, PROVIDER_ID, install_provider, provider, slow
from tests.support.writes import LOCALES, OWNER, OWNER_P, make

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
        db, who, event.id, EventPatch(expected_revision=event.revision, **body), locales=LOCALES
    )
    await db.refresh(event)


async def _live(db, cal, **kw):
    event = await make(db, OWNER_P, cal, **kw)
    event.status, event.published_at = "published", NOW
    await db.flush()
    await db.refresh(event)
    return event


async def test_defaults_to_none(db, cal):
    event = await make(db, OWNER_P, cal)
    assert event.registration_mode == "none" and event.registration_url is None


async def test_builtin_needs_provider(db, monkeypatch, cal):
    install_provider(monkeypatch)  # nobody provides registration
    with pytest.raises(RegistrationUnavailable) as caught:
        await make(db, OWNER_P, cal, registration=BUILTIN)
    assert caught.value.status_code == 422 and caught.value.code == "registration_unavailable"


async def test_builtin_names_a_provider_when_some_exist(db, cal):
    with pytest.raises(InvalidRegistration):
        await make(db, OWNER_P, cal, registration={"mode": "builtin", "target": "x"})
    with pytest.raises(RegistrationUnavailable):  # a provider this host does not have
        await make(
            db,
            OWNER_P,
            cal,
            registration={**BUILTIN, "provider": "other:registration"},
        )


async def test_target_checked(db, monkeypatch, cal):
    with pytest.raises(UnknownRegistrationTarget):
        await make(db, OWNER_P, cal, registration={**BUILTIN, "target": "nope"})
    install_provider(monkeypatch, provider(check=slow))
    monkeypatch.setattr(constants, "SOURCE_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(RegistrationUnavailable) as caught:
        await make(db, OWNER_P, cal, registration=BUILTIN)
    assert caught.value.status_code == 503


async def test_builtin_stored(db, cal):
    event = await make(
        db,
        OWNER_P,
        cal,
        registration={**BUILTIN, "capacity": 30, "show_seats": True, "reminder_minutes": 60},
    )
    assert (event.registration_mode, event.registration_provider) == ("builtin", PROVIDER_ID)
    assert (event.registration_target, event.registration_capacity) == (KNOWN_TARGET, 30)
    assert event.registration_show_seats is True and event.registration_reminder_minutes == 60
    assert event.registration_url is None


async def test_window_wall_clock(db, cal):
    event = await make(
        db,
        OWNER_P,
        cal,
        registration={
            **BUILTIN,
            "opens_at_local": "2026-07-01T09:00",
            "closes_at_local": "2026-07-01T09:30",
        },
    )
    assert event.registration_opens_at == datetime(2026, 7, 1, 7, 0, tzinfo=UTC)  # Vienna: CEST
    assert event.registration_closes_at == datetime(2026, 7, 1, 7, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("opens", "closes"),
    [("2026-07-01T09:00", "2026-07-01T09:00"), ("2026-07-02T09:00", "2026-07-01T09:00")],
)
async def test_window_must_open_before_it_closes(db, opens, closes, cal):
    with pytest.raises(InvalidRegistration):
        await make(
            db,
            OWNER_P,
            cal,
            registration={**BUILTIN, "opens_at_local": opens, "closes_at_local": closes},
        )


async def test_one_sided_windows_are_fine(db, cal):
    event = await make(
        db, OWNER_P, cal, registration={**BUILTIN, "closes_at_local": "2026-06-30T12:00"}
    )
    assert event.registration_opens_at is None and event.registration_closes_at is not None


async def test_window_follows_the_events_own_zone_after_a_zone_change(db, cal):
    event = await make(db, OWNER_P, cal)
    await _patch(
        db,
        event,
        times={"timezone": "UTC", "start": "2026-07-01T10:00", "end": "2026-07-01T11:00"},
        registration={**BUILTIN, "opens_at_local": "2026-07-01T09:00"},
    )
    assert event.registration_opens_at == datetime(2026, 7, 1, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize("capacity", [1, constants.REGISTRATION_CAPACITY_MAX])
async def test_capacity_at_the_limits(db, capacity, cal):
    event = await make(db, OWNER_P, cal, registration={**BUILTIN, "capacity": capacity})
    assert event.registration_capacity == capacity


@pytest.mark.parametrize("capacity", [0, -1, constants.REGISTRATION_CAPACITY_MAX + 1])
def test_capacity_past_the_limits(capacity):
    from sm_events.web.schemas.registration import RegistrationIn

    with pytest.raises(ValidationError):
        RegistrationIn(**BUILTIN, capacity=capacity)


def test_target_length_bounds():
    from sm_events.web.schemas.registration import RegistrationIn

    RegistrationIn(
        mode="builtin", provider=PROVIDER_ID, target="t" * constants.REGISTRATION_TARGET_MAX
    )
    with pytest.raises(ValidationError):
        RegistrationIn(
            mode="builtin",
            provider=PROVIDER_ID,
            target="t" * (constants.REGISTRATION_TARGET_MAX + 1),
        )
    with pytest.raises(ValidationError):
        RegistrationIn(mode="builtin", provider=PROVIDER_ID, target="two\nlines")
    with pytest.raises(ValidationError):
        RegistrationIn(mode="maybe")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        RegistrationIn(unknown_key=1)  # type: ignore[call-arg]


async def test_reminder_lead_must_be_one_of_the_allowed(db, cal):
    from sm_events.reminders.limits import REMINDER_LEADS

    for lead in REMINDER_LEADS:
        event = await make(db, OWNER_P, cal, registration={**BUILTIN, "reminder_minutes": lead})
        assert event.registration_reminder_minutes == lead
    with pytest.raises(InvalidRegistration):
        await make(db, OWNER_P, cal, registration={**BUILTIN, "reminder_minutes": 61})


@pytest.mark.parametrize(
    "body",
    [
        {"mode": "external"},  # external needs a url
        {"mode": "external", "url": "https://x.example/r", "target": "t"},
        {"mode": "external", "url": "https://x.example/r", "capacity": 5},
        {"mode": "none", "url": "https://x.example/r"},
        {"mode": "none", "capacity": 5},
        {"mode": "none", "show_seats": True},
        {"mode": "builtin", "provider": PROVIDER_ID},  # no target
        {
            "mode": "builtin",
            "target": KNOWN_TARGET,
            "provider": PROVIDER_ID,
            "url": "https://x.example/",
        },
    ],
)
async def test_shape_per_mode(db, body, cal):
    with pytest.raises(InvalidRegistration):
        await make(db, OWNER_P, cal, registration=body)


async def test_external_keeps_url(db, cal):
    event = await make(db, OWNER_P, cal, registration_url="https://x.example/r")
    assert (event.registration_mode, event.registration_url) == (
        "external",
        "https://x.example/r",
    )
    await _patch(db, event, registration_url=None)
    assert (event.registration_mode, event.registration_url) == ("none", None)
    await _patch(db, event, registration_url="https://x.example/s")
    assert event.registration_mode == "external"


async def test_registration_object_wins_and_url_must_agree(db, cal):
    reg = {"mode": "external", "url": "https://x.example/r"}
    event = await make(db, OWNER_P, cal, registration=reg)
    assert event.registration_url == "https://x.example/r"
    with pytest.raises(InvalidRegistration):
        await make(db, OWNER_P, cal, registration=reg, registration_url="https://y.example/")
    same = await make(db, OWNER_P, cal, registration=reg, registration_url="https://x.example/r")
    assert same.registration_mode == "external"


async def test_legacy_url_on_a_builtin_event_is_refused(db, cal):
    event = await make(db, OWNER_P, cal, registration=BUILTIN)
    await _refused(db, event, InvalidRegistration, registration_url="https://x.example/r")
    await _patch(db, event, registration_url=None)  # nothing to clear
    assert event.registration_mode == "builtin"


async def test_switching_to_none_clears_everything(db, cal):
    event = await make(
        db, OWNER_P, cal, registration={**BUILTIN, "capacity": 5, "show_seats": True}
    )
    await _patch(db, event, registration={"mode": "none"})
    assert event.registration_mode == "none"
    assert event.registration_provider is None and event.registration_target is None
    assert event.registration_capacity is None and event.registration_show_seats is False


async def test_an_unchanged_registration_writes_nothing(db, cal):
    event = await make(db, OWNER_P, cal, registration={**BUILTIN, "capacity": 5})
    rev = event.revision
    await _patch(db, event, registration={**BUILTIN, "capacity": 5})
    assert event.revision == rev


async def test_published_change_needs_publish_and_is_announced(db, cal):
    event = await _live(db, cal, registration=BUILTIN)
    await _refused(db, event, PublishRequired, who=OWNER, registration={**BUILTIN, "capacity": 9})
    assert event.registration_capacity is None
    seen: list = []
    events = EventBus()

    async def _on(e):
        seen.append(e)

    events.subscribe(contract.EventUpdated, _on)
    bus.attach(db, events)
    await _patch(db, event, registration={**BUILTIN, "capacity": 9})
    await bus.commit(db)
    (got,) = seen
    assert got.changed == ("registration",) and event.registration_capacity == 9


async def test_a_draft_registration_change_is_silent(db, cal):
    event = await make(db, OWNER_P, cal, registration=BUILTIN)
    seen: list = []
    events = EventBus()

    async def _on(e):
        seen.append(e)

    events.subscribe(contract.EventUpdated, _on)
    bus.attach(db, events)
    await _patch(db, event, registration={**BUILTIN, "capacity": 4})
    await bus.commit(db)
    assert seen == []


async def test_an_uninstalled_provider_is_kept_untouched(db, monkeypatch, cal):
    event = await make(db, OWNER_P, cal, registration={**BUILTIN, "capacity": 7})
    install_provider(monkeypatch)  # the provider is gone
    await _patch(db, event, venue_name="Hall")  # an unrelated write goes through
    assert (event.registration_mode, event.registration_provider) == ("builtin", PROVIDER_ID)
    assert (event.registration_target, event.registration_capacity) == (KNOWN_TARGET, 7)
    await _refused(db, event, RegistrationUnavailable, registration={**BUILTIN, "capacity": 8})
    # sending the same settings back is not a change, so it is not refused either
    await _patch(db, event, registration={**BUILTIN, "capacity": 7})
    assert event.registration_capacity == 7


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
