"""Skip, cancel and move one occurrence of a series."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sm_events.content import bus
from sm_events.content.overrides import clear_override, set_override
from sm_events.contracts import events as contract
from sm_events.core.errors import (
    InvalidTimes,
    NotAnOccurrence,
    NotFound,
    NotRecurring,
    PublishRequired,
    Stale,
)
from sm_events.models import OccurrenceOverride, Revision
from sm_events.web.schemas.overrides import OverrideIn
from sqlalchemy import select

from tests.support.access import seed_calendars
from tests.support.calendars import seed_series
from tests.support.writes import OWNER, OWNER_P, SE, make, recording, revision_count

WEEKLY = "FREQ=WEEKLY;BYDAY=WE"
SECOND = datetime(2026, 7, 8, 8, tzinfo=UTC)  # the 2nd Wednesday, 10:00 Vienna


def body(rev=1, kind="skipped", original=SECOND, **kw) -> OverrideIn:
    return OverrideIn(expected_revision=rev, original_start=original, kind=kind, **kw)


async def series(db, status="draft", letter="I"):
    event = await make(db, OWNER_P, (await seed_calendars(db))[letter], rrule=WEEKLY)
    if status == "published":
        event.status, event.published_at = status, datetime.now(UTC)
        await db.flush()
    return event


async def rows(db, event):
    return (
        (
            await db.execute(
                select(OccurrenceOverride).where(OccurrenceOverride.event_id == event.id)
            )
        )
        .scalars()
        .all()
    )


async def test_override_on_one_off_refused(db):
    cal = (await seed_calendars(db))["I"]
    event = await make(db, OWNER, cal)
    with pytest.raises(NotRecurring):
        await set_override(db, OWNER, event.id, body())
    await db.refresh(event)
    assert event.revision == 1 and await rows(db, event) == []


async def test_override_not_an_occurrence(db):
    event = await series(db)
    for original in (datetime(2026, 7, 9, 8, tzinfo=UTC), datetime(2026, 7, 8, 8, 1, tzinfo=UTC)):
        with pytest.raises(NotAnOccurrence):
            await set_override(db, OWNER_P, event.id, body(original=original))
        await db.refresh(event)  # the refused write's savepoint expired it
    await db.refresh(event)
    assert event.revision == 1 and await rows(db, event) == []


def test_moved_needs_times_and_only_times():
    with pytest.raises(ValidationError):
        body(kind="moved")
    with pytest.raises(ValidationError):
        body(kind="moved", start="2026-07-08T11:00")
    with pytest.raises(ValidationError):
        body(kind="skipped", start="2026-07-08T11:00", end="2026-07-08T12:00")
    with pytest.raises(ValidationError):
        OverrideIn(
            expected_revision=1, original_start=SECOND, kind="moved",
            start="2026-07-08T11:00", end="2026-07-08T12:00", title="nope",
        )  # fmt: skip
    with pytest.raises(ValidationError):  # naive original_start
        OverrideIn(expected_revision=1, original_start="2026-07-08T08:00", kind="skipped")
    assert body(kind="moved", start="2026-07-08T11:00", end="2026-07-08T12:00").kind == "moved"


async def test_moved_stores_utc_span(db):
    event = await series(db)
    row = await set_override(
        db, OWNER_P, event.id,
        body(kind="moved", start="2026-07-09T11:00", end="2026-07-09T12:30", note="n"),
    )  # fmt: skip
    assert row.starts_at == datetime(2026, 7, 9, 9, tzinfo=UTC)
    assert row.ends_at == datetime(2026, 7, 9, 10, 30, tzinfo=UTC)
    assert row.original_start == SECOND and row.note == "n"


async def test_moved_duration_bound(db):
    event = await series(db)
    with pytest.raises(InvalidTimes) as raised:
        await set_override(
            db, OWNER_P, event.id,
            body(kind="moved", start="2026-07-08T10:00", end="2026-08-20T10:00"),
        )  # fmt: skip
    assert raised.value.code == "duration_too_long"
    await db.refresh(event)
    with pytest.raises(InvalidTimes) as raised:
        await set_override(
            db, OWNER_P, event.id,
            body(kind="moved", start="2026-07-08T10:00", end="2026-07-08T09:00"),
        )  # fmt: skip
    assert raised.value.code == "end_before_start"
    await db.refresh(event)
    assert event.revision == 1


async def test_second_write_replaces(db):
    event = await series(db)
    await set_override(db, OWNER_P, event.id, body(1, "skipped", note="a"))
    await set_override(db, OWNER_P, event.id, body(2, "cancelled", note="b"))
    (only,) = await rows(db, event)
    assert (only.kind, only.note) == ("cancelled", "b") and only.starts_at is None


async def test_clear(db):
    event = await series(db)
    row = await set_override(db, OWNER_P, event.id, body())
    with pytest.raises(NotFound):
        await clear_override(db, OWNER_P, event.id, row.id + 99, 2)
    await db.refresh(event)
    assert event.revision == 2  # the failed clear took nothing
    await clear_override(db, OWNER_P, event.id, row.id, 2)
    assert await rows(db, event) == [] and event.revision == 3
    actions = (
        (
            await db.execute(
                select(Revision.action)
                .where(Revision.event_id == event.id)
                .order_by(Revision.number)
            )
        )
        .scalars()
        .all()
    )
    assert actions == ["created", "override_set", "override_cleared"]


async def test_override_bumps_revision_and_records(db):
    event = await series(db)
    await set_override(db, OWNER_P, event.id, body(note="why"))
    assert event.revision == 2
    last = (
        await db.execute(
            select(Revision).where(Revision.event_id == event.id, Revision.number == 2)
        )
    ).scalar_one()
    assert last.action == "override_set"
    assert [o["kind"] for o in last.snapshot["overrides"]] == ["skipped"]


async def test_override_is_stale_guarded(db):
    event = await series(db)
    with pytest.raises(Stale):
        await set_override(db, OWNER_P, event.id, body(rev=4))
    assert await rows(db, event) == []


async def test_override_on_published_needs_publish(db):
    event = await series(db, status="published", letter="P")
    with pytest.raises(PublishRequired):
        await set_override(db, SE, event.id, body())
    assert await revision_count(db, event.id) == 1 and await rows(db, event) == []
    row = await set_override(db, OWNER_P, event.id, body())
    with pytest.raises(PublishRequired):
        await clear_override(db, SE, event.id, row.id, 2)


async def test_moved_emits_rescheduled_with_original_start(db):
    event = await series(db, status="published")
    rec = recording(db)
    await set_override(
        db, OWNER_P, event.id, body(kind="moved", start="2026-07-09T11:00", end="2026-07-09T12:00")
    )
    assert rec.seen == []
    await bus.commit(db)
    (got,) = rec.seen
    assert isinstance(got, contract.EventRescheduled)
    assert got.original_start == SECOND and got.rule_changed is False
    assert (got.old_start, got.old_end) == (SECOND, datetime(2026, 7, 8, 9, tzinfo=UTC))
    assert (got.new_start, got.new_end) == (
        datetime(2026, 7, 9, 9, tzinfo=UTC),
        datetime(2026, 7, 9, 10, tzinfo=UTC),
    )


async def test_cancelled_override_emits_cancelled_and_skip_nothing(db):
    event = await series(db, status="published")
    rec = recording(db)
    await set_override(db, OWNER_P, event.id, body(1, "skipped"))
    await set_override(db, OWNER_P, event.id, body(2, "cancelled"))
    await bus.commit(db)
    (got,) = rec.seen
    assert isinstance(got, contract.EventCancelled) and got.original_start == SECOND


async def test_draft_override_announces_nothing(db):
    event = await series(db)
    rec = recording(db)
    await set_override(db, OWNER_P, event.id, body(kind="cancelled"))
    await bus.commit(db)
    assert rec.seen == []


async def test_all_day_series_override(db):
    cal = (await seed_calendars(db))["I"]
    event = await seed_series(
        db, cal, "FREQ=WEEKLY;BYDAY=SU", "2026-03-22", "2026-03-22", all_day=True
    )
    original = datetime(2026, 3, 28, 23, tzinfo=UTC)  # Sunday 29 March, local midnight
    row = await set_override(
        db, OWNER_P, event.id, body(1, "moved", original, start="2026-03-30", end="2026-03-31")
    )
    assert row.starts_at == datetime(2026, 3, 29, 22, tzinfo=UTC)
