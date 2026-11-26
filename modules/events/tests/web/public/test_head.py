"""The server-rendered head: escaping, injection, language, autodiscovery."""

from __future__ import annotations

import json
import re

import pytest
from fastapi import Response
from sm_events.web.endpoints.public import _head

SHELL = (
    b'<!doctype html><html lang="en"><head><meta charset="utf-8">'
    b"<title>SimpleModule</title></head><body><div id=app></div></body></html>"
)
EVIL = "</script><script>alert(1)</script>"


def test_json_ld_script_break_out():
    head = _head.event_head(
        title=EVIL,
        description=EVIL,
        canonical="https://x.example/e",
        image=None,
        robots=None,
        json_ld={"@type": "Event", "name": EVIL},
        locale="en",
        alternates=[],
    )
    assert head.count("<script") == 1 and head.count("</script>") == 1
    body = re.search(
        r'<script type="application/ld\+json" data-inertia="json-ld">(.*)</script>', head, re.S
    ).group(1)
    assert json.loads(body)["name"] == EVIL
    assert "<script>alert" not in head  # the title and description are escaped too


@pytest.mark.parametrize("raw", ["<", ">", "&", chr(0x2028), chr(0x2029), "<!--", "]]>", "'", '"'])
def test_safe_json_ld_escapes_the_dangerous_characters(raw):
    out = _head.safe_json_ld({"v": f"a{raw}b"})
    for char in ["<", ">", "&", chr(0x2028), chr(0x2029)]:
        assert char not in out
    assert json.loads(out) == {"v": f"a{raw}b"}


def test_html_comment_escaped():
    out = _head.safe_json_ld({"v": "<!-- x -->"})
    assert "<!--" not in out and json.loads(out)["v"] == "<!-- x -->"


def test_noindex():
    head = _head.event_head(
        title="T", description=None, canonical="https://x/e", image=None,
        robots=_head.ROBOTS_NOINDEX, json_ld=None, locale="en", alternates=[],
    )  # fmt: skip
    assert '<meta name="robots" data-inertia="robots" content="noindex,nofollow">' in head
    ok = _head.event_head(
        title="T", description=None, canonical="https://x/e", image=None,
        robots=None, json_ld=None, locale="en", alternates=[],
    )  # fmt: skip
    assert "robots" not in ok


def test_canonical_and_hreflang_escaped():
    head = _head.event_head(
        title='A "quoted" <b>',
        description='x"y',
        canonical='https://x.example/e?date=1&a="b"',
        image=None,
        robots=None,
        json_ld=None,
        locale="de",
        alternates=[
            {"locale": "en", "url": "https://x.example/e"},
            {"locale": "x-default", "url": 'https://x.example/e"'},
        ],
    )
    assert (
        '<link rel="canonical" data-inertia="canonical" '
        'href="https://x.example/e?date=1&amp;a=&quot;b&quot;">'
    ) in head
    assert 'hreflang="x-default" href="https://x.example/e&quot;"' in head
    assert "<title>A &quot;quoted&quot; &lt;b&gt;</title>" in head
    assert '<meta property="og:type" data-inertia="og:type" content="website">' in head
    assert '<meta property="og:locale" data-inertia="og:locale" content="de">' in head
    assert "<b>" not in head


def test_feed_autodiscovery_type_text_calendar():
    head = _head.listing_head(
        title="Events", description="d", canonical="https://x/events/", feed_url="https://x/events/calendar.ics",
        locale="en", alternates=[],
    )  # fmt: skip
    assert 'type="text/calendar"' in head and 'href="https://x/events/calendar.ics"' in head
    assert "rss" not in head


def test_inject_replaces_shell_title():
    response = Response(SHELL, media_type="text/html")
    _head.inject(response, "<title>Mine</title><meta name=x>")
    body = response.body.decode()
    assert body.count("<title>") == 1 and "SimpleModule" not in body
    assert body.index("<title>Mine</title>") < body.index("</head>")
    assert response.headers["content-length"] == str(len(response.body))


def test_inject_leaves_json_and_empty_bodies_alone():
    json_response = Response(b'{"a": 1}', media_type="application/json")
    assert _head.inject(json_response, "<title>x</title>").body == b'{"a": 1}'
    empty = Response(status_code=304)
    assert _head.inject(empty, "<title>x</title>") is empty


def test_set_html_lang_keeps_shell_lang():
    response = Response(SHELL, media_type="text/html")
    _head.set_html_lang(response, "de")
    assert b'<html lang="de" data-shell-lang="en">' in response.body
    assert response.headers["content-length"] == str(len(response.body))


def test_set_html_lang_escapes_the_locale():
    response = Response(SHELL, media_type="text/html")
    _head.set_html_lang(response, 'de"><script>')
    assert b"<script>" not in response.body


def test_no_executable_script():
    head = _head.event_head(
        title="T", description="d", canonical="https://x/e", image="https://x/i.png",
        robots=None, json_ld={"@type": "Event"}, locale="en", alternates=[],
    )  # fmt: skip
    scripts = re.findall(r"<script[^>]*>", head)
    assert scripts == ['<script type="application/ld+json" data-inertia="json-ld">']


def test_json_ld_carries_the_request_nonce():
    head = _head.event_head(
        title="T", description=None, canonical=None, image=None, robots=None,
        json_ld={"@type": "Event"}, locale="en", alternates=[], nonce='abc"def',
    )  # fmt: skip
    assert '<script type="application/ld+json" data-inertia="json-ld" nonce="abc&quot;def">' in head
    plain = _head.event_head(
        title="T", description=None, canonical=None, image=None, robots=None,
        json_ld={"@type": "Event"}, locale="en", alternates=[],
    )  # fmt: skip
    assert "nonce" not in plain
