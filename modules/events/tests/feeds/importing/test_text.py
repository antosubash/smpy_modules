"""Text from a file: stripped of what a single line refuses, escaped, then sanitised."""

from __future__ import annotations

from sm_events.core import constants
from sm_events.feeds.importing.text import clean_title, description_html, unescape, venue


def test_title_cleanup():
    title, notes = clean_title("Tal\u202ek\x00\x07 \u200b  on\n\n tests\u2028")
    assert title == "Talk on tests" and notes == ()
    long, _ = clean_title("x" * 301)
    assert len(long) == 300
    empty, notes = clean_title(" ‮ \x00 ")
    assert empty == constants.IMPORT_UNTITLED and notes == ("untitled",)
    assert clean_title("")[1] == ("untitled",)


def test_unescape_text_values():
    assert unescape(r"a\, b\; c\\d\nE\Nf") == "a, b; c\\d\nE\nf"
    assert unescape("plain") == "plain"
    assert unescape("trailing\\") == "trailing\\"


def test_paragraphs():
    html, notes = description_html("a\n\nb\nc", None)
    assert html == "<p>a</p><p>b<br>c</p>" and notes == ()
    assert description_html("", None)[0] == ""
    assert description_html("  \n\n ", None)[0] == ""


def test_html_in_plain_is_escaped():
    html, _ = description_html('<script>alert(1)</script> <img src=x onerror=y> & "q"', None)
    assert "<script" not in html and "<img" not in html
    assert "&lt;script&gt;" in html and "&amp;" in html


def test_url_appended_http_only():
    html, _ = description_html("Hello", "https://example.org/a?b=1&c=2")
    assert html.endswith(
        '<p><a href="https://example.org/a?b=1&amp;c=2">https://example.org/a?b=1&amp;c=2</a></p>'
    )
    for bad in (
        "javascript:alert(1)",
        "data:text/html,x",
        "ftp://x",
        "//example.org",
        "http://exa mple.org",
        "https://x\n.org",
    ):
        assert "href" not in description_html("Hello", bad)[0], bad
    assert (
        "href" not in description_html("Hello", "https://example.org/" + "a" * constants.URL_MAX)[0]
    )


def test_description_truncated():
    html, notes = description_html("x" * (constants.IMPORT_DESCRIPTION_MAX + 50), None)
    assert notes == ("description_truncated",)
    assert html.count("x") == constants.IMPORT_DESCRIPTION_MAX
    assert description_html("x" * constants.IMPORT_DESCRIPTION_MAX, None)[1] == ()


def test_control_characters_never_reach_the_html():
    html, _ = description_html("a\x00b\x07c‮d\x1b", None)
    assert html == "<p>abcd</p>"


def test_venue():
    assert venue("  Room\x00 1‮ ") == "Room 1"
    assert venue("x" * 500) == "x" * constants.VENUE_MAX
    assert venue("‮\x00") is None and venue("") is None
