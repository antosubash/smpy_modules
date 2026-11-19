"""Registration settings: the mode, the legacy URL and who may change a published event."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from simple_module_core.events import EventBus
from sm_events.calendar.plugins import registry
from sm_events.content import bus
from sm_events.content.events_write import update_event
from sm_events.contracts import events as contract
from sm_events.core.errors import PublishRequired
from sm_events.core.errors_registration import (
    InvalidRegistration,
)
from sm_events.web.schemas.events_in import EventPatch

from tests.support.access import seed_calendars
from tests.support.providers import KNOWN_TARGET, PROVIDER_ID, install_provider, provider
from tests.support.writes import EDITOR, LOCALES, OWNER, OWNER_P, make

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
