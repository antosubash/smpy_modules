"""The message a transport sends, and its MIME form.

``sender``, ``to`` and ``reply_to`` are header values (``"Name <a@b>"`` or a
bare address); the SMTP envelope takes the address part. Every header value -
and every extra header's name - is checked with
:func:`~sm_newsletter.core.headers.check_header_text`, so a line break in a
subject is a ``ValueError`` (naming the field, never the value) rather than an
injected header.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime, make_msgid, parseaddr

from sm_newsletter.core.clock import utcnow
from sm_newsletter.core.headers import check_header_text


@dataclass(frozen=True)
class OutgoingMessage:
    sender: str
    to: str
    subject: str
    html: str
    text: str
    reply_to: str | None
    headers: Mapping[str, str]
    # "campaign=<id> send=<id>" or "test campaign=<id>": for logs only, never a header.
    ref: str = ""


# Headers build_mime sets itself; an extra header may not replace them.
_RESERVED = frozenset(
    {
        "from",
        "to",
        "cc",
        "bcc",
        "sender",
        "subject",
        "reply-to",
        "message-id",
        "date",
        "mime-version",
    }
)


def envelope_address(value: str) -> str:
    """The bare address of a ``From``/``To`` header value."""
    return parseaddr(value)[1] or value


def _domain(sender: str) -> str:
    _, at, domain = envelope_address(sender).rpartition("@")
    return domain if at and domain else "localhost"


def build_mime(msg: OutgoingMessage) -> EmailMessage:
    """``multipart/alternative`` (text, then HTML) with ``Message-ID`` and ``Date``."""
    check_header_text(msg.sender, field="sender")
    check_header_text(msg.to, field="to")
    check_header_text(msg.subject, field="subject")
    if msg.reply_to is not None:
        check_header_text(msg.reply_to, field="reply_to")
    for name, value in msg.headers.items():
        check_header_text(name, field="header name")
        if ":" in name or " " in name or not name:
            raise ValueError("header name must be a non-empty token without ':' or spaces")
        if name.lower() in _RESERVED or name.lower().startswith("content-"):
            raise ValueError(f"header {name} is set by the message itself")
        check_header_text(value, field=f"header {name}")

    mime = EmailMessage(policy=SMTP)
    mime["From"] = msg.sender
    mime["To"] = msg.to
    if msg.reply_to:
        mime["Reply-To"] = msg.reply_to
    mime["Subject"] = msg.subject
    mime["Date"] = format_datetime(utcnow())
    mime["Message-ID"] = make_msgid(domain=_domain(msg.sender))
    for name, value in msg.headers.items():
        mime[name] = value
    # Quoted-printable keeps the body 7-bit: no 8BITMIME needed, at any relay.
    mime.set_content(msg.text, cte="quoted-printable")
    mime.add_alternative(msg.html, subtype="html", cte="quoted-printable")
    return mime


def unsubscribe_headers(url: str) -> dict[str, str]:
    """RFC 2369 / RFC 8058 one-click unsubscribe headers for ``url``."""
    check_header_text(url, field="unsubscribe url")
    return {
        "List-Unsubscribe": f"<{url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        "Precedence": "bulk",
    }
