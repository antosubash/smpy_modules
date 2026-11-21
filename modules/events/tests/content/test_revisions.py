"""History rows: snapshot contents, pruning and the note."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from sm_events.content import revisions
from sm_events.content.revisions import (
    EVENT_COLUMNS,
    get_revision,
    list_revisions,
    record,
    snapshot,
)
from sm_events.core import constants
from sm_events.core.errors import NotFound
from sm_events.models import OccurrenceOverride, Revision
from sqlalchemy import inspect, select

from tests.support.access import seed_calendars
from tests.support.calendars import seed_event


async def an_event(db, **fields):
    return await seed_event(db, (await seed_calendars(db))["I"], **fields)


def test_snapshot_columns_are_the_listed_ones():
    assert set(EVENT_COLUMNS) == {
        "uid", "calendar_id", "parent_id", "type", "status", "cancelled", "all_day",
        "starts_at", "ends_at", "timezone", "rrule", "recurrence_until", "attendance_mode",
        "venue_name", "address", "online_url", "latitude", "longitude", "category_id",
        "organiser", "image", "registration_url", "extra", "revision", "publish_at",
        "published_at",
        # PR 9: registration settings are part of an event's history.
        "registration_mode", "registration_provider", "registration_target",
        "registration_capacity", "registration_opens_at", "registration_closes_at",
        "registration_show_seats", "registration_reminder_minutes",
    }  # fmt: skip


async def test_snapshot_fields(db):
    event = await an_event(db, title="Hello", venue_name="Hall")
    db.add(
        OccurrenceOverride(
            event_id=event.id,
            original_start=datetime(2026, 7, 8, 10, tzinfo=UTC),
            kind="moved",
            starts_at=datetime(2026, 7, 9, 10, tzinfo=UTC),
            ends_at=datetime(2026, 7, 9, 11, tzinfo=UTC),
            note="n",
        )
    )
    await db.flush()
    row = await record(db, event, action="created", actor="u")
    snap = row.snapshot
    assert set(snap) == {*EVENT_COLUMNS, "texts", "overrides"}
    json.dumps(snap)  # JSON-safe
    assert snap["venue_name"] == "Hall" and snap["status"] == "draft"
    assert snap["texts"]["en"]["title"] == "Hello"
    assert set(snap["texts"]["en"]) == set(revisions._TEXT_FIELDS)
    assert snap["overrides"] == [
        {
            "original_start": "2026-07-08T10:00:00+00:00",
            "kind": "moved",
            "starts_at": "2026-07-09T10:00:00+00:00",
            "ends_at": "2026-07-09T11:00:00+00:00",
            "note": "n",
        }
    ]
    assert snapshot(event, {}, [])["texts"] == {}


async def test_snapshot_preserves_extra(db):
    event = await an_event(db, extra={"x": 1, "nested": {"a": [1, 2]}})
    row = await record(db, event, action="created", actor=None)
    assert row.snapshot["extra"] == {"x": 1, "nested": {"a": [1, 2]}}
    assert row.actor is None and row.number == 1


async def test_an_unknown_action_is_a_programming_error(db):
    event = await an_event(db)
    with pytest.raises(ValueError, match="unknown revision action"):
        await record(db, event, action="renamed", actor=None)
    assert {"created", "trashed", "restored", "published_scheduled"} <= set(
        constants.REVISION_ACTIONS
    )


async def test_prune_keeps_100(db):
    event = await an_event(db)
    for number in range(1, 106):
        event.revision = number
        await record(db, event, action="updated", actor="u")
    numbers = sorted(
        (await db.execute(select(Revision.number).where(Revision.event_id == event.id))).scalars()
    )
    assert numbers == list(range(6, 106))
    assert constants.REVISIONS_KEPT == 100


async def test_prune_is_per_event(db):
    cal = (await seed_calendars(db))["I"]
    one, two = await seed_event(db, cal), await seed_event(db, cal)
    for event in (one, two):
        await record(db, event, action="created", actor=None)
    for number in range(2, 104):
        one.revision = number
        await record(db, one, action="updated", actor=None)
    assert len(await list_revisions(db, two.id)) == 1


async def test_note_stored(db):
    event = await an_event(db)
    row = await record(db, event, action="rejected", actor="u", note="too vague")
    assert (await get_revision(db, event.id, 1)).note == "too vague" and row.note == "too vague"


async def test_list_newest_first_without_snapshots(db, db_state):
    event = await an_event(db)
    for number in (1, 2, 3):
        event.revision = number
        await record(db, event, action="updated", actor="u")
    await db.commit()
    async with db_state.session_factory() as fresh:
        rows = await list_revisions(fresh, event.id)
        assert [r.number for r in rows] == [3, 2, 1]
        assert "snapshot" in inspect(rows[0]).unloaded


async def test_get_revision_missing(db):
    event = await an_event(db)
    with pytest.raises(NotFound):
        await get_revision(db, event.id, 7)
    with pytest.raises(NotFound):
        await get_revision(db, uuid.uuid4(), 1)
