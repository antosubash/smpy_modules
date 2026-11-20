"""The reminder mail: plain text and HTML, in the follower's language, in the event's zone."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sm_events.models import Calendar, Event, EventText
from sm_events.reminders import message
from sm_events.reminders.links import Links

GOLDEN = Path(__file__).parent / "golden"
LS, PS, RLO, LRO, LRM = (chr(c) for c in (0x2028, 0x2029, 0x202E, 0x202D, 0x200E))
EVENT_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
CAL_ID = uuid.UUID("99999999-8888-7777-6666-555555555555")
LINKS = Links(
    base_url="https://events.example.org",
    prefix="/events",
    content_locales=("en", "de"),
    single_tenant=True,
)


def _event(**fields) -> Event:
    base = {
        "id": EVENT_ID,
        "calendar_id": CAL_ID,
        "uid": "u@x",
        "type": "event",
        "status": "published",
        "starts_at": datetime(2026, 7, 1, 8, tzinfo=UTC),
        "ends_at": datetime(2026, 7, 1, 9, tzinfo=UTC),
        "timezone": "Europe/Vienna",
        "all_day": False,
        "cancelled": False,
        "attendance_mode": "in_person",
        "venue_name": "Town Hall",
        "address": "Main Square 1\n1010 Vienna",
        "online_url": None,
    }
    base.update(fields)
    return Event(**base)


def _texts(**by_locale: str) -> dict[str, EventText]:
    return {
        loc: EventText(event_id=EVENT_ID, locale=loc, slug=f"talk-{loc}", title=title)
        for loc, title in by_locale.items()
    }


def _calendar(visibility="public") -> Calendar:
    return Calendar(id=CAL_ID, slug="main", name="Main", owner_id="o", visibility=visibility)


def _build(event=None, texts=None, calendar=None, **over):
    event = event or _event()
    args = {
        "to": "reader@example.org",
        "event": event,
        "texts": texts or _texts(en="Garden talk", de="Gartenvortrag"),
        "calendar": calendar or _calendar(),
        "occurrence_start": event.starts_at,
        "occurrence_end": event.ends_at,
        "lead": 60,
        "locale": "en",
        "default_locale": "en",
        "links": LINKS,
    }
    args.update(over)
    return message.build_message(**args)


CASES = {
    "en_timed": {},
    "de_timed": {"locale": "de"},
    "en_all_day_multi": {
        "event": _event(
            all_day=True,
            venue_name=None,
            address=None,
            starts_at=datetime(2026, 7, 5, 22, tzinfo=UTC),
            ends_at=datetime(2026, 7, 8, 22, tzinfo=UTC),
        ),
        "lead": 1440,
    },
    "de_series_online": {
        "event": _event(
            attendance_mode="hybrid",
            online_url="https://meet.example.org/room?x=1&y=2",
            starts_at=datetime(2026, 1, 12, 9, tzinfo=UTC),
            ends_at=datetime(2026, 1, 12, 10, tzinfo=UTC),
            rrule="FREQ=WEEKLY",
        ),
        "locale": "de",
        "lead": 10080,
    },
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_golden(name):
    got = _build(**CASES[name])
    assert got.to == "reader@example.org"
    assert got.html is not None
    golden = json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))
    assert {"subject": got.subject, "text": got.text} == golden


def test_zone_abbreviation():
    july = _build()
    assert "CEST" in july.text and "CET" not in july.text.replace("CEST", "")
    january = _build(
        event=_event(
            starts_at=datetime(2026, 1, 12, 9, tzinfo=UTC),
            ends_at=datetime(2026, 1, 12, 10, tzinfo=UTC),
        )
    )
    assert "CET" in january.text and "CEST" not in january.text


def test_times_are_the_events_not_the_readers():
    got = _build()  # 08:00Z is 10:00 in Vienna in July
    assert "10:00" in got.text and "08:00" not in got.text
    assert "10:00" in got.html


def test_title_fallback():
    got = _build(texts=_texts(en="Only English"), locale="de")
    assert "Only English" in got.subject and "Only English" in got.text
    got = _build(texts=_texts(fr="Seulement"), locale="de", default_locale="en")
    assert "Seulement" in got.subject  # neither: the first text there is


def test_unknown_locale_falls_back_to_en():
    assert _build(locale="xx").text == _build(locale="en").text
    assert _build(locale="de-AT").text == _build(locale="de").text  # a primary subtag counts


def test_subject_sanitised():
    nasty = f"Talk\r\nBcc: evil@example.org {LS} x{RLO} " + "y" * 400
    got = _build(texts=_texts(en=nasty))
    assert "\n" not in got.subject and "\r" not in got.subject
    assert not any(c in got.subject for c in (LS, PS, RLO, LRO, LRM))
    assert len(got.subject) <= 200
    assert message.clean_subject("a\x00b\x07c\x7fd  e\t\tf") == "abcd e f"
    assert message.clean_subject("x" * 500) == "x" * 200


def test_online_url_only_when_online_or_hybrid():
    url = "https://meet.example.org/room"
    for mode, shown in (("in_person", False), ("online", True), ("hybrid", True)):
        got = _build(event=_event(attendance_mode=mode, online_url=url))
        assert (url in got.text) is shown and (url in got.html) is shown, mode
    for bad in (
        "javascript:alert(1)",
        "https://user:pw@evil.example",
        "ftp://x.example",
        "meet.example.org",
    ):
        got = _build(event=_event(attendance_mode="online", online_url=bad))
        assert bad not in got.text and bad not in got.html, bad


def test_the_place_is_one_line():
    got = _build()
    assert "Town Hall" in got.text and "Main Square 1, 1010 Vienna" in got.text


def test_moved_occurrence_is_worded_as_moved():
    event = _event()
    got = _build(moved_from=datetime(2026, 6, 24, 8, tzinfo=UTC))
    assert "24" in got.text and "moved" in got.text.lower()
    assert "moved" not in _build().text.lower()
    de = _build(moved_from=datetime(2026, 6, 24, 8, tzinfo=UTC), locale="de")
    assert "verschoben" in de.text.lower()
    assert event


def test_links_public_for_a_public_calendar_on_a_single_tenant_host():
    got = _build(event=_event(rrule="FREQ=WEEKLY"))
    assert "https://events.example.org/events/talk-en?date=2026-07-01" in got.text
    de = _build(locale="de")
    assert "https://events.example.org/de/events/talk-de" in de.text  # the text's own language
    assert "https://events.example.org/admin/events/reminders" in got.text


@pytest.mark.parametrize(
    ("visibility", "single"), [("internal", True), ("private", True), ("public", False)]
)
def test_links_the_editor_only_for_someone_who_can_edit(visibility, single):
    got = _build(
        calendar=_calendar(visibility), links=replace(LINKS, single_tenant=single), can_edit=True
    )
    assert f"https://events.example.org/admin/events/edit/{EVENT_ID}" in got.text
    assert "/events/talk-" not in got.text


@pytest.mark.parametrize(
    ("visibility", "single"), [("internal", True), ("private", True), ("public", False)]
)
def test_a_viewer_is_linked_to_the_calendar_with_that_occurrence_open(visibility, single):
    got = _build(
        calendar=_calendar(visibility),
        links=replace(LINKS, single_tenant=single),
        occurrence_key="e1:2026-07-01T08:00:00Z",
    )
    url = (
        "https://events.example.org/admin/events/?view=day&date=2026-07-01&tz=calendar"
        f"&calendar={CAL_ID}&event=e1%3A2026-07-01T08%3A00%3A00Z"
    )
    assert url in got.text and url in (got.html or "").replace("&amp;", "&")
    assert "/admin/events/edit/" not in got.text


def test_the_day_is_the_events_own_not_utc():
    late = _event(starts_at=datetime(2026, 7, 1, 22, 30, tzinfo=UTC))  # 00:30 on the 2nd in Vienna
    got = _build(event=late, calendar=_calendar("internal"), occurrence_key="k")
    assert "date=2026-07-02&tz=calendar" in got.text


def test_a_relative_or_missing_base_url_is_refused_not_guessed():
    for bad in ("", "/relative", "events.example.org", "javascript:alert(1)"):
        with pytest.raises(ValueError):
            _build(links=replace(LINKS, base_url=bad))


def test_html_is_escaped_and_has_nothing_to_track_with():
    got = _build(texts=_texts(en='<script>alert(1)</script> & "quotes"'))
    assert "<script>" not in got.html and "&lt;script&gt;" in got.html
    assert ("&amp;" in got.html and "&#34;" in got.html) or "&quot;" in got.html
    assert "<img" not in got.html.lower() and "<iframe" not in got.html.lower()
    assert "<script>alert(1)</script>" in got.text  # plain text is not HTML: nothing to escape
    assert got.html.count("<a ") == 2  # the event and the manage link, nothing else
    assert "style=" not in got.html or "url(" not in got.html


def test_the_mail_carries_nobody_elses_data():
    got = _build()
    for text in (got.text, got.html, got.subject):
        assert "@" not in text.replace("reader@example.org", "")


def test_catalogue_keys_parity():
    root = Path(message.__file__).resolve().parents[1] / "locales"
    keys = {
        p.stem: set(json.loads(p.read_text(encoding="utf-8"))["reminders"]["mail"])
        for p in root.glob("*.json")
    }
    assert keys["en"] == keys["de"] and keys["en"]


def test_a_cancelled_or_unpublished_event_is_not_a_message():
    for bad in (_event(cancelled=True), _event(status="draft")):
        with pytest.raises(ValueError):
            _build(event=bad)
    assert timedelta  # keep the import used
