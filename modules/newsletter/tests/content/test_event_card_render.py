"""The event card in an email: the when-line in the event's zone, the HTML and the text part."""

# ruff: noqa: RUF001 - the en dashes of the when-line are what these tests pin

from __future__ import annotations

import re

import pytest
from sm_newsletter.content.blocks import EventCardProps, parse_body
from sm_newsletter.content.render import event_card as card
from sm_newsletter.content.render import render
from sm_newsletter.content.render.types import Branding, FooterCopy, RenderContext, RenderInput

EVENT_ID = "3f2c6c1e-8f4e-4a45-9d0e-0a5b8f6f1c11"
BASE = {
    "id": "ev",
    "source_id": EVENT_ID,
    "title": "Open day",
    "excerpt": "Come by",
    "image_url": "",
    "url": "/events/open-day?date=2026-07-01",
    "ics_url": "/events/open-day.ics",
    "locale": "en",
    "starts_at": "2026-07-01T08:00:00Z",
    "ends_at": "2026-07-01T09:30:00Z",
    "all_day": False,
    "start_date": None,
    "end_date": None,
    "timezone": "Europe/Vienna",
    "attendance_mode": "in_person",
    "place": "Hall 1, Main St 2",
    "cancelled": False,
    "snapshot_at": "2026-11-03T10:00:00Z",
}
FOOTER = FooterCopy(reason="Because.", unsubscribe="Unsubscribe")
CTX = RenderContext(
    content_base="https://acme.example.org",
    public_base="https://example.org",
    branding=Branding(app_name="Acme", accent="#0f766e", logo_url=""),
    physical_address="1 Main Street",
    footer=FOOTER,
    locale="en",
)


def props(**changes) -> EventCardProps:
    return EventCardProps.model_validate({**BASE, **changes})


def when(locale: str = "en", **changes) -> str:
    return card.when(props(**changes), locale)


def test_when_timed_same_day():
    assert when() == "Wednesday, July 1, 2026, 10:00 AM–11:30 AM CEST"
    assert when("de") == "Mittwoch, 1. Juli 2026, 10:00–11:30 CEST"


def test_when_winter_zone():
    got = when(starts_at="2026-01-14T09:00:00Z", ends_at="2026-01-14T10:00:00Z")
    assert got == "Wednesday, January 14, 2026, 10:00 AM–11:00 AM CET"


def test_when_in_the_events_zone_not_the_readers():
    got = when(timezone="America/New_York")  # 08:00Z is 4 AM there
    assert got == "Wednesday, July 1, 2026, 4:00 AM–5:30 AM EDT"


def test_when_multi_day_timed():
    got = when(starts_at="2026-07-01T16:00:00Z", ends_at="2026-07-02T07:00:00Z")
    assert got == "Wednesday, July 1, 2026, 6:00 PM CEST – Thursday, July 2, 2026, 9:00 AM CEST"


def test_when_all_day_short_day():
    got = when(
        all_day=True,
        start_date="2026-03-29",
        end_date="2026-03-30",
        starts_at="2026-03-28T23:00:00Z",
        ends_at="2026-03-29T22:00:00Z",  # a 23-hour day
    )
    assert got == "Sunday, March 29, 2026"


def test_when_all_day_range_inclusive():
    got = when(
        all_day=True,
        start_date="2026-08-01",
        end_date="2026-08-04",
        starts_at="2026-07-31T22:00:00Z",
        ends_at="2026-08-03T22:00:00Z",
    )
    assert got == "Saturday, August 1, 2026 – Monday, August 3, 2026"
    assert when("de", all_day=True, start_date="2026-08-01", end_date="2026-08-02",
                starts_at="2026-07-31T22:00:00Z", ends_at="2026-08-01T22:00:00Z") == (
        "Samstag, 1. August 2026"
    )  # fmt: skip


def test_when_across_dst():
    got = when(starts_at="2026-10-24T23:30:00Z", ends_at="2026-10-25T02:30:00Z")
    assert got == "Sunday, October 25, 2026, 1:30 AM CEST–3:30 AM CET"


@pytest.mark.parametrize("locale", ["xx", "", "zz_ZZ", "not a locale"])
def test_when_unknown_locale_falls_back_to_en(locale):
    assert when(locale) == when("en")


def _email(locale: str = "en", ctx: RenderContext = CTX, **changes):
    block = {"type": "EventCard", "props": {**BASE, **changes}}
    ctx = RenderContext(**{**ctx.__dict__, "locale": locale})
    return render(RenderInput(subject="S", preheader="P", blocks=parse_body([block])), ctx)


def test_html_links_absolute_and_inert():
    out = _email(
        title='<script>alert(1)</script> {{first_name}} "q"',
        excerpt="<b>x</b> {{unsubscribe_url}}",
        image_url="https://cdn.example.com/a.png",
    )
    hrefs = re.findall(r'href="([^"]*)"', out.html)
    assert "https://acme.example.org/events/open-day?date=2026-07-01" in hrefs
    assert "https://acme.example.org/events/open-day.ics" in hrefs
    assert 'src="https://cdn.example.com/a.png"' in out.html
    assert "<script" not in out.html and "<b>x" not in out.html and "{{first_name" not in out.html
    assert "&lt;script&gt;" in out.html and "&quot;q&quot;" in out.html
    assert "Wednesday, July 1, 2026, 10:00 AM–11:30 AM CEST" in out.html
    assert "Hall 1, Main St 2" in out.html and "Add to calendar" in out.html


def test_a_site_relative_image_is_made_absolute():
    out = _email(image_url="/media/a.png")
    assert 'src="https://acme.example.org/media/a.png"' in out.html


def test_no_event_id_in_any_output():
    for locale in ("en", "de"):
        out = _email(locale)
        assert EVENT_ID not in out.html and EVENT_ID not in out.text
        assert EVENT_ID.replace("-", "") not in out.html


def test_cancelled_badge_no_calendar_link():
    out = _email(cancelled=True)
    assert "Cancelled" in out.html and ".ics" not in out.html and "Add to calendar" not in out.html
    assert out.text.startswith("Cancelled: Open day")
    assert ".ics" not in out.text


def test_place_lines():
    assert card.place_line(props(), "Online") == "Hall 1, Main St 2"
    assert card.place_line(props(attendance_mode="online", place="Hall 1"), "Online") == "Online"
    assert (
        card.place_line(props(attendance_mode="hybrid"), "Online") == "Hall 1, Main St 2 · Online"
    )
    assert card.place_line(props(attendance_mode="hybrid", place=""), "Online") == "Online"
    assert card.place_line(props(place=""), "Online") == ""


def test_text_part_lines():
    out = _email()
    body = out.text.split("\n\n")[0]
    assert body.split("\n") == [
        "Open day",
        "Wednesday, July 1, 2026, 10:00 AM–11:30 AM CEST",
        "Hall 1, Main St 2",
        "Come by",
        "https://acme.example.org/events/open-day?date=2026-07-01",
        "Add to calendar: https://acme.example.org/events/open-day.ics",
    ]
    bare = _email(excerpt="", place="").text.split("\n\n")[0].split("\n")
    assert len(bare) == 4  # title, when, url, calendar link: empty lines are dropped


def test_german_labels_come_from_the_footer_copy():
    de = RenderContext(
        **{
            **CTX.__dict__,
            "footer": FooterCopy(
                reason="Weil.",
                unsubscribe="Abmelden",
                add_to_calendar="Zum Kalender hinzufügen",
                cancelled="Abgesagt",
                online="Online",
            ),
        }
    )
    out = _email("de", de, cancelled=True)
    assert "Abgesagt" in out.html and out.text.startswith("Abgesagt: Open day")
    assert "Mittwoch, 1. Juli 2026" in out.html


def test_direction_controls_never_reach_the_email():
    """Events' validators refuse them in a title, but a snapshot may hold text written before that
    (or by a PATCH straight to the body): the renderer neutralises them itself."""
    hostile = "Ev\u202eil \u2066x\u2069 \u200fend"
    out = _email(title=hostile, excerpt=hostile, place=hostile, attendance_mode="hybrid")
    for part in (out.html, out.text):
        assert not re.search("[\u200e\u200f\u061c\u202a-\u202e\u2066-\u2069]", part)
    assert "Evil" in out.html and "Evil" in out.text
