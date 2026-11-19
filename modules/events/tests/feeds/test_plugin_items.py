"""A plugin source's items as plain ``VEVENT``s."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import icalendar
from sm_events.calendar.occurrence import Occurrence, PluginOccurrence
from sm_events.feeds.plugin_items import plugin_vevents

CAL = uuid.uuid4()


def occ(key="k", title="T", **kw) -> Occurrence:
    fields = {
        "source": "acme:s",
        "key": key,
        "calendar_id": CAL,
        "start": datetime(2026, 7, 2, 10, tzinfo=UTC),
        "end": datetime(2026, 7, 2, 11, tzinfo=UTC),
        "all_day": False,
        "timezone": "Europe/Vienna",
        "title": title,
        "lang": "en",
        "color": "#2563eb",
        "type": "event",
        **kw,
    }
    fields["key"] = f"{fields['calendar_id']}:{key}"  # what the validator makes of a plugin's key
    return PluginOccurrence(**fields)


def render(*items, absolute=lambda p: f"https://x.example{p}") -> bytes:
    cal = icalendar.Calendar()
    for event in plugin_vevents(items, absolute=absolute):
        cal.add_component(event)
    return cal.to_ical()


def parse(raw: bytes) -> list[icalendar.Event]:
    return list(icalendar.Calendar.from_ical(raw).walk("VEVENT"))


def test_uid_and_dates():
    timed = occ("t", "Timed")
    day = occ(
        "d",
        "Day",
        all_day=True,
        start_date=date(2026, 7, 2),
        end_date=date(2026, 7, 4),
        start=datetime(2026, 7, 1, 22, tzinfo=UTC),
        end=datetime(2026, 7, 3, 22, tzinfo=UTC),
    )
    raw = render(timed, day)
    a, b = parse(raw)
    assert (str(a["UID"]), str(b["UID"])) == (f"acme:s:{CAL}:t", f"acme:s:{CAL}:d")
    assert b"DTSTART:20260702T100000Z" in raw and b"DTEND:20260702T110000Z" in raw
    assert b"DTSTART;VALUE=DATE:20260702" in raw
    assert b"DTEND;VALUE=DATE:20260704" in raw  # exclusive
    assert str(a["STATUS"]) == "CONFIRMED" and str(a["SEQUENCE"]) == "0"


def test_cancelled_status():
    (event,) = parse(render(occ(status="cancelled")))
    assert str(event["STATUS"]) == "CANCELLED"


def test_url_absolute_for_path():
    (path, full, none) = parse(
        render(occ("a", url="/admin/x"), occ("b", url="https://a.example/x"), occ("c"))
    )
    assert str(path["URL"]) == "https://x.example/admin/x"
    assert str(full["URL"]) == "https://a.example/x"
    assert "URL" not in none


def test_dtstamp_deterministic():
    stamped = occ("a", updated_at=datetime(2026, 5, 1, 8, tzinfo=UTC))
    plain = occ("b")
    first = render(stamped, plain)
    assert first == render(stamped, plain)
    a, b = parse(first)
    assert a["DTSTAMP"].dt == datetime(2026, 5, 1, 8, tzinfo=UTC)
    assert b["DTSTAMP"].dt == datetime(2026, 7, 2, 10, tzinfo=UTC)  # else the item's start


def test_title_escaped():
    nasty = "A; B, C\\ D\nE:F"
    raw = render(occ(title=nasty))
    (event,) = parse(raw)
    assert str(event["SUMMARY"]).replace("\n", " ") == "A; B, C\\ D E:F"
    assert raw.count(b"\r\nSUMMARY") == 1  # a newline in a title cannot start a property


def test_the_uid_is_per_source_calendar_and_key():
    other = uuid.uuid4()
    events = parse(render(occ("same", "One"), occ("same", "Two", calendar_id=other)))
    assert [str(e["UID"]) for e in events] == [f"acme:s:{CAL}:same", f"acme:s:{other}:same"]


def test_a_repeated_uid_keeps_the_first():
    events = parse(render(occ("same", "First"), occ("same", "Second")))
    assert [str(e["SUMMARY"]) for e in events] == ["First"]


def test_the_uid_is_capped_like_a_native_one():
    from sm_events.core import constants

    (event,) = parse(render(occ("k" * 200, source="acme:" + "s" * 40)))
    assert len(str(event["UID"])) <= constants.UID_MAX


def test_updated_at_never_serialised():
    assert "updated_at" not in occ(updated_at=datetime(2026, 5, 1, tzinfo=UTC)).model_dump()


def test_long_keys_sharing_a_prefix_keep_distinct_uids():
    """A UID cut at the cap used to collide for two long keys with one long prefix, and the
    second item was dropped: the cut keeps a digest of the whole value."""
    source = "p" * 120 + ":s"
    first = occ("k" * 199 + "1", "One", source=source)
    second = occ("k" * 199 + "2", "Two", source=source)
    again = occ("k" * 199 + "1", "One", source=source)
    one, two = parse(render(first, second))
    assert str(one["UID"]) != str(two["UID"])
    assert len(str(one["UID"])) <= 255 and len(str(two["UID"])) <= 255
    assert str(parse(render(again))[0]["UID"]) == str(one["UID"])  # stable across requests
    short = parse(render(occ("short")))[0]
    assert str(short["UID"]) == f"acme:s:{CAL}:short"  # a short UID is untouched
