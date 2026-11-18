"""What the occurrences read shows to whom: drafts, editable and the editor URL."""

from __future__ import annotations

import pytest
from sm_events.calendar.occurrence import OccurrenceFilters

from tests.support.access import principal, seed_calendars
from tests.support.calendars import seed_event, seed_series
from tests.support.occurrences import OWNER, read, utc

V, E, P, M = "events.view", "events.edit", "events.publish", "events.manage"
VIENNA = "Europe/Vienna"
ALL = OccurrenceFilters()


@pytest.mark.parametrize(
    "who",
    [
        principal("v", V),
        principal("sv", V),
        principal(None),
        principal("o"),  # lost events.view
    ],
    ids=["V", "SV", "A", "O-"],
)
async def test_drafts_never_reach_viewers(db, who):
    cals = await seed_calendars(db)
    for letter, cal in cals.items():
        await seed_event(db, cal, title=f"{letter}-draft", status="draft")
        await seed_event(db, cal, title=f"{letter}-review", status="in_review")
        await seed_event(
            db, cal, title=f"{letter}-scheduled", status="draft", publish_at=utc(2030, 1, 1)
        )
        await seed_event(db, cal, title=f"{letter}-published", status="published")
        await seed_series(
            db,
            cal,
            "FREQ=DAILY;COUNT=2",
            "2026-07-01T10:00",
            "2026-07-01T11:00",
            title=f"{letter}-series-draft",
            status="draft",
        )
    for flag in (True, False):
        page = await read(
            db, who, utc(2026, 6, 1), utc(2026, 8, 1), OccurrenceFilters(include_unpublished=flag)
        )
        assert page.items
        assert {o.event_status for o in page.items} == {"published"}
        assert all(o.title.endswith("-published") for o in page.items)


async def test_writers_see_drafts_with_status(db):
    cals = await seed_calendars(db)
    await seed_event(db, cals["P"], title="draft", status="draft")
    await seed_event(db, cals["P"], title="pub", status="published")
    se = principal("se", V)
    page = await read(db, se, utc(2026, 7, 1), utc(2026, 7, 2))
    got = {o.title: o for o in page.items}
    assert got["draft"].event_status == "draft" and got["draft"].editable
    assert not got["pub"].editable and got["pub"].url is None  # locked, and SE cannot publish
    hidden = await read(
        db, se, utc(2026, 7, 1), utc(2026, 7, 2), OccurrenceFilters(include_unpublished=False)
    )
    assert [o.title for o in hidden.items] == ["pub"]


async def test_editable_and_url(db):
    cals = await seed_calendars(db)
    event = await seed_event(db, cals["P"], status="published")
    page = await read(db, OWNER, utc(2026, 7, 1), utc(2026, 7, 2))
    assert page.items[0].editable
    assert page.items[0].url == f"/admin/events/edit/{event.id}"
    plain_owner = principal("o", V, E)  # owner without events.publish
    got = (await read(db, plain_owner, utc(2026, 7, 1), utc(2026, 7, 2))).items[0]
    assert not got.editable and got.url is None
    viewer = principal("v", V)
    got = (await read(db, viewer, utc(2026, 7, 1), utc(2026, 7, 2))).items
    assert got == []  # the calendar is private
