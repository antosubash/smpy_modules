"""A plugin's answer: validated whole, normalised, filled in."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from sm_events.calendar.extension_types import SourceCalendar, SourceOccurrence
from sm_events.calendar.plugin_validate import InvalidPluginItem, to_occurrences

CAL = SourceCalendar(
    id=uuid.uuid4(),
    slug="c",
    name="C",
    visibility="public",
    default_timezone="Europe/Vienna",
    color="#2563eb",
)
START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2027, 1, 1, tzinfo=UTC)


def utc(*a):
    return datetime(*a, tzinfo=UTC)


def timed(key="a", **kw):
    kw.setdefault("start", utc(2026, 7, 2, 10))
    kw.setdefault("end", utc(2026, 7, 2, 11))
    return SourceOccurrence(key=key, title=kw.pop("title", "T"), **kw)


def day(key="d", first=date(2026, 7, 2), last=date(2026, 7, 3), **kw):
    return SourceOccurrence(
        key=key, title=kw.pop("title", "T"), all_day=True, start_date=first, end_date=last, **kw
    )


def run(items, start=START, end=END):
    return to_occurrences(
        items, source_id="acme:s", calendar=CAL, start=start, end=end, default_lang="en"
    )


def test_timed_normalised_to_utc():
    plus2 = timezone(timedelta(hours=2))
    two, three = datetime(2026, 7, 2, 12, tzinfo=plus2), datetime(2026, 7, 2, 13, tzinfo=plus2)
    (occ,) = run([timed(start=two, end=three)])
    assert (occ.start, occ.end) == (utc(2026, 7, 2, 10), utc(2026, 7, 2, 11))
    assert occ.start.utcoffset() == timedelta(0)
    assert (occ.start_date, occ.end_date, occ.all_day) == (None, None, False)


def test_all_day_dates_to_local_midnight():
    (occ,) = run([day(first=date(2026, 3, 29), last=date(2026, 3, 30))])
    assert occ.start == utc(2026, 3, 28, 23)  # Vienna is UTC+1 until the 29th
    assert occ.end == utc(2026, 3, 29, 22)  # and UTC+2 from 03:00 that day
    assert (occ.start_date, occ.end_date, occ.timezone) == (
        date(2026, 3, 29),
        date(2026, 3, 30),
        "Europe/Vienna",
    )


def test_item_timezone_overrides_the_calendars():
    (occ,) = run([day(timezone="UTC")])
    assert occ.start == utc(2026, 7, 2) and occ.timezone == "UTC"


@pytest.mark.parametrize(
    "bad",
    [
        timed(start=datetime(2026, 7, 2, 10), end=datetime(2026, 7, 2, 11)),  # naive
        timed(start=utc(2026, 7, 2, 11), end=utc(2026, 7, 2, 11)),
        timed(start=utc(2026, 7, 2, 12), end=utc(2026, 7, 2, 11)),
        timed(end=utc(2026, 7, 2, 10) + timedelta(days=367)),
        timed(timezone="Mars/Base"),
        timed(start=None, end=None),
        timed(start=utc(2026, 7, 2, 10), end=None),
        timed(start_date=date(2026, 7, 2)),  # mixed shapes
        day(first=date(2026, 7, 3), last=date(2026, 7, 3)),
        day(first=date(2026, 7, 3), last=date(2026, 7, 2)),
        day(last=date(2027, 7, 4)),
        day(first=None),
        day(first=date.min, last=date(1, 1, 3)),
        timed(start=utc(1800, 1, 1), end=utc(1800, 1, 2)),
        timed(lang="not a lang"),
        timed(title="‮​ \n"),
        timed(title="\x00\x07"),
    ],
)
def test_invalid_item_is_refused(bad):
    with pytest.raises(InvalidPluginItem) as caught:
        run([bad])
    assert caught.value.code == "invalid_item"


def test_span_cap_is_366_days_inclusive():
    start = utc(2026, 1, 1)
    run([timed(start=start, end=start + timedelta(days=366))])
    with pytest.raises(InvalidPluginItem):
        run([timed(start=start, end=start + timedelta(days=366, seconds=1))])


def test_non_items_are_refused():
    for bad in (None, {"key": "a"}, "x", 1):
        with pytest.raises(InvalidPluginItem):
            run([bad])


@pytest.mark.parametrize(
    ("url", "kept"),
    [
        ("/admin/x", True),
        ("https://a.example/x?y=1", True),
        ("http://a.example", True),
        ("//evil", False),
        ("/\\evil", False),
        ("javascript:alert(1)", False),
        ("JaVaScRiPt:alert(1)", False),
        ("data:text/html,x", False),
        ("ftp://a/x", False),
        ("https://", False),
        ("https:/a", False),
        ("/a b", False),
        ("/a\nb", False),
        ("/a\tb", False),
        ("", False),
        ("relative/path", False),
    ],
)
def test_url_rules(url, kept):
    if kept:
        assert run([timed(url=url)])[0].url == url
    else:
        with pytest.raises(InvalidPluginItem):
            run([timed(url=url)])


def test_an_overlong_url_is_refused_even_past_the_model():
    long = SourceOccurrence.model_construct(
        key="a", title="T", start=utc(2026, 7, 2, 10), end=utc(2026, 7, 2, 11), url="/" + "x" * 2000
    )
    with pytest.raises(InvalidPluginItem):
        run([long])


def test_no_url_is_none():
    assert run([timed()])[0].url is None


def test_title_kept_as_text():
    assert run([timed(title="<script>x</script>")])[0].title == "<script>x</script>"
    assert run([timed(title="  a\x00b‮c\nd ")])[0].title == "abc d"


def test_outside_window_dropped_not_an_error():
    inside, before, after, touching = (
        timed("in", start=utc(2026, 7, 2, 10), end=utc(2026, 7, 2, 11)),
        timed("before", start=utc(2026, 1, 1), end=utc(2026, 1, 2)),
        timed("after", start=utc(2026, 8, 1), end=utc(2026, 8, 2)),
        timed("touch", start=utc(2026, 6, 30), end=utc(2026, 7, 1)),
    )
    got = run([inside, before, after, touching], start=utc(2026, 7, 1), end=utc(2026, 7, 10))
    assert [o.key.split(":", 1)[1] for o in got] == ["in"]


def test_invalid_item_outside_the_window_still_rejects_the_answer():
    with pytest.raises(InvalidPluginItem):
        run([timed("far", start=utc(2025, 1, 1), end=utc(2025, 1, 2)), timed("bad", title="\x00")])


def test_duplicate_key_invalid():
    with pytest.raises(InvalidPluginItem) as caught:
        run([timed("same"), timed("same", title="Other")])
    assert caught.value.code == "duplicate_key"


def test_fields_filled():
    (occ,) = run([timed(color="#aabbcc", status="cancelled", lang="de-AT")])
    assert occ.source == "acme:s" and occ.calendar_id == CAL.id
    assert (occ.editable, occ.type, occ.event_id) == (False, "event", None)
    assert (occ.original_start, occ.event_status) == (None, None)
    assert (occ.color, occ.status, occ.lang) == ("#aabbcc", "cancelled", "de-AT")
    plain = run([timed()])[0]
    assert (plain.color, plain.lang, plain.status) == (CAL.color, "en", "confirmed")


@pytest.mark.parametrize(
    "url", ["https://user:pw@evil.example/x", "http://user@evil.example/", "https://@a.example/"]
)
def test_url_with_credentials_is_refused(url):
    with pytest.raises(InvalidPluginItem):
        run([timed(url=url)])


@pytest.mark.parametrize(
    "bad",
    [
        {"key": "a b <x>"},
        {"key": ""},
        {"key": "k" * 201},
        {"title": "T" * 100_000},
        {"color": "red;}"},
        {"status": "weird"},
        {"lang": "x" * 40},
    ],
)
def test_model_construct_cannot_skip_the_checks(bad):
    """``model_construct`` skips pydantic's validation: every item is validated again here."""
    fields = {
        "key": "a",
        "title": "T",
        "start": utc(2026, 7, 2, 10),
        "end": utc(2026, 7, 2, 11),
        **bad,
    }
    with pytest.raises(InvalidPluginItem):
        run([SourceOccurrence.model_construct(**fields)])
