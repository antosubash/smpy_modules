"""Byte-exact snapshots of the renderer (R5).

``NEWSLETTER_UPDATE_GOLDEN=1`` rewrites the files; review the diff in the commit.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from sm_newsletter.content.blocks import parse_body
from sm_newsletter.content.render import render
from sm_newsletter.content.render.types import Branding, FooterCopy, RenderContext, RenderInput
from sm_newsletter.content.urls import UNSUBSCRIBE_TAG

GOLDEN = Path(__file__).parent / "golden"
SNAP = "2026-11-01T10:00:00+00:00"

EVENT = {
    "source_id": "3f2c6c1e-8f4e-4a45-9d0e-0a5b8f6f1c11",
    "image_url": "",
    "url": "/events/open-day",
    "ics_url": "/events/open-day.ics",
    "locale": "en",
    "starts_at": "2026-07-01T08:00:00Z",
    "ends_at": "2026-07-01T09:30:00Z",
    "all_day": False,
    "start_date": None,
    "end_date": None,
    "timezone": "Europe/Vienna",
    "attendance_mode": "in_person",
    "cancelled": False,
    "snapshot_at": SNAP,
}
EVENT_CARDS = [
    {"type": "Heading", "props": {"id": "h", "text": "Veranstaltungen", "level": "1"}},
    {  # timed, in person, with an image
        "type": "EventCard",
        "props": {
            "id": "timed", **EVENT, "title": "Tag der offenen Tür", "excerpt": "Kommen Sie vorbei.",
            "image_url": "/media/tag.png", "place": "Halle 1, Hauptstraße 2",
        },
    },
    {  # a series' next occurrence: the page address names the date
        "type": "EventCard",
        "props": {
            "id": "series", **EVENT, "title": "Wöchentlicher Stammtisch", "excerpt": "",
            "url": "/de/events/stammtisch?date=2026-07-08", "ics_url": "/de/events/stammtisch.ics",
            "locale": "de", "starts_at": "2026-07-08T16:00:00Z", "ends_at": "2026-07-08T18:00:00Z",
            "place": "Café Central",
        },
    },
    {  # all day, over several days, in a zone that is not the reader's
        "type": "EventCard",
        "props": {
            "id": "allday", **EVENT, "title": "Sommerlager", "excerpt": "Drei Tage draußen.",
            "all_day": True, "start_date": "2026-08-01", "end_date": "2026-08-04",
            "starts_at": "2026-07-31T22:00:00Z", "ends_at": "2026-08-03T22:00:00Z",
            "place": "Seestraße 9", "attendance_mode": "hybrid",
        },
    },
    {  # cancelled: badge, and no calendar link
        "type": "EventCard",
        "props": {
            "id": "cancelled", **EVENT, "title": "Konzert", "excerpt": "Entfällt.",
            "cancelled": True, "place": "Stadthalle",
        },
    },
    {  # online, nothing optional
        "type": "EventCard",
        "props": {
            "id": "bare", **EVENT, "title": "Webinar", "excerpt": "", "place": "",
            "attendance_mode": "online", "timezone": "America/New_York",
        },
    },
    {  # hostile text: escaped, no merge tag survives
        "type": "EventCard",
        "props": {
            "id": "hostile", **EVENT,
            "title": "<script>alert(1)</script> \"Fun\" & {{first_name}} \u202eevil",
            "excerpt": "<img src=x onerror=alert(1)> {{unsubscribe_url}}", "place": "A&B <Hall>",
        },
    },
]  # fmt: skip

KITCHEN_SINK = [
    {"type": "Heading", "props": {"id": "h1", "text": "Hello {{first_name|friend}}", "level": "1"}},
    {"type": "Heading", "props": {"id": "h2", "text": "This week", "align": "center"}},
    {
        "type": "RichText",
        "props": {
            "id": "rt",
            "html": (
                '<p>Read <strong>this</strong> and <a href="/about">that</a>.</p>'
                "<ul><li>one</li><li>two</li></ul><blockquote>Quoted</blockquote>"
            ),
        },
    },
    {
        "type": "Image",
        "props": {
            "id": "img",
            "src": "/media/hero.png",
            "alt": "Hero",
            "href": "/hero",
            "width": 480,
        },
    },
    {
        "type": "Button",
        "props": {"id": "btn", "label": "Read more", "href": "/news", "align": "left"},
    },
    {"type": "Divider", "props": {"id": "div"}},
    {"type": "Spacer", "props": {"id": "sp", "size": "lg"}},
    {
        "type": "ArticleCard",
        "props": {
            "id": "ac",
            "source_id": 7,
            "title": "Spring & summer",
            "excerpt": "What is new.",
            "image_url": "/media/a.png",
            "url": "/news/spring",
            "snapshot_at": SNAP,
        },
    },
    {
        "type": "PageCard",
        "props": {
            "id": "pc",
            "source_id": 3,
            "title": "About us",
            "excerpt": "",
            "url": "https://other.example.net/about",
            "snapshot_at": SNAP,
        },
    },
    {
        "type": "EventCard",
        "props": {
            "id": "ev",
            **EVENT,
            "title": "Open day",
            "excerpt": "Meet the team.",
            "image_url": "/media/day.png",
            "place": "Hall 1, Main St 2",
        },
    },
    {"type": "Button", "props": {"id": "bye", "label": "Leave", "href": UNSUBSCRIBE_TAG}},
]
MINIMAL = [{"type": "RichText", "props": {"id": "rt", "html": "<p>Just text.</p>"}}]

FOOTER = FooterCopy(
    reason="You are receiving this email because you subscribed to updates from Acme.",
    unsubscribe="Unsubscribe",
)
FULL = RenderContext(
    content_base="https://acme.example.org",
    public_base="https://example.org",
    branding=Branding(
        app_name="Acme", accent="#0f766e", logo_url="https://example.org/newsletter/brand/logo?v=1"
    ),
    physical_address="Acme Ltd\n1 Main Street\nTown",
    footer=FOOTER,
    locale="en",
)
BARE = RenderContext(
    content_base="",
    public_base="",
    branding=Branding(app_name="Newsletter", accent="#2563eb", logo_url=""),
    physical_address="",
    footer=FOOTER,
    locale="de",
)
DE = RenderContext(
    content_base="https://acme.example.org",
    public_base="https://example.org",
    branding=Branding(app_name="Acme", accent="#0f766e", logo_url=""),
    physical_address="Acme GmbH\nHauptstraße 1",
    footer=FooterCopy(
        reason="Sie erhalten diese E-Mail, weil Sie Neuigkeiten von Acme abonniert haben.",
        unsubscribe="Abmelden",
        read_more="Weiterlesen",
        add_to_calendar="Zum Kalender hinzufügen",
        cancelled="Abgesagt",
        online="Online",
    ),
    locale="de",
)
CASES = {
    "event_cards": (EVENT_CARDS, DE, ()),
    "kitchen_sink": (KITCHEN_SINK, FULL, ()),
    "minimal": (MINIMAL, FULL, ()),
    "no_base_url": (KITCHEN_SINK, BARE, ("relative_urls", "physical_address_missing")),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_golden(case):
    raw, context, warnings = CASES[case]
    out = render(
        RenderInput(
            subject="Weekly {{first_name|news}}", preheader="Inside", blocks=parse_body(raw)
        ),
        context,
    )
    assert out.warnings == warnings
    assert EVENT["source_id"] not in out.html + out.text  # an event's id is never printed
    assert "\u202e" not in out.html + out.text  # nor a direction override
    for ext, value in (("html", out.html), ("txt", out.text)):
        path = GOLDEN / f"{case}.{ext}"
        if os.environ.get("NEWSLETTER_UPDATE_GOLDEN") == "1":
            path.write_text(value, encoding="utf-8")
        assert path.read_text(encoding="utf-8") == value, f"{path.name} differs"
    assert "<script" not in out.html and "<style" not in out.html and "class=" not in out.html
    assert out.html.count(f'href="{UNSUBSCRIBE_TAG}"') >= 1
    if context.content_base:
        for url in re.findall(r'(?:href|src)="([^"]*)"', out.html):
            assert url == UNSUBSCRIBE_TAG or url.startswith("https://"), url
