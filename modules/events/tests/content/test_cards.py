"""Card assembly: a published public event as another module sees it."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sm_events.calendar.times import to_span
from sm_events.content.cards import EventCard, cards_for
from sm_events.core import locales
from sm_events.models import EventText, OccurrenceOverride
from sqlalchemy import update
from sqlmodel import col

from tests.support.access import seed_calendars
from tests.support.calendars import seed_event, seed_series

NOW = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
WEEKLY = ("FREQ=WEEKLY;BYDAY=WE", "2026-05-06T10:00", "2026-05-06T11:00")


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


async def _cal(db):
    return (await seed_calendars(db))["U"]


async def _card(db, event, locale=None, now=NOW) -> EventCard | None:
    cards = await cards_for(db, [event], tenant_id="default", locale=locale, now=now)
    assert len(cards) <= 1
    return cards[0] if cards else None


async def test_one_off_card_fields(db):
    cal = await _cal(db)
    event = await seed_event(
        db,
        cal,
        title="Open day",
        slug="open-day",
        status="published",
        starts_at=utc(2026, 7, 10, 8),
        timezone="Europe/Vienna",
        attendance_mode="hybrid",
        venue_name="Hall 1",
        address="Main St 2",
        image="https://cdn.example.com/a.png",
    )
    card = await _card(db, event)
    assert card == EventCard(
        id=event.id,
        title="Open day",
        summary="",
        starts_at=utc(2026, 7, 10, 8),
        ends_at=utc(2026, 7, 10, 9),
        all_day=False,
        start_date=None,
        end_date=None,
        timezone="Europe/Vienna",
        occurrence_start=None,
        attendance_mode="hybrid",
        venue_name="Hall 1",
        address="Main St 2",
        image_url="https://cdn.example.com/a.png",
        path="/events/open-day",
        ics_path="/events/open-day.ics",
        locale="en",
        cancelled=False,
    )


async def test_missing_optional_fields_are_empty_strings(db):
    cal = await _cal(db)
    event = await seed_event(db, cal, title="Bare", slug="bare", status="published")
    card = await _card(db, event)
    assert card is not None
    assert (card.summary, card.venue_name, card.address, card.image_url) == ("", "", "", "")


async def test_summary_and_a_non_web_image(db):
    cal = await _cal(db)
    event = await seed_event(
        db, cal, title="T", status="published", image="javascript:alert(1)", slug="t"
    )
    await db.execute(
        update(EventText)
        .where(col(EventText.event_id) == event.id)
        .values(summary="Bring a friend")
    )
    card = await _card(db, event)
    assert card is not None
    assert card.summary == "Bring a friend"
    assert card.image_url == ""  # the public page shows an image only as an http(s) link


async def test_card_is_frozen(db):
    cal = await _cal(db)
    event = await seed_event(db, cal, title="T", status="published", slug="t")
    card = await _card(db, event)
    assert card is not None
    with pytest.raises(Exception, match="frozen"):
        card.title = "x"  # type: ignore[misc]


async def test_past_one_off_still_carded(db):
    cal = await _cal(db)
    event = await seed_event(
        db, cal, title="Over", status="published", starts_at=NOW - timedelta(days=2)
    )
    card = await _card(db, event)
    assert card is not None
    assert (card.starts_at, card.ends_at) == (
        NOW - timedelta(days=2),
        NOW - timedelta(days=2, hours=-1),
    )


async def test_series_next_occurrence(db):
    cal = await _cal(db)
    series = await seed_series(db, cal, *WEEKLY, title="Weekly", slug="weekly", status="published")
    card = await _card(db, series)
    assert card is not None
    # 10:00 Vienna on 2026-07-01 is 08:00Z: in progress at ``now``, so it counts.
    assert card.starts_at == utc(2026, 7, 1, 8)
    assert card.occurrence_start == utc(2026, 7, 1, 8)
    assert card.path == "/events/weekly?date=2026-07-01"
    assert card.ics_path == "/events/weekly.ics"
    later = await _card(db, series, now=utc(2026, 7, 1, 9, 30))
    assert later is not None and later.starts_at == utc(2026, 7, 8, 8)


async def test_series_skips_and_moves(db):
    cal = await _cal(db)
    series = await seed_series(db, cal, *WEEKLY, title="Weekly", slug="weekly", status="published")
    skipped = OccurrenceOverride(
        event_id=series.id, original_start=utc(2026, 7, 1, 8), kind="skipped"
    )
    db.add(skipped)
    await db.flush()
    card = await _card(db, series)
    assert card is not None and card.starts_at == utc(2026, 7, 8, 8)
    assert card.path == "/events/weekly?date=2026-07-08"
    await db.delete(skipped)
    await db.flush()
    db.add(
        OccurrenceOverride(
            event_id=series.id,
            original_start=utc(2026, 7, 1, 8),
            kind="moved",
            starts_at=utc(2026, 7, 2, 12),
            ends_at=utc(2026, 7, 2, 13),
        )
    )
    await db.flush()
    card = await _card(db, series)
    assert card is not None
    assert (card.starts_at, card.ends_at) == (utc(2026, 7, 2, 12), utc(2026, 7, 2, 13))
    assert card.occurrence_start == utc(2026, 7, 1, 8)
    assert card.path == "/events/weekly?date=2026-07-01"  # the original date keeps naming it


async def test_cancelled(db):
    cal = await _cal(db)
    flagged = await seed_event(db, cal, title="F", status="published", cancelled=True, slug="f")
    card = await _card(db, flagged)
    assert card is not None and card.cancelled
    series = await seed_series(db, cal, *WEEKLY, title="S", slug="s", status="published")
    db.add(
        OccurrenceOverride(event_id=series.id, original_start=utc(2026, 7, 1, 8), kind="cancelled")
    )
    await db.flush()
    card = await _card(db, series)
    assert card is not None and card.cancelled and card.starts_at == utc(2026, 7, 1, 8)
    after = await _card(db, series, now=utc(2026, 7, 1, 9, 30))
    assert after is not None and not after.cancelled


async def test_ended_series_is_none(db):
    cal = await _cal(db)
    series = await seed_series(
        db,
        cal,
        "FREQ=WEEKLY;BYDAY=WE;COUNT=2",
        "2026-06-03T10:00",
        "2026-06-03T11:00",
        title="Done",
        status="published",
    )
    assert await _card(db, series) is None


async def test_all_day_dates(db):
    cal = await _cal(db)
    span = to_span(
        all_day=True,
        timezone="Europe/Vienna",
        start="2026-03-29",
        end="2026-03-29",
        recurring=False,
    )
    event = await seed_event(
        db,
        cal,
        title="Short day",
        status="published",
        starts_at=span.starts_at,
        ends_at=span.ends_at,
        timezone="Europe/Vienna",
        all_day=True,
    )
    card = await _card(db, event)
    assert card is not None
    assert (card.all_day, card.start_date, card.end_date) == (
        True,
        date(2026, 3, 29),
        date(2026, 3, 30),
    )


async def test_all_day_series_names_its_local_date(db):
    cal = await _cal(db)
    series = await seed_series(
        db,
        cal,
        "FREQ=WEEKLY;BYDAY=WE",
        "2026-05-06",
        "2026-05-06",
        all_day=True,
        title="All day",
        slug="all-day",
        status="published",
    )
    card = await _card(db, series, now=utc(2026, 7, 1, 12))
    assert card is not None
    assert (card.start_date, card.end_date) == (date(2026, 7, 1), date(2026, 7, 2))
    assert card.path == "/events/all-day?date=2026-07-01"


async def test_text_fallback_and_locale_prefix(db):
    locales.use("en", "de")
    cal = await _cal(db)
    event = await seed_event(db, cal, title="Hello", slug="hello", status="published")
    card = await _card(db, event, locale="de")
    assert card is not None
    assert (card.title, card.locale, card.path) == ("Hello", "en", "/events/hello")
    db.add(EventText(event_id=event.id, locale="de", slug="hallo", title="Hallo"))
    await db.flush()
    card = await _card(db, event, locale="de")
    assert card is not None
    assert (card.title, card.locale) == ("Hallo", "de")
    assert card.path == "/de/events/hallo" and card.ics_path == "/de/events/hallo.ics"
    english = await _card(db, event)
    assert english is not None and english.locale == "en"


async def test_order_follows_the_rows_and_drops_the_uncardable(db):
    cal = await _cal(db)
    a = await seed_event(db, cal, title="A", status="published", slug="a")
    done = await seed_series(
        db,
        cal,
        "FREQ=WEEKLY;COUNT=2",
        "2026-06-03T10:00",
        "2026-06-03T11:00",
        title="Done",
        status="published",
    )
    b = await seed_event(db, cal, title="B", status="published", slug="b")
    cards = await cards_for(db, [b, done, a], tenant_id="default", locale=None, now=NOW)
    assert [c.title for c in cards] == ["B", "A"]
