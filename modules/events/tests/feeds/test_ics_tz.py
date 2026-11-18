"""The VTIMEZONE stays correct for open-ended series, checked by an independent reader."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import icalendar
import pytest
from dateutil import tz as dtz
from sm_events.feeds.ics_calendar import build
from sm_events.web.endpoints.public._feeds import _zone_range

from tests.support.feed_items import make

NOW = datetime(2026, 11, 18, tzinfo=UTC)
ZONES = [
    "Europe/Vienna",
    "Australia/Lord_Howe",
    "America/Sao_Paulo",
    "Asia/Kathmandu",
    "Pacific/Apia",
]


def file_for(zone: str, now: datetime = NOW, item=None) -> bytes:
    first, last = _zone_range(now)
    item = item or make(
        tz=zone, rule="FREQ=WEEKLY", start="2026-03-02T10:00", end="2026-03-02T11:00"
    )
    return build([item], name="n", timezone=zone, first=first, last=last)


def reader_offsets(raw: bytes, zone: str) -> object:
    """dateutil's ``tzical`` over the file's own VTIMEZONE: nothing of ours, nothing of zoneinfo."""
    calendar = icalendar.Calendar.from_ical(raw)
    (vtz,) = calendar.walk("VTIMEZONE")
    text = "BEGIN:VCALENDAR\r\n" + vtz.to_ical().decode() + "END:VCALENDAR\r\n"
    return dtz.tzical(io.StringIO(text)).get(zone)


@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize("years", [1, 5, 10, 15])
@pytest.mark.parametrize("month", [1, 4, 7, 10])
def test_offsets_match_zoneinfo_years_ahead(zone, years, month):
    reader = reader_offsets(file_for(zone), zone)
    real = ZoneInfo(zone)
    when = datetime(NOW.year + years, month, 15, 12)
    assert when.replace(tzinfo=reader).utcoffset() == when.replace(tzinfo=real).utcoffset(), when


def test_an_open_ended_series_reaches_the_horizon_not_the_next_two_years():
    raw = file_for("Europe/Vienna")
    reader = reader_offsets(raw, "Europe/Vienna")
    summer = datetime(2029, 7, 10, 10, tzinfo=reader)
    assert summer.utcoffset().total_seconds() == 7200  # the review's case: one hour off before


def test_a_bounded_series_is_covered_to_its_end():
    first, last = _zone_range(NOW)
    item = make(
        rule="FREQ=WEEKLY;UNTIL=20450714T080000Z", start="2026-03-02T10:00", end="2026-03-02T11:00"
    )
    raw = build([item], name="n", timezone="Europe/Vienna", first=first, last=last)
    reader = reader_offsets(raw, "Europe/Vienna")
    when = datetime(2045, 7, 10, 10)
    assert (
        when.replace(tzinfo=reader).utcoffset()
        == when.replace(tzinfo=ZoneInfo("Europe/Vienna")).utcoffset()
    )


def test_a_series_far_in_the_past_is_covered_from_its_start():
    first, last = _zone_range(NOW)
    item = make(rule="FREQ=WEEKLY;COUNT=700", start="2015-03-02T10:00", end="2015-03-02T11:00")
    raw = build([item], name="n", timezone="Europe/Vienna", first=first, last=last)
    reader = reader_offsets(raw, "Europe/Vienna")
    for when in (datetime(2015, 7, 6, 10), datetime(2016, 1, 11, 10), datetime(2020, 7, 6, 10)):
        assert (
            when.replace(tzinfo=reader).utcoffset()
            == when.replace(tzinfo=ZoneInfo("Europe/Vienna")).utcoffset()
        )


def test_body_and_etag_are_stable_from_day_to_day():
    item = make(rule="FREQ=WEEKLY", start="2026-03-02T10:00", end="2026-03-02T11:00")
    a = file_for("Europe/Vienna", datetime(2026, 1, 1, tzinfo=UTC), item)
    b = file_for("Europe/Vienna", datetime(2026, 12, 31, 23, tzinfo=UTC), item)
    assert a == b
    assert a != file_for(
        "Europe/Vienna", datetime(2027, 1, 1, tzinfo=UTC), item
    )  # moves once a year


def test_the_zone_is_bounded():
    raw = file_for("Europe/Vienna")
    assert len(raw) < 20_000
