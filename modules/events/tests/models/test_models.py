"""The eight tables: tenant ownership, unique keys, foreign keys and defaults."""

from __future__ import annotations

import pytest
from sm_events.core.clock import utcnow
from sm_events.core.tenancy import tenant_scope
from sm_events.models import (
    Base,
    Calendar,
    CalendarRedirect,
    Event,
    EventText,
    Visibility,
)
from sqlalchemy import Index, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError

TABLES = {
    "events_calendar",
    "events_event",
    "events_event_text",
    "events_occurrence_override",
    "events_category",
    "events_revision",
    "events_redirect",
    "events_calendar_redirect",
    "events_feed_token",
    "events_import",
    "events_import_item",
}


def test_every_table_is_tenant_owned():
    assert {t.name for t in Base.metadata.sorted_tables} == TABLES
    for table in Base.metadata.sorted_tables:
        assert "tenant_id" in table.c, table.name


ACROSS_TENANTS = {"uq_events_feed_token_hash"}
"""The one unique key that deliberately does not lead with ``tenant_id``: a private feed's
token is looked up by its hash before any tenant is known, so the hash is unique install-wide."""


def test_tenant_scoped_uniques_lead_with_tenant():
    seen = 0
    exempt = set()
    for table in Base.metadata.sorted_tables:
        for item in table.constraints | table.indexes:
            unique = isinstance(item, UniqueConstraint) or (isinstance(item, Index) and item.unique)
            if not unique or item.__class__.__name__ == "PrimaryKeyConstraint":
                continue
            if item.name in ACROSS_TENANTS:
                exempt.add(item.name)
                continue
            seen += 1
            assert next(iter(item.columns)).name == "tenant_id", (table.name, item.name)
    assert seen >= 7
    assert exempt == ACROSS_TENANTS


async def _calendar(db, slug="team", **kwargs) -> Calendar:
    cal = Calendar(slug=slug, name=slug.title(), owner_id="o", **kwargs)
    db.add(cal)
    await db.flush()
    return cal


async def test_calendar_slug_unique_per_tenant(db):
    await _calendar(db)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await _calendar(db)


@pytest.mark.unbound_tenant
async def test_same_slug_in_another_tenant_is_accepted(db):
    with tenant_scope("a"):
        await _calendar(db)
    with tenant_scope("b"):
        other = await _calendar(db)
    assert other.tenant_id == "b"


async def test_trashed_calendar_keeps_its_slug(db):
    cal = await _calendar(db)
    cal.is_deleted = True
    cal.deleted_at = utcnow()
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await _calendar(db)


async def _event(db, cal) -> Event:
    event = Event(
        uid="u1",
        calendar_id=cal.id,
        starts_at=utcnow(),
        ends_at=utcnow(),
        timezone="UTC",
    )
    db.add(event)
    await db.flush()
    return event


async def test_text_slug_unique_per_locale(db):
    event = await _event(db, await _calendar(db))
    db.add(EventText(event_id=event.id, locale="en", slug="x", title="X"))
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(EventText(event_id=event.id, locale="en", slug="x", title="Y"))
            await db.flush()
    other = await _event_with_uid(db, event.calendar_id, "u2")
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(EventText(event_id=other.id, locale="en", slug="x", title="Z"))
            await db.flush()
    db.add(EventText(event_id=other.id, locale="de", slug="x", title="Z"))
    await db.flush()


async def _event_with_uid(db, calendar_id, uid) -> Event:
    event = Event(
        uid=uid, calendar_id=calendar_id, starts_at=utcnow(), ends_at=utcnow(), timezone="UTC"
    )
    db.add(event)
    await db.flush()
    return event


def test_foreign_keys():
    def ondelete(table: str, column: str) -> str | None:
        (fk,) = Base.metadata.tables[table].c[column].foreign_keys
        return fk.ondelete

    assert ondelete("events_event", "category_id") == "SET NULL"
    assert ondelete("events_event", "calendar_id") == "CASCADE"
    assert ondelete("events_event", "parent_id") == "CASCADE"
    assert ondelete("events_calendar_redirect", "calendar_id") == "CASCADE"
    for table in (
        "events_event_text",
        "events_occurrence_override",
        "events_revision",
        "events_redirect",
    ):
        assert ondelete(table, "event_id") == "CASCADE", table


async def test_defaults(db):
    event = await _event(db, await _calendar(db))
    await db.refresh(event)
    assert event.status == "draft"
    assert event.revision == 1
    assert event.type == "event"
    assert event.extra == {}
    assert event.cancelled is False and event.all_day is False
    assert event.attendance_mode == "in_person"


async def test_calendar_defaults(db):
    cal = await _calendar(db)
    assert cal.visibility == Visibility.PRIVATE == "private"
    assert cal.color == "#2563eb"
    assert cal.default_timezone == "UTC"
    assert cal.sources == []


async def test_revision_note_nullable(db):
    from sm_events.models import Revision

    event = await _event(db, await _calendar(db))
    db.add(Revision(event_id=event.id, number=1, action="created"))
    db.add(Revision(event_id=event.id, number=2, action="rejected", note="x" * 1000))
    await db.flush()
    rows = (await db.execute(select(Revision).order_by(Revision.number))).scalars().all()
    assert rows[0].note is None
    assert rows[1].note == "x" * 1000


async def test_calendar_redirect_unique(db):
    cal = await _calendar(db)
    db.add(CalendarRedirect(calendar_id=cal.id, old_slug="old"))
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(CalendarRedirect(calendar_id=cal.id, old_slug="old"))
            await db.flush()


@pytest.mark.unbound_tenant
async def test_calendar_redirect_same_slug_in_another_tenant(db):
    with tenant_scope("a"):
        cal_a = await _calendar(db, "a-cal")
        db.add(CalendarRedirect(calendar_id=cal_a.id, old_slug="old"))
        await db.flush()
    with tenant_scope("b"):
        cal_b = await _calendar(db, "b-cal")
        db.add(CalendarRedirect(calendar_id=cal_b.id, old_slug="old"))
        await db.flush()
        rows = (await db.execute(select(CalendarRedirect))).scalars().all()
    assert [(r.tenant_id, r.old_slug) for r in rows] == [("b", "old")]
