"""The occurrences read over rows inserted directly."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sm_events.calendar.occurrence import OccurrenceFilters
from sm_events.calendar.occurrences import occurrences
from sm_events.models import Category, OccurrenceOverride

from tests.support.access import principal, seed_calendars
from tests.support.calendars import seed_event, seed_series

V, E, P, M = "events.view", "events.edit", "events.publish", "events.manage"
VIENNA = "Europe/Vienna"
ALL = OccurrenceFilters()


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


async def read(db, who, start, end, filters=ALL, locale="en"):
    return await occurrences(
        db,
        tenant_id="default",
        viewer=who,
        start=start,
        end=end,
        filters=filters,
        default_locale=locale,
    )


OWNER = principal("o", V, E, P)


async def test_one_off_and_series_merge_sorted(db):
    cals = await seed_calendars(db)
    cal = cals["I"]
    await seed_event(db, cal, title="late", status="published", starts_at=utc(2026, 7, 8, 12))
    await seed_event(db, cal, title="early", status="published", starts_at=utc(2026, 7, 6, 6))
    await seed_series(
        db,
        cal,
        "FREQ=WEEKLY;BYDAY=MO",
        "2026-07-06T10:00",
        "2026-07-06T11:00",
        title="weekly",
        status="published",
    )
    page = await read(db, OWNER, utc(2026, 7, 1), utc(2026, 7, 20))
    assert [(o.title, o.start) for o in page.items] == [
        ("early", utc(2026, 7, 6, 6)),
        ("weekly", utc(2026, 7, 6, 8)),
        ("late", utc(2026, 7, 8, 12)),
        ("weekly", utc(2026, 7, 13, 8)),
    ]
    assert not page.truncated
    keys = [(o.start, o.end, o.source, o.key) for o in page.items]
    assert keys == sorted(keys)


async def test_key_shapes(db):
    cals = await seed_calendars(db)
    one = await seed_event(db, cals["I"], status="published")
    many = await seed_series(
        db, cals["I"], "FREQ=DAILY", "2026-07-02T10:00", "2026-07-02T11:00", status="published"
    )
    page = await read(db, OWNER, utc(2026, 7, 1), utc(2026, 7, 4))
    keys = {o.key for o in page.items}
    assert str(one.id) in keys
    assert f"{many.id}:20260702T080000Z" in keys
    assert f"{many.id}:20260703T080000Z" in keys
    single = next(o for o in page.items if o.event_id == one.id)
    assert single.original_start is None and single.source == "events"
    assert next(o for o in page.items if o.key.endswith("20260702T080000Z")).original_start == utc(
        2026, 7, 2, 8
    )


async def test_read_across_dst(db):
    cals = await seed_calendars(db)
    await seed_series(
        db,
        cals["I"],
        "FREQ=WEEKLY;BYDAY=MO",
        "2026-03-16T10:00",
        "2026-03-16T11:00",
        status="published",
    )
    page = await read(db, OWNER, utc(2026, 3, 15), utc(2026, 4, 6))
    assert [o.start for o in page.items] == [
        utc(2026, 3, 16, 9),
        utc(2026, 3, 23, 9),
        utc(2026, 3, 30, 8),
    ]


async def test_all_day_range_edges(db):
    cals = await seed_calendars(db)
    await seed_series(
        db,
        cals["I"],
        "FREQ=YEARLY",
        "2026-03-29",
        "2026-03-29",
        all_day=True,
        status="published",
        title="short day",
    )
    inside = await read(db, OWNER, utc(2026, 3, 28, 23, 30), utc(2026, 3, 29, 0, 30))
    assert len(inside.items) == 1
    got = inside.items[0]
    assert got.all_day and (got.start_date, got.end_date) == (date(2026, 3, 29), date(2026, 3, 30))
    assert got.end - got.start == timedelta(hours=23)
    before = await read(db, OWNER, utc(2026, 3, 28), utc(2026, 3, 28, 23))
    assert before.items == []
    after = await read(db, OWNER, utc(2026, 3, 29, 22), utc(2026, 3, 30))
    assert after.items == []
    single = await seed_event(
        db,
        cals["I"],
        all_day=True,
        status="published",
        timezone=VIENNA,
        starts_at=utc(2026, 3, 28, 23),
        ends_at=utc(2026, 3, 29, 22),
    )
    page = await read(db, OWNER, utc(2026, 3, 28, 23, 30), utc(2026, 3, 29, 0, 30))
    assert single.id in {o.event_id for o in page.items}


async def _override(db, event, original_start, kind, **fields):
    db.add(
        OccurrenceOverride(event_id=event.id, original_start=original_start, kind=kind, **fields)
    )
    await db.flush()


async def test_overrides_applied(db):
    cals = await seed_calendars(db)
    ev = await seed_series(
        db, cals["I"], "FREQ=DAILY", "2026-07-01T10:00", "2026-07-01T11:00", status="published"
    )
    await _override(db, ev, utc(2026, 7, 2, 8), "skipped")
    await _override(db, ev, utc(2026, 7, 3, 8), "cancelled")
    await _override(
        db,
        ev,
        utc(2026, 7, 4, 8),
        "moved",
        starts_at=utc(2026, 7, 4, 14),
        ends_at=utc(2026, 7, 4, 15),
    )
    page = await read(db, OWNER, utc(2026, 7, 1), utc(2026, 7, 6))
    by_day = {(o.start.day, o.start.hour): o for o in page.items}
    assert (2, 8) not in by_day  # skipped
    assert by_day[3, 8].status == "cancelled"
    assert (4, 8) not in by_day
    moved = by_day[4, 14]
    assert moved.key == f"{ev.id}:20260704T080000Z"  # keeps its original key
    assert moved.original_start == utc(2026, 7, 4, 8)
    assert by_day[1, 8].status == "confirmed" and by_day[5, 8].status == "confirmed"


async def test_moved_into_window_from_outside(db):
    cals = await seed_calendars(db)
    ev = await seed_series(
        db, cals["I"], "FREQ=WEEKLY", "2026-06-03T10:00", "2026-06-03T11:00", status="published"
    )
    # last month's instance moved into July
    await _override(
        db,
        ev,
        utc(2026, 6, 10, 8),
        "moved",
        starts_at=utc(2026, 7, 2, 9),
        ends_at=utc(2026, 7, 2, 10),
    )
    page = await read(db, OWNER, utc(2026, 7, 1), utc(2026, 7, 4))
    assert [o.start for o in page.items] == [utc(2026, 7, 1, 8), utc(2026, 7, 2, 9)]
    assert page.items[1].original_start == utc(2026, 6, 10, 8)


async def test_moved_into_window_from_an_ended_series(db):
    """The series ended before the window; its moved instance is still shown."""
    cals = await seed_calendars(db)
    ev = await seed_series(
        db,
        cals["I"],
        "FREQ=WEEKLY;COUNT=3",
        "2026-05-06T10:00",
        "2026-05-06T11:00",
        status="published",
    )
    await _override(
        db,
        ev,
        utc(2026, 5, 13, 8),
        "moved",
        starts_at=utc(2026, 7, 2, 9),
        ends_at=utc(2026, 7, 2, 10),
    )
    page = await read(db, OWNER, utc(2026, 7, 1), utc(2026, 7, 4))
    assert [o.start for o in page.items] == [utc(2026, 7, 2, 9)]


async def test_moved_out_of_window_disappears(db):
    cals = await seed_calendars(db)
    ev = await seed_series(
        db, cals["I"], "FREQ=DAILY", "2026-07-01T10:00", "2026-07-01T11:00", status="published"
    )
    await _override(
        db,
        ev,
        utc(2026, 7, 2, 8),
        "moved",
        starts_at=utc(2026, 8, 2, 9),
        ends_at=utc(2026, 8, 2, 10),
    )
    page = await read(db, OWNER, utc(2026, 7, 1), utc(2026, 7, 4))
    assert [o.start.day for o in page.items] == [1, 3]


async def test_cancelled_event_marks_all(db):
    cals = await seed_calendars(db)
    await seed_series(
        db,
        cals["I"],
        "FREQ=DAILY;COUNT=3",
        "2026-07-01T10:00",
        "2026-07-01T11:00",
        status="published",
        cancelled=True,
    )
    page = await read(db, OWNER, utc(2026, 7, 1), utc(2026, 7, 10))
    assert len(page.items) == 3 and {o.status for o in page.items} == {"cancelled"}


async def test_title_fallback_and_lang(db):
    cals = await seed_calendars(db)
    await seed_event(db, cals["I"], title="English", locale="en", status="published")
    page = await read(db, OWNER, utc(2026, 7, 1), utc(2026, 7, 2), locale="en")
    de = await read(db, OWNER, utc(2026, 7, 1), utc(2026, 7, 2), OccurrenceFilters(locale="de"))
    assert (page.items[0].title, page.items[0].lang) == ("English", "en")
    assert (de.items[0].title, de.items[0].lang) == ("English", "en")


async def test_color_category_then_calendar(db):
    cals = await seed_calendars(db)
    cals["I"].color = "#111111"
    cat = Category(slug="c", names={"en": "C"}, color="#222222")
    plain = Category(slug="p", names={"en": "P"}, color=None)
    db.add_all([cat, plain])
    await db.flush()
    await seed_event(db, cals["I"], title="a", status="published", category_id=cat.id)
    await seed_event(db, cals["I"], title="b", status="published", category_id=plain.id)
    await seed_event(db, cals["I"], title="c", status="published")
    page = await read(db, OWNER, utc(2026, 7, 1), utc(2026, 7, 2))
    assert {o.title: o.color for o in page.items} == {
        "a": "#222222",
        "b": "#111111",
        "c": "#111111",
    }


async def test_filters(db):
    cals = await seed_calendars(db)
    cat = Category(slug="c", names={"en": "C"})
    db.add(cat)
    await db.flush()
    a = await seed_event(db, cals["I"], title="a", status="published", category_id=cat.id)
    b = await seed_event(db, cals["U"], title="b", status="published", type="meeting")
    window = (utc(2026, 7, 1), utc(2026, 7, 2))
    only_i = await read(
        db, OWNER, *window, OccurrenceFilters(calendar_ids=frozenset({cals["I"].id}))
    )
    assert {o.event_id for o in only_i.items} == {a.id}
    by_cat = await read(db, OWNER, *window, OccurrenceFilters(category_ids=frozenset({cat.id})))
    assert {o.event_id for o in by_cat.items} == {a.id}
    by_type = await read(db, OWNER, *window, OccurrenceFilters(types=frozenset({"meeting"})))
    assert {o.event_id for o in by_type.items} == {b.id}
    # an id the viewer cannot see matches nothing, and is not an error
    viewer = principal("v", V)
    hidden = await read(
        db, viewer, *window, OccurrenceFilters(calendar_ids=frozenset({cals["P"].id}))
    )
    assert hidden.items == []
    mixed = await read(
        db,
        viewer,
        *window,
        OccurrenceFilters(calendar_ids=frozenset({cals["P"].id, cals["I"].id})),
    )
    assert {o.event_id for o in mixed.items} == {a.id}


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


@pytest.mark.unbound_tenant
async def test_tenant_mismatch_raises(db):
    with pytest.raises(ValueError):
        await read(db, OWNER, utc(2026, 7, 1), utc(2026, 7, 2))


async def test_tenant_must_equal_the_bound_one(db):
    with pytest.raises(ValueError):
        await occurrences(
            db,
            tenant_id="b",
            viewer=OWNER,
            start=utc(2026, 7, 1),
            end=utc(2026, 7, 2),
            filters=ALL,
            default_locale="en",
        )
