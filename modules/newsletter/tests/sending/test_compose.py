"""Composing one recipient's message from the render snapshot (no database)."""

from __future__ import annotations

import re
from html.parser import HTMLParser

import pytest
from sm_newsletter.core import tokens
from sm_newsletter.models import CampaignRender, Send
from sm_newsletter.sending.compose import compose
from sm_newsletter.tracking.rewrite import TRACKING_OFF, Tracking

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
    assert tokens.parse(SECRET, token, purpose="u") == tokens.SendToken("org.a", 7, 42)


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


LINK = "https://example.com/story?a=1&b=2"
TRACKED = (
    '<p>Hi {{first_name|there}}</p><a href="{{link:1}}">Story</a>'
    '<a href="{{unsubscribe_url}}">Unsubscribe</a>{{open_pixel}}'
)
ON = Tracking(opens=True, clicks=True)


def _tracked(send: Send | None = None, *, tracking: Tracking = ON, html: str = TRACKED):
    return compose(
        _render(html=html),
        send or _send(),
        secret=SECRET,
        list_unsubscribe=True,
        tracking=tracking,
        links={1: LINK},
    )


def _token(url: str) -> str:
    return url.split("/newsletter/")[1].split("/")[1].removesuffix(".gif")


def test_compose_tracking_tokens_are_purpose_bound():
    msg = _tracked()
    (click,) = re.findall(r'href="(https://news\.example\.org/newsletter/c/[^"]+)"', msg.html)
    (pixel,) = re.findall(r'src="(https://news\.example\.org/newsletter/o/[^"]+)"', msg.html)
    assert pixel.endswith(".gif") and click.endswith("/1")
    c, o = _token(click), _token(pixel)
    u = msg.headers["List-Unsubscribe"].strip("<>").rsplit("/", 1)[1]
    want = tokens.SendToken("org.a", 7, 42)
    for purpose, token in (("c", c), ("o", o), ("u", u)):
        assert tokens.parse(SECRET, token, purpose=purpose) == want
        for other in {"c", "o", "u"} - {purpose}:
            assert tokens.parse(SECRET, token, purpose=other) is None
    assert len({c, o, u}) == 3
    assert "/newsletter/c/" not in msg.text and "/newsletter/o/" not in msg.text


def test_compose_tracking_off_restores_links():
    msg = _tracked(tracking=TRACKING_OFF)
    assert 'href="https://example.com/story?a=1&amp;b=2"' in msg.html
    assert "/newsletter/o/" not in msg.html and "/newsletter/c/" not in msg.html
    assert "{{" not in msg.html


class _Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict]] = []
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def test_recipient_data_cannot_add_tracking():
    hostile = '{{open_pixel}} {{link:0}} "><img width="1">'
    html = (
        '<p>{{first_name|there}}</p><img src="https://example.com/x.png" alt="{{first_name}}">'
        '<a href="{{link:1}}">Story</a>{{open_pixel}}'
    )
    msg = _tracked(_send(first_name=hostile), html=html)
    parsed = _Tags()
    parsed.feed(msg.html)
    pixels = [a for t, a in parsed.tags if t == "img" and a.get("width") == "1"]
    assert len(pixels) == 1 and "/newsletter/o/" in pixels[0]["src"]
    hrefs = [a["href"] for t, a in parsed.tags if t == "a"]
    assert len(hrefs) == 1 and "/newsletter/c/" in hrefs[0]
    (alt_img,) = [a for t, a in parsed.tags if t == "img" and "alt" in a and a.get("alt")]
    assert alt_img["alt"] == hostile.strip()
    assert "{{open_pixel}}" in "".join(parsed.text)
    assert msg.html.count("/newsletter/c/") == 1 and msg.html.count("/newsletter/o/") == 1


def test_compose_default_is_untracked():
    msg = _compose()
    assert "/newsletter/o/" not in msg.html and "/newsletter/c/" not in msg.html
    assert "<p>Hi Ada</p>" in msg.html


def test_subject_never_tracked():
    msg = compose(
        _render(subject="Hi {{open_pixel}} {{link:1}}"),
        _send(),
        secret=SECRET,
        list_unsubscribe=True,
        tracking=ON,
        links={1: LINK},
    )
    assert msg.subject == "Hi {{open_pixel}} {{link:1}}"
