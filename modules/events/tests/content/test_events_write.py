"""Create and update: defaults, rights, bounds, the guard and bus events."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sm_events.content.events_write import create_event, update_event
from sm_events.content.texts import texts_of
from sm_events.core.errors import (
    Forbidden,
    ImmutableField,
    InvalidTimes,
    NotFound,
    PublishRequired,
    Stale,
    UnknownCategory,
    UnknownType,
)
from sm_events.models import Category, Event, Revision
from sm_events.web.schemas.events_in import EventPatch
from sqlalchemy import select

from tests.support.access import seed_calendars
from tests.support.calendars import seed_event
from tests.support.writes import (
    LOCALES,
    OWNER,
    OWNER_P,
    SE,
    VIEWER,
    create_body,
    make,
    revision_count,
    times,
)


async def cals(db):
    return await seed_calendars(db)


def patch(rev=1, **kw) -> EventPatch:
    return EventPatch(expected_revision=rev, **kw)


async def update(db, who, event, rev=None, **kw):
    return await update_event(
        db, who, event.id, patch(event.revision if rev is None else rev, **kw), locales=LOCALES
    )


async def test_create_defaults(db):
    cal = (await cals(db))["P"]
    event = await make(db, OWNER, cal)
    assert event.status == "draft" and event.revision == 1 and event.type == "event"
    assert event.uid.endswith("@simple-module-events")
    assert event.cancelled is False and event.extra == {}
    assert event.starts_at == datetime(2026, 7, 1, 8, tzinfo=UTC)
    rows = (await db.execute(select(Revision).where(Revision.event_id == event.id))).scalars().all()
    assert [(r.number, r.action, r.actor) for r in rows] == [(1, "created", "o")]
    assert rows[0].snapshot["texts"]["en"]["title"] == "Concert"
    assert (await texts_of(db, [event.id]))[event.id]["en"].slug == "concert"


async def test_create_needs_write_events(db):
    c = await cals(db)
    with pytest.raises(Forbidden):
        await make(db, VIEWER, c["I"])
    with pytest.raises(NotFound):
        await make(db, VIEWER, c["P"])
    assert (await make(db, SE, c["P"])).calendar_id == c["P"].id


async def test_failed_create_leaves_nothing(db):
    cal = (await cals(db))["I"]
    with pytest.raises(NotFound):
        await make(db, OWNER, cal, calendar_id=__import__("uuid").uuid4())
    from sm_events.core.errors import DefaultLocaleRequired

    with pytest.raises(DefaultLocaleRequired):
        await create_event(
            db, OWNER, create_body(cal, texts={"de": {"title": "x"}}), locales=LOCALES
        )
    assert (await db.execute(select(Event))).scalars().all() == []


async def test_unknown_type_and_category(db):
    cal = (await cals(db))["I"]
    with pytest.raises(UnknownType):
        await make(db, OWNER, cal, type="meeting")
    with pytest.raises(UnknownCategory):
        await make(db, OWNER, cal, category_id=__import__("uuid").uuid4())
    category = Category(slug="c", names={"en": "C"})
    db.add(category)
    await db.flush()
    assert (await make(db, OWNER, cal, category_id=category.id)).category_id == category.id


async def test_series_create_sets_recurrence_until(db):
    cal = (await cals(db))["I"]
    event = await make(db, OWNER, cal, rrule="freq=daily;count=3")
    assert event.rrule == "FREQ=DAILY;COUNT=3"
    assert event.recurrence_until == datetime(2026, 7, 3, 9, tzinfo=UTC)
    endless = await make(db, OWNER, cal, rrule="FREQ=WEEKLY;BYDAY=WE")
    assert endless.recurrence_until is None


async def test_series_duration_bound(db):
    cal = (await cals(db))["I"]
    body = {"times": times("2026-07-01T10:00", "2026-08-01T11:00"), "rrule": "FREQ=MONTHLY"}
    with pytest.raises(InvalidTimes) as raised:
        await make(db, OWNER, cal, **body)
    assert raised.value.code == "duration_too_long"
    await make(db, OWNER, cal, times=times("2026-07-01T10:00", "2026-08-01T11:00"))  # one-off: fine


async def test_patch_partial(db):
    cal = (await cals(db))["I"]
    event = await make(db, OWNER, cal, texts={"en": {"title": "A"}, "de": {"title": "B"}})
    before = {k: (v.title, v.slug) for k, v in (await texts_of(db, [event.id]))[event.id].items()}
    await update(db, OWNER, event, venue_name="Hall")
    assert event.venue_name == "Hall" and event.revision == 2
    after = {k: (v.title, v.slug) for k, v in (await texts_of(db, [event.id]))[event.id].items()}
    assert before == after
    assert await revision_count(db, event.id) == 2
    await update(db, OWNER, event, venue_name=None)
    assert event.venue_name is None


async def test_patch_texts_and_times(db):
    cal = (await cals(db))["I"]
    event = await make(db, OWNER, cal)
    await update(
        db, OWNER, event, times=times("2026-07-02T09:00", "2026-07-02T10:00"),
        texts={"de": {"title": "Konzert"}},
    )  # fmt: skip
    assert event.starts_at == datetime(2026, 7, 2, 7, tzinfo=UTC)
    assert set((await texts_of(db, [event.id]))[event.id]) == {"en", "de"}


async def test_patch_stale(db):
    cal = (await cals(db))["I"]
    event = await make(db, OWNER, cal)
    with pytest.raises(Stale) as raised:
        await update(db, OWNER, event, rev=7, venue_name="x")
    assert raised.value.current_revision == 1
    await db.refresh(event)
    assert event.revision == 1 and event.venue_name is None
    assert await revision_count(db, event.id) == 1


async def test_failed_patch_rolls_the_claim_back(db):
    cal = (await cals(db))["I"]
    event = await make(db, OWNER, cal)
    with pytest.raises(InvalidTimes):
        await update(db, OWNER, event, times=times("2026-07-01T10:00", "2026-07-01T09:00"))
    await db.refresh(event)
    assert event.revision == 1
    assert await revision_count(db, event.id) == 1
    await update(db, OWNER, event, venue_name="ok")  # the session is usable
    assert event.revision == 2


def test_immutable_fields():
    import uuid

    for field, value in (("calendar_id", uuid.uuid4()), ("parent_id", None), ("type", "event")):
        with pytest.raises(ImmutableField):
            EventPatch(expected_revision=1, **{field: value})


async def test_extra_preserved(db):
    cal = (await cals(db))["I"]
    event = await seed_event(db, cal, extra={"x": 1})
    await update(db, OWNER, event, venue_name="Hall")
    await db.refresh(event)
    assert event.extra == {"x": 1}
    snap = (await db.execute(select(Revision).where(Revision.event_id == event.id))).scalar_one()
    assert snap.snapshot["extra"] == {"x": 1}


async def test_viewer_cannot_patch_and_invisible_is_404(db):
    c = await cals(db)
    event = await seed_event(db, c["P"])
    with pytest.raises(NotFound):
        await update(db, VIEWER, event, venue_name="x")
    draft = await seed_event(db, c["I"])
    with pytest.raises(NotFound):  # a draft is invisible to a viewer
        await update(db, VIEWER, draft, venue_name="x")
    live = await seed_event(db, c["I"], status="published")
    with pytest.raises(Forbidden):  # visible, but not writable
        await update(db, VIEWER, live, venue_name="x")


async def test_locked_event_needs_publish(db):
    cal = (await cals(db))["P"]
    published = await seed_event(db, cal, status="published", published_at=datetime.now(UTC))
    scheduled = await seed_event(
        db, cal, status="draft", publish_at=datetime(2030, 1, 1, tzinfo=UTC)
    )
    for event in (published, scheduled):
        for changes in (
            {"venue_name": "x"},
            {"cancelled": True},
            {"times": times("2026-07-05T10:00", "2026-07-05T11:00")},
            {"texts": {"en": {"title": "new"}}},
        ):
            with pytest.raises(PublishRequired):
                await update(db, SE, event, **changes)
        await db.refresh(event)
        assert event.revision == 1 and await revision_count(db, event.id) == 0
    await update(db, OWNER_P, published, venue_name="ok")
    assert published.revision == 2


async def test_online_attendance_and_geo_fields(db):
    cal = (await cals(db))["I"]
    event = await make(
        db, OWNER, cal, attendance_mode="hybrid", online_url="https://meet.example/x",
        latitude=48.2, longitude=16.37, organiser="Org",
    )  # fmt: skip
    assert event.attendance_mode == "hybrid" and event.latitude == 48.2
