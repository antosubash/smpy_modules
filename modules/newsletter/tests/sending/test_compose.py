"""Composing one recipient's message from the render snapshot (no database)."""

from __future__ import annotations

import re

import pytest
from sm_newsletter.core import tokens
from sm_newsletter.models import CampaignRender, Send
from sm_newsletter.sending.compose import compose

from tests.support.campaign_world import RENDER_HTML, RENDER_TEXT, SENDER
from tests.support.sending import BASE_URL, NOW

SECRET = "compose-secret"
_URL = re.compile(r"https://news\.example\.org/[^\s\"<>]+")


def _render(**overrides) -> CampaignRender:
    values = {
        "tenant_id": "org.a",
        "campaign_id": 7,
        "subject": "Hello {{first_name|there}}",
        "html": RENDER_HTML,
        "text": RENDER_TEXT,
        "sender": SENDER,
        "reply_to": None,
        "public_base": BASE_URL,
        "locale": "en",
        "rendered_at": NOW,
    }
    return CampaignRender(**{**values, **overrides})


def _send(first_name: str | None = "Ada") -> Send:
    return Send(
        id=42,
        tenant_id="org.a",
        campaign_id=7,
        record_uuid="u" * 32,
        email="ada.lovelace@example.com",
        first_name=first_name,
    )


def _compose(send: Send | None = None, *, list_unsubscribe: bool = True):
    return compose(_render(), send or _send(), secret=SECRET, list_unsubscribe=list_unsubscribe)


def test_first_name_or_fallback():
    assert _compose().subject == "Hello Ada"
    assert "Hi Ada" in _compose().text
    plain = _compose(_send(first_name=None))
    assert plain.subject == "Hello there"
    assert "<p>Hi there</p>" in plain.html


def test_one_unsubscribe_url_everywhere_carrying_the_send():
    msg = _compose()
    (in_html,) = _URL.findall(msg.html)
    (in_text,) = _URL.findall(msg.text)
    assert in_html == in_text
    assert msg.headers["List-Unsubscribe"] == f"<{in_text}>"
    token = in_text.rsplit("/", 1)[1]
    assert tokens.parse(SECRET, token) == tokens.SendToken("org.a", 7, 42)


def test_the_address_is_not_in_the_url():
    url = _URL.findall(_compose().text)[0]
    assert "ada" not in url.lower()
    assert "example.com" not in url


def test_addressing_and_ref():
    msg = _compose()
    assert (msg.to, msg.sender, msg.reply_to) == ("ada.lovelace@example.com", SENDER, None)
    assert msg.ref == "campaign=7 send=42"


def test_a_first_name_with_a_line_break_is_flattened():
    msg = _compose(_send(first_name="Ada\r\nBcc: x@evil.test"))
    assert msg.subject == "Hello Ada Bcc: x@evil.test"
    assert "\r" not in msg.subject and "\n" not in msg.subject


def test_an_invalid_header_is_a_value_error():
    with pytest.raises(ValueError, match="subject"):
        compose(_render(subject="Hi\r\nBcc: x"), _send(), secret=SECRET, list_unsubscribe=True)


def test_no_list_headers_without_support():
    assert dict(_compose(list_unsubscribe=False).headers) == {}


def test_one_click_and_bulk_headers():
    headers = _compose().headers
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert headers["Precedence"] == "bulk"
