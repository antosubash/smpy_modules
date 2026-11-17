"""A lost rename race rolls back only the attempted calendar change."""

from __future__ import annotations

import pytest
from sm_events.calendar import calendars
from sm_events.core.errors import SlugTaken
from sm_events.models import Calendar
from sm_events.web.schemas.calendars import CalendarCreate, CalendarPatch
from sqlmodel import select

from tests.support.access import principal


async def test_rename_race_keeps_transaction_usable(db, monkeypatch):
    who = principal("o", "events.view", "events.edit")
    taken = await calendars.create_calendar(
        db, who, CalendarCreate(name="Taken", slug="taken"), default_tz="UTC"
    )
    other = await calendars.create_calendar(
        db, who, CalendarCreate(name="Other", slug="other"), default_tz="UTC"
    )

    async def missed_collision(*_args, **_kwargs):
        return False

    # The pre-check misses the collision, so the unique index has to catch it.
    monkeypatch.setattr(calendars, "slug_taken", missed_collision)
    with pytest.raises(SlugTaken):
        await calendars.update_calendar(db, other, CalendarPatch(slug=taken.slug, name="Changed"))

    rows = (await db.execute(select(Calendar).order_by(Calendar.slug))).scalars().all()
    assert [(row.slug, row.name) for row in rows] == [("other", "Other"), ("taken", "Taken")]
