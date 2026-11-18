"""``extra`` on create and update: validated, immutable type, uninstalled bytes kept."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.exceptions import RequestValidationError
from sm_events.calendar.plugins import registry
from sm_events.content import revisions
from sm_events.content.events_trash import restore_event, trash_event
from sm_events.content.events_write import update_event
from sm_events.content.overrides import clear_override, set_override
from sm_events.content.workflow import transition
from sm_events.core.errors import ImmutableField, UnknownType
from sm_events.core.errors_extensions import ExtraTooLarge, TypeNotInstalled
from sm_events.models import Event, OccurrenceOverride, Revision
from sm_events.web.schemas.events_in import EventPatch
from sm_events.web.schemas.overrides import OverrideIn
from sqlalchemy import select, text

from tests.pg_support import USING_POSTGRES
from tests.support.access import seed_calendars
from tests.support.sources import install_talk
from tests.support.writes import LOCALES, OWNER_P, make

NOW = datetime(2026, 7, 1, 12, tzinfo=UTC)
RAW = {"b": 1, "a": [1, 2], "nested": {"z": None, "y": "ü"}}
GONE = "gone:thing"


@pytest.fixture(autouse=True)
def talk(monkeypatch):
    install_talk(monkeypatch)
    yield
    registry.reset_registry()


async def cal(db):
    return (await seed_calendars(db))["I"]


def patch(event, **fields) -> EventPatch:
    return EventPatch(expected_revision=event.revision, **fields)


async def test_create_with_plugin_type(db):
    event = await make(db, OWNER_P, await cal(db), type="acme:talk", extra={"speaker": "Ada"})
    assert event.type == "acme:talk"
    assert event.extra == {"speaker": "Ada", "room": None, "level": "intro"}


async def test_create_default_type_has_empty_extra(db):
    assert (await make(db, OWNER_P, await cal(db))).extra == {}


async def test_create_unknown_type_422(db):
    with pytest.raises(UnknownType):
        await make(db, OWNER_P, await cal(db), type=GONE, extra={"a": 1})


async def test_create_validates_extra(db):
    calendar = await cal(db)
    with pytest.raises(RequestValidationError) as caught:
        await make(db, OWNER_P, calendar, type="acme:talk", extra={"room": "1"})
    assert caught.value.errors()[0]["loc"] == ("body", "extra", "speaker")
    with pytest.raises(RequestValidationError):
        await make(db, OWNER_P, calendar, extra={"nope": 1})  # the built-in type has none
    with pytest.raises(ExtraTooLarge):
        await make(db, OWNER_P, calendar, type="acme:talk", extra={"speaker": "x" * 20_000})
    assert (await db.execute(select(Event))).scalars().all() == []


async def test_patch_replaces_extra_validated(db):
    event = await make(db, OWNER_P, await cal(db), type="acme:talk", extra={"speaker": "Ada"})
    got = await update_event(
        db, OWNER_P, event.id, patch(event, extra={"speaker": "Bo", "room": "7"}), locales=LOCALES
    )
    await db.refresh(got)
    assert got.extra == {"speaker": "Bo", "room": "7", "level": "intro"} and got.revision == 2
    with pytest.raises(RequestValidationError):
        await update_event(db, OWNER_P, event.id, patch(got, extra={"room": "1"}), locales=LOCALES)
    await db.refresh(got)  # the refused write rolled its savepoint back
    again = await update_event(
        db, OWNER_P, event.id, patch(got, extra=dict(got.extra)), locales=LOCALES
    )
    await db.refresh(again)
    assert again.revision == 2  # the same value writes nothing


async def test_patch_without_extra_leaves_it_untouched(db):
    event = await make(db, OWNER_P, await cal(db), type="acme:talk", extra={"speaker": "Ada"})
    before = json.dumps(event.extra)
    got = await update_event(
        db, OWNER_P, event.id, patch(event, venue_name="Hall"), locales=LOCALES
    )
    assert json.dumps(got.extra) == before and got.venue_name == "Hall"


def test_patch_type_immutable():
    with pytest.raises(ImmutableField):
        EventPatch.model_validate({"expected_revision": 1, "type": "acme:talk"})


def test_patch_extra_cannot_be_null():
    with pytest.raises(ValueError):
        EventPatch(expected_revision=1, extra=None)


async def _raw_text(db, event_id) -> str | None:
    if not USING_POSTGRES:
        return None
    row = await db.execute(
        text("SELECT extra::text FROM events_event WHERE id = :i"), {"i": event_id}
    )
    return row.scalar_one()


async def test_uninstalled_type_bytes_survive_every_path(db):
    event = await make(db, OWNER_P, await cal(db), rrule="FREQ=WEEKLY;BYDAY=WE")
    event.type, event.extra = GONE, RAW
    await db.flush()
    wanted = json.dumps(RAW)
    raw_before = await _raw_text(db, event.id)

    async def check(step):
        await db.refresh(event)
        assert event.type == GONE, step
        assert json.dumps(event.extra) == wanted, step
        if raw_before is not None:
            assert await _raw_text(db, event.id) == raw_before, step

    rev = lambda: event.revision  # noqa: E731
    await update_event(db, OWNER_P, event.id, patch(event, venue_name="Hall"), locales=LOCALES)
    await check("patch")
    second = datetime(2026, 7, 8, 8, tzinfo=UTC)
    await set_override(
        db,
        OWNER_P,
        event.id,
        OverrideIn(expected_revision=rev(), original_start=second, kind="skipped"),
    )
    await check("override set")
    (row,) = (await db.execute(select(OccurrenceOverride))).scalars().all()
    await db.refresh(event)
    await clear_override(db, OWNER_P, event.id, row.id, rev())
    await check("override clear")
    for action in ("submit", "approve", "unpublish"):
        await db.refresh(event)
        await transition(
            db,
            OWNER_P,
            event.id,
            action,
            expected=rev(),
            now=NOW,
            publish_at_local="2026-06-01T10:00" if action == "approve" else None,
        )
        await check(action)
    await db.refresh(event)
    await trash_event(db, OWNER_P, event.id, rev())
    await restore_event(db, OWNER_P, event.id, rev() + 0)
    await db.refresh(event)
    await check("trash and restore")
    snap = (await db.execute(select(Revision).where(Revision.event_id == event.id))).scalars().all()
    later = [r for r in snap if r.action != "created"]  # "created" predates the seeded extra
    assert later and all(r.snapshot["extra"] == RAW for r in later)
    fresh = revisions.snapshot(event, {}, [])
    assert fresh["extra"] == RAW


async def test_uninstalled_patch_with_extra_refused(db):
    event = await make(db, OWNER_P, await cal(db))
    event.type, event.extra = GONE, RAW
    await db.flush()
    with pytest.raises(TypeNotInstalled) as caught:
        await update_event(db, OWNER_P, event.id, patch(event, extra={"a": 1}), locales=LOCALES)
    assert caught.value.code == "type_not_installed"
    await db.refresh(event)
    assert event.revision == 1 and event.extra == RAW
    # every other field stays editable
    got = await update_event(
        db, OWNER_P, event.id, patch(event, venue_name="Hall"), locales=LOCALES
    )
    assert got.venue_name == "Hall" and got.extra == RAW
