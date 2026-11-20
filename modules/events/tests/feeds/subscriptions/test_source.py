"""External items in the occurrences read: bounded, indexed, expanded by the module's own rules,
and visible exactly as far as the calendar is."""

from __future__ import annotations

import re
from datetime import date
from zoneinfo import ZoneInfo

import pytest
from sm_events.calendar.occurrence import OccurrenceFilters
from sm_events.core import constants
from sm_events.core.access.public import ANONYMOUS
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.subscriptions import source as source_module
from sm_events.feeds.subscriptions import store
from sm_events.models import Visibility

from tests.support.access import principal
from tests.support.occurrences import OWNER, read, utc
from tests.support.sql_spy import Spy
from tests.support.subscriptions import ics, seed_calendar, seed_item, seed_subscription, vevent

KEY = re.compile(r"^[0-9a-f]{32}:[0-9a-f]{24}(:\d{8}T\d{6}Z)?$")
MARCH = (utc(2027, 3, 1), utc(2027, 4, 15))


async def _feed(db, sub, *events, tz="Europe/Vienna"):
    await store.store_feed(db, sub, calendar_tz=tz, body=ics(*events))
    await db.flush()


def _vienna(**extra):
    return vevent(
        **{
            "DTSTART;TZID=Europe/Vienna": "20270322T100000",
            "DTEND;TZID=Europe/Vienna": "20270322T110000",
            "RRULE": "FREQ=WEEKLY",
            **extra,
        }
    )


@pytest.fixture
async def cal(db):
    return await seed_calendar(db)


@pytest.fixture
async def sub(db, cal):
    return await seed_subscription(db, cal, label="Ext", color="#112233")


async def _titles(db, who=OWNER, window=MARCH, **kw):
    page = await read(db, who, *window, **kw)
    return page, [i for i in page.items if i.source == constants.SOURCE_SUBSCRIPTIONS]


async def test_one_off_and_series_in_window(db, sub):
    one_off = vevent(UID="o@x", DTSTART="20270310T090000Z", DTEND="20270310T100000Z")
    await _feed(db, sub, _vienna(UID="s@x"), one_off)
    _, items = await _titles(db)
    assert any(i.start == utc(2027, 3, 10, 9) for i in items)
    vienna = ZoneInfo("Europe/Vienna")
    series = [i.start.astimezone(vienna) for i in items if i.start.date() >= date(2027, 3, 22)]
    assert len(series) >= 4
    assert {start.hour for start in series} == {10}  # 10:00 local on both sides of 28 March
    assert {start.utcoffset().total_seconds() for start in series} == {3600, 7200}


async def test_overrides_applied(db, sub):
    master = _vienna(UID="s@x", SUMMARY="Weekly")
    exdate = ["EXDATE;TZID=Europe/Vienna:20270329T100000"]
    cancelled = vevent(
        **{
            "UID": "s@x",
            "RECURRENCE-ID;TZID=Europe/Vienna": "20270405T100000",
            "DTSTART;TZID=Europe/Vienna": "20270405T100000",
            "DTEND;TZID=Europe/Vienna": "20270405T110000",
            "STATUS": "CANCELLED",
            "SUMMARY": "Weekly",
        }
    )
    moved = vevent(
        **{
            "UID": "s@x",
            "RECURRENCE-ID;TZID=Europe/Vienna": "20270412T100000",
            "DTSTART;TZID=Europe/Vienna": "20270413T150000",
            "DTEND;TZID=Europe/Vienna": "20270413T160000",
            "SUMMARY": "Weekly",
        }
    )
    await _feed(db, sub, [*master[:-1], *exdate, master[-1]], cancelled, moved)
    _, items = await _titles(db)
    by_day = {i.start.date().isoformat(): i for i in items}
    assert "2027-03-29" not in by_day  # EXDATE
    assert by_day["2027-04-05"].status == "cancelled"
    assert "2027-04-12" not in by_day
    assert by_day["2027-04-13"].start == utc(2027, 4, 13, 13)
    assert by_day["2027-04-13"].key.endswith(":20270412T080000Z")  # the original start, UTC


async def test_moved_into_window_from_outside(db, sub):
    first = vevent(
        UID="s@x", RRULE="FREQ=WEEKLY;COUNT=3", DTSTART="20270105T100000Z", DTEND="20270105T110000Z"
    )
    moved = vevent(
        **{
            "UID": "s@x",
            "RECURRENCE-ID": "20270112T100000Z",
            "DTSTART": "20270309T100000Z",
            "DTEND": "20270309T110000Z",
        }
    )
    await _feed(db, sub, first, moved)
    _, items = await _titles(db)
    assert [i.start for i in items] == [utc(2027, 3, 9, 10)]


async def test_expansion_stops_at_window(db, sub, monkeypatch):
    await _feed(
        db,
        sub,
        vevent(UID="d@x", RRULE="FREQ=DAILY", DTSTART="20270101T100000Z", DTEND="20270101T110000Z"),
    )
    seen = []
    real = source_module.instances

    def spy(**kw):
        seen.append(kw["window_end"])
        return real(**kw)

    monkeypatch.setattr(source_module, "instances", spy)
    start, end = utc(2027, 3, 1), utc(2028, 2, 29)  # 365 days
    _, items = await _titles(db, window=(start, end))
    assert seen == [end]
    assert len(items) == 365


async def test_cap_reports_truncated(db, sub):
    for n in range(constants.MAX_OCCURRENCES + 50):
        await seed_item(
            db, sub, f"u{n}", utc(2027, 3, 1, 0) + (n * (utc(2027, 3, 20) - utc(2027, 3, 1)) / 2100)
        )
    await db.flush()
    page, _ = await _titles(db)
    assert len(page.items) == constants.MAX_OCCURRENCES and page.truncated is True


async def test_anonymous_sees_only_public_subscriptions_and_never_private_class(db):
    cal = await seed_calendar(db, "open", visibility=Visibility.PUBLIC)
    hidden = await seed_subscription(db, cal, label="Hidden", public=False)
    shown = await seed_subscription(db, cal, label="Shown", public=True)
    await seed_item(db, hidden, "h", utc(2027, 3, 10), title="HiddenOne")
    await seed_item(db, shown, "p", utc(2027, 3, 11), title="PublicOne")
    await seed_item(db, shown, "x", utc(2027, 3, 12), title="Secret", private_class=True)
    await db.flush()
    _, anon = await _titles(db, ANONYMOUS)
    assert [i.title for i in anon] == ["PublicOne"]
    _, signed = await _titles(db)
    assert {i.title for i in signed} == {"HiddenOne", "PublicOne", "Secret"}


async def test_calendar_visibility_is_the_rule(db, sub):
    await seed_item(db, sub, "a", utc(2027, 3, 10))
    await db.flush()
    stranger = principal("stranger", "events.view")
    assert (await _titles(db, stranger))[1] == []  # a private calendar the stranger cannot see
    assert len((await _titles(db))[1]) == 1


async def test_paused_error_disabled_still_shown_and_deleted_hidden(db, cal):
    states = {}
    for state in ("paused", "error", "disabled", "ok"):
        s = await seed_subscription(db, cal, label=state, status=state)
        await seed_item(db, s, state, utc(2027, 3, 10), title=state)
        states[state] = s
    gone = await seed_subscription(db, cal, label="gone", is_deleted=True)
    await seed_item(db, gone, "gone", utc(2027, 3, 10), title="gone")
    await db.flush()
    _, items = await _titles(db)
    assert {i.title for i in items} == {"paused", "error", "disabled", "ok"}


async def test_fields(db, sub):
    await seed_item(
        db, sub, "uid-1", utc(2027, 3, 10, 9), title="Hello", url="https://a.example/x",
        location="Room 4",
    )  # fmt: skip
    await seed_item(
        db,
        sub,
        "uid-2",
        utc(2027, 3, 11, 9),
        all_day=True,
        timezone="Europe/Vienna",
        starts_at=utc(2027, 3, 10, 23),
        ends_at=utc(2027, 3, 11, 23),
        span_start=utc(2027, 3, 10, 23),
        span_end=utc(2027, 3, 11, 23),
        title="Day",
    )
    await db.flush()
    _, items = await _titles(db)
    one = next(i for i in items if i.title == "Hello")
    assert (one.origin_label, one.color, one.editable, one.url) == (
        "Ext",
        "#112233",
        False,
        "https://a.example/x",
    )
    assert one.location == "Room 4"  # the stored place travels with the entry
    assert (one.event_id, one.type, one.source, one.calendar_id) == (
        None,
        "event",
        "subscriptions",
        sub.calendar_id,
    )
    assert KEY.match(one.key) and one.original_start is None
    day = next(i for i in items if i.title == "Day")
    assert (day.start_date.isoformat(), day.end_date.isoformat()) == ("2027-03-11", "2027-03-12")


async def test_colour_falls_back_to_the_calendars(db, cal):
    plain = await seed_subscription(db, cal, color=None)
    await seed_item(db, plain, "a", utc(2027, 3, 10))
    await db.flush()
    _, items = await _titles(db)
    assert items[0].color == cal.color


async def test_filters_narrow(db, sub, cal):
    await seed_item(db, sub, "a", utc(2027, 3, 10))
    await db.flush()
    assert (
        len((await _titles(db, filters=OccurrenceFilters(sources=frozenset({"subscriptions"}))))[1])
        == 1
    )
    assert (await _titles(db, filters=OccurrenceFilters(sources=frozenset({"events"}))))[1] == []
    assert (await _titles(db, filters=OccurrenceFilters(types=frozenset({"other"}))))[1] == []
    assert (await _titles(db, filters=OccurrenceFilters(category_ids=frozenset({cal.id}))))[1] == []
    assert (await _titles(db, filters=OccurrenceFilters(event_ids=frozenset({cal.id}))))[1] == []
    assert (await _titles(db, filters=OccurrenceFilters(calendar_ids=frozenset({cal.id}))))[1] != []
    other = await seed_calendar(db, "other")
    assert (await _titles(db, filters=OccurrenceFilters(calendar_ids=frozenset({other.id}))))[
        1
    ] == []


@pytest.mark.unbound_tenant
async def test_other_tenant_isolated(db):
    with tenant_scope("acme"):
        theirs = await seed_subscription(db, await seed_calendar(db, "acme-cal"))
        await seed_item(db, theirs, "a", utc(2027, 3, 10), title="Theirs")
        await db.commit()
    with tenant_scope("default"):
        page = await read(db, OWNER, *MARCH)
    assert [i for i in page.items if i.source == "subscriptions"] == []


async def test_a_fixed_number_of_statements(db_state, db, cal):
    subs = [await seed_subscription(db, cal, label=f"s{n}") for n in range(5)]
    for index, s in enumerate(subs):
        for n in range(20):
            await seed_item(db, s, f"u{index}-{n}", utc(2027, 3, 1 + n % 20))
    await db.flush()
    await db.commit()
    with Spy(db_state) as many:
        await read(db, OWNER, *MARCH)
    for s in subs[1:]:
        s.is_deleted = True
    await db.commit()
    with Spy(db_state) as few:
        await read(db, OWNER, *MARCH)
    assert len(many.seen) == len(few.seen) <= 12
