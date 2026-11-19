"""The VEVENT's own URL (kept only when it is a web address) and the single-line cleaner."""

from __future__ import annotations

import pytest
from sm_events.feeds.importing.text import clean_line

from tests.feeds.importing.mapping import event, one


@pytest.mark.parametrize(
    ("line", "kept"),
    [
        ("URL:https://a.example/x", "https://a.example/x"),
        ("URL:http://a.example/x?y=1", "http://a.example/x?y=1"),
        ("URL:javascript:alert(1)", None),
        ("URL:data:text/html,<b>x</b>", None),
        ("URL:https://a.example/with space", None),
        ("URL:https://user:pw@a.example/x", None),
        ("URL:/relative", None),
        ("URL:", None),
    ],
)
def test_mapped_url_http_only(line, kept):
    assert one(*event("a@x", line)).event.url == kept


def test_no_url_is_none():
    assert one(*event("a@x")).event.url is None


def test_a_url_over_the_limit_is_dropped():
    assert one(*event("a@x", "URL:https://a.example/" + "x" * 2100)).event.url is None


def test_clean_line():
    assert clean_line("Tal\u202ek\x00\x07 \u200b  on\n\n tests\u2028", 300) == "Talk on tests"
    assert clean_line("x" * 201, 200) == "x" * 200
    assert clean_line(" \x00 ", 200) == ""
