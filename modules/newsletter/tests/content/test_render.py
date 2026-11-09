"""Structural rules of the email renderer (R5): what every rendered email must and must not be."""

from __future__ import annotations

import re

import pytest
from sm_newsletter.content.blocks import parse_body
from sm_newsletter.content.render import personalise, render
from sm_newsletter.content.render.types import Branding, FooterCopy, RenderContext, RenderInput
from sm_newsletter.content.urls import UNSUBSCRIBE_TAG

SNAP = "2026-11-01T10:00:00+00:00"
U = "https://news.example.org/newsletter/u/tok"


def ctx(**over) -> RenderContext:
    values = {
        "content_base": "https://acme.example.org",
        "public_base": "https://example.org",
        "branding": Branding(app_name="Acme", accent="#2563eb", logo_url=""),
        "physical_address": "1 Main St\nTown",
        "footer": FooterCopy(reason="You get this from Acme.", unsubscribe="Unsubscribe"),
        "locale": "en",
    }
    values.update(over)
    return RenderContext(**values)


def body(*items: dict) -> list:
    return parse_body(
        [{"type": t, "props": {"id": f"b{i}", **p}} for i, (t, p) in enumerate(items)]
    )


def inp(blocks, subject="Hello", preheader="Peek") -> RenderInput:
    return RenderInput(subject=subject, preheader=preheader, blocks=blocks)


CARD = {
    "source_id": 1,
    "title": "A {{first_name}} title",
    "excerpt": "Short {{unsubscribe_url}} text",
    "image_url": "/media/a.png",
    "url": "/news/a",
    "snapshot_at": SNAP,
}


def test_footer_always_present():
    out = render(inp([]), ctx())
    assert out.warnings == ("empty_body",)
    assert "You get this from Acme." in out.html
    assert f'href="{UNSUBSCRIBE_TAG}"' in out.html
    assert "1 Main St<br>Town" in out.html
    assert out.text.endswith(
        f"--\nYou get this from Acme.\n1 Main St\nTown\nUnsubscribe: {UNSUBSCRIBE_TAG}\n"
    )


def test_images_shrink_with_the_cell():
    """A bare width attribute is min-content in an auto table: 375 px viewports overflowed."""
    blocks = body(
        ("Image", {"src": "/media/x.png", "alt": "x", "width": 536}),
        ("ArticleCard", CARD),
    )
    out = render(inp(blocks), ctx(branding=Branding("Acme", "#2563eb", "/logo.png")))
    imgs = re.findall(r"<img [^>]*>", out.html)
    assert len(imgs) == 3
    for tag in imgs:
        assert re.search(r'style="[^"]*display:block;width:100%;max-width:\d+px;height:auto', tag)
        assert re.search(r' width="\d+"', tag)  # Outlook reads the attribute
    assert "max-width:536px" in imgs[1]


def test_no_script_ever():
    blocks = body(
        ("RichText", {"html": "<p>ok<script>alert(1)</script></p><style>p{}</style>"}),
        ("Heading", {"text": "<script>alert(1)</script>"}),
    )
    out = render(inp(blocks, subject="<script>x</script>"), ctx())
    lowered = out.html.lower()
    assert "<script" not in lowered and "<style" not in lowered
    assert "class=" not in lowered
    assert "&lt;script&gt;" in out.html


def test_all_urls_absolute():
    blocks = body(
        ("RichText", {"html": '<p><a href="/about">About</a> <a href="mailto:a@b.org">m</a></p>'}),
        ("Image", {"src": "/media/x.png", "href": "/x", "alt": "x"}),
        ("Image", {"src": "//cdn.example.org/y.png"}),
        ("Button", {"label": "Go", "href": "/go"}),
        ("Button", {"label": "Bye", "href": UNSUBSCRIBE_TAG}),
        ("ArticleCard", CARD),
        ("PageCard", {**CARD, "image_url": ""}),
    )
    c = ctx(branding=Branding(app_name="Acme", accent="#123456", logo_url="https://example.org/l"))
    out = render(inp(blocks), c)
    urls = re.findall(r'(?:href|src)="([^"]*)"', out.html)
    assert len(urls) >= 10
    for url in urls:
        assert url == UNSUBSCRIBE_TAG or url.startswith(("https://", "mailto:")), url
    assert "https://acme.example.org/about" in out.html
    assert "https://acme.example.org/news/a" in out.text
    assert "relative_urls" not in out.warnings


def test_relative_warning_without_base():
    blocks = body(("Button", {"label": "Go", "href": "/go"}))
    out = render(inp(blocks), ctx(content_base=""))
    assert "relative_urls" in out.warnings
    assert 'href="/go"' in out.html
    assert "relative_urls" in render(inp(blocks), ctx(public_base="")).warnings


def test_physical_address_missing_warning():
    blocks = body(("Divider", {}))
    out = render(inp(blocks), ctx(physical_address="  "))
    assert out.warnings == ("physical_address_missing",)
    assert render(inp(blocks), ctx()).warnings == ()


def test_preheader_hidden():
    out = render(inp([], preheader="Sneak <peek>"), ctx())
    m = re.search(r'<div style="([^"]*)">Sneak &lt;peek&gt;</div>', out.html)
    assert m is not None
    assert "display:none" in m.group(1) and "mso-hide:all" in m.group(1)
    assert "max-height:0" in m.group(1) and "overflow:hidden" in m.group(1)


def test_subject_merge():
    t = render(inp([], subject="Hi {{first_name|there}}"), ctx())
    assert personalise(t, first_name=None, unsubscribe_url=U).subject == "Hi there"
    assert personalise(t, first_name="Ann", unsubscribe_url=U).subject == "Hi Ann"
    assert "<title>Hi Ann</title>" in personalise(t, first_name="Ann", unsubscribe_url=U).html


def test_subject_stays_a_header():
    t = render(inp([], subject="Hi {{first_name}}"), ctx())
    out = personalise(t, first_name="Ann\r\nBcc: x@y.org\x00", unsubscribe_url=U)
    assert "\r" not in out.subject and "\n" not in out.subject and "\x00" not in out.subject
    assert out.subject.startswith("Hi Ann")


def test_unsubscribe_tag_replaced_everywhere():
    blocks = body(("Button", {"label": "Leave", "href": UNSUBSCRIBE_TAG}))
    out = personalise(render(inp(blocks), ctx()), first_name=None, unsubscribe_url=U + "?a=1&b=2")
    assert UNSUBSCRIBE_TAG not in out.html and UNSUBSCRIBE_TAG not in out.text
    assert out.html.count(f'href="{U}?a=1&amp;b=2"') == 2  # the button and the footer
    assert f"Leave: {U}?a=1&b=2" in out.text
    assert out.text.endswith(f"Unsubscribe: {U}?a=1&b=2\n")


def test_first_name_html_injection_escaped():
    blocks = body(("Heading", {"text": "Hi {{first_name}}"}))
    out = personalise(
        render(inp(blocks), ctx()), first_name='<img src=x onerror="a">', unsubscribe_url=U
    )
    assert "<img src=x" not in out.html
    assert "&lt;img src=x onerror=&quot;a&quot;&gt;" in out.html


def test_card_text_cannot_carry_merge_tags():
    out = render(inp(body(("ArticleCard", CARD))), ctx())
    mail = personalise(out, first_name="Ann", unsubscribe_url=U)
    assert "Ann" not in mail.html and "Ann" not in mail.text
    assert U not in mail.html.replace(f'href="{U}"', "")
    assert "A &#123;&#123;first_name}} title" in mail.html


@pytest.mark.parametrize("accent", ["red", "#12345g", '#fff" onload="x'])
def test_bad_accent_refused(accent):
    with pytest.raises(ValueError):
        render(inp([]), ctx(branding=Branding(app_name="A", accent=accent, logo_url="")))


def test_logo_and_text_parts():
    blocks = body(
        ("Heading", {"text": "Big", "level": "1"}),
        ("Heading", {"text": "Small"}),
        ("Divider", {}),
        ("ArticleCard", CARD),
    )
    c = ctx(
        branding=Branding(app_name="A&B", accent="#2563eb", logo_url="https://example.org/l?v=1")
    )
    out = render(inp(blocks), c)
    assert re.search(r'<img src="https://example.org/l\?v=1" width="200" alt="A&amp;B"', out.html)
    assert "Big\n===\n" in out.text and "Small\n-----\n" in out.text and "\n----\n" in out.text
    assert (
        "A { {first_name}} title\nShort { {unsubscribe_url}} text\nhttps://acme.example.org/news/a"
        in (out.text)
    )
