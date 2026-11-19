"""Registration settings on an event: validation, the wall clock, and what a write may not do.

Service level (no HTTP): ``create_event`` and ``update_event`` are what the API calls.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sm_events.calendar.plugins import registry
from sm_events.content.events_write import update_event
from sm_events.core import constants
from sm_events.core.errors_registration import (
    InvalidRegistration,
    RegistrationUnavailable,
    UnknownRegistrationTarget,
)
from sm_events.web.schemas.events_in import EventPatch

from tests.support.access import seed_calendars
from tests.support.providers import KNOWN_TARGET, PROVIDER_ID, install_provider, provider, slow
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
