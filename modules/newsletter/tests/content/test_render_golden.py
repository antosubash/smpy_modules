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
CASES = {
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
