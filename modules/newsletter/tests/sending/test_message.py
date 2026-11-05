import pytest
from sm_newsletter.sending.transport.message import (
    OutgoingMessage,
    build_mime,
    unsubscribe_headers,
)


def _msg(**overrides) -> OutgoingMessage:
    values = {
        "sender": "News Desk <news@example.org>",
        "to": "reader@example.com",
        "subject": "Grüße from the desk",
        "html": "<p>Hello <b>reader</b></p>",
        "text": "Hello reader",
        "reply_to": "desk@example.org",
        "headers": {},
    }
    values.update(overrides)
    return OutgoingMessage(**values)


def test_alternative_parts_order():
    mime = build_mime(_msg())
    assert mime.get_content_type() == "multipart/alternative"
    parts = list(mime.iter_parts())
    assert [p.get_content_type() for p in parts] == ["text/plain", "text/html"]
    assert parts[0].get_content().strip() == "Hello reader"
    assert "<b>reader</b>" in parts[1].get_content()
    assert mime["From"] == "News Desk <news@example.org>"
    assert mime["To"] == "reader@example.com"
    assert mime["Reply-To"] == "desk@example.org"
    assert mime["Subject"] == "Grüße from the desk"
    assert mime["Date"]
    assert all(p["Content-Transfer-Encoding"] == "quoted-printable" for p in parts)


def test_reply_to_omitted_when_none():
    assert build_mime(_msg(reply_to=None))["Reply-To"] is None


def test_unsubscribe_headers_exact():
    url = "https://example.org/newsletter/u/test"
    assert unsubscribe_headers(url) == {
        "List-Unsubscribe": "<https://example.org/newsletter/u/test>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        "Precedence": "bulk",
    }
    mime = build_mime(_msg(headers=unsubscribe_headers(url)))
    assert mime["List-Unsubscribe"] == "<https://example.org/newsletter/u/test>"
    assert mime["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert mime["Precedence"] == "bulk"


@pytest.mark.parametrize(
    "overrides",
    [
        {"subject": "Hi\r\nBcc: victim@example.com"},
        {"to": "reader@example.com\nBcc: x@example.com"},
        {"sender": "a@example.org\r"},
        {"reply_to": "r@example.org\n"},
        {"subject": "tab\there"},
        {"headers": {"X-Campaign": "1\r\nBcc: x@example.com"}},
        {"headers": {"X-Bad\r\nName": "1"}},
        {"headers": {"X-Bad: Name": "1"}},
    ],
)
def test_crlf_header_refused(overrides):
    with pytest.raises(ValueError) as exc:
        build_mime(_msg(**overrides))
    assert "victim@example.com" not in str(exc.value)
    assert "x@example.com" not in str(exc.value)


def test_unsubscribe_url_with_line_break_refused():
    with pytest.raises(ValueError):
        unsubscribe_headers("https://example.org/u\r\nBcc: x@example.com")


def test_message_id_domain():
    first = build_mime(_msg())["Message-ID"]
    second = build_mime(_msg())["Message-ID"]
    assert first.startswith("<") and first.endswith("@example.org>")
    assert first != second


def test_message_id_without_sender_domain_falls_back():
    assert build_mime(_msg(sender="nobody"))["Message-ID"].endswith("@localhost>")


@pytest.mark.parametrize(
    "name",
    ["From", "to", "Subject", "Reply-To", "Message-ID", "date", "MIME-Version", "Content-Type"],
)
def test_extra_header_cannot_replace_structural_ones(name):
    with pytest.raises(ValueError):
        build_mime(_msg(headers={name: "x"}))
