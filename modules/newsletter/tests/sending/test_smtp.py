"""The SMTP transport against an in-process aiosmtpd relay (see ``conftest.py``)."""

import logging
import socket
import ssl
from dataclasses import replace
from email import message_from_bytes

import pytest
from sm_newsletter.core.errors import TransportUnavailable
from sm_newsletter.sending.transport.message import OutgoingMessage, unsubscribe_headers

from tests.sending.conftest import PASSWORD, USERNAME


def _msg(to: str, **overrides) -> OutgoingMessage:
    values = {
        "sender": "News Desk <news@example.org>",
        "to": to,
        "subject": "Weekly",
        "html": "<p>Hello</p>\n<p>.leading dot</p>",
        "text": "Hello\n.leading dot",
        "reply_to": None,
        "headers": unsubscribe_headers("https://example.org/newsletter/u/test"),
    }
    values.update(overrides)
    return OutgoingMessage(**values)


@pytest.fixture
def secrets_logged(caplog):
    caplog.set_level(logging.DEBUG, logger="sm_newsletter")
    caplog.set_level(logging.DEBUG, logger="aiosmtplib")
    return caplog


async def test_accepted_and_headers_arrive(relay, make_transport):
    _, rec = relay
    async with make_transport().session() as session:
        result = await session.send(_msg("reader@example.com"))
    assert result.outcome == "accepted"
    assert result.code == 250
    assert len(rec.delivered) == 1
    envelope = rec.delivered[0]
    assert envelope.mail_from == "news@example.org"
    assert envelope.rcpt_tos == ["reader@example.com"]
    arrived = message_from_bytes(envelope.original_content)
    assert arrived["Subject"] == "Weekly"
    assert arrived["List-Unsubscribe"] == "<https://example.org/newsletter/u/test>"
    assert arrived["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert arrived["Message-ID"].endswith("@example.org>")
    text = arrived.get_payload()[0].get_payload(decode=True).decode()
    assert ".leading dot" in text  # dot-stuffing was undone by the server


async def test_rcpt_550_rejected_with_code(relay, make_transport):
    _, rec = relay
    async with make_transport().session() as session:
        rejected = await session.send(_msg("bounce@example.com"))
        accepted = await session.send(_msg("second@example.com"))
    assert rejected.outcome == "rejected"
    assert rejected.code == 550
    assert "5.1.1" in rejected.detail
    # RSET cleared the failed envelope; the second transaction is its own.
    assert "RSET" in rec.commands
    assert accepted.outcome == "accepted"
    assert [e.rcpt_tos for e in rec.delivered] == [["second@example.com"]]


async def test_451_rejected_with_code(relay, make_transport):
    _, rec = relay
    async with make_transport().session() as session:
        result = await session.send(_msg("soft@example.com"))
        after = await session.send(_msg("next@example.com"))
    assert (result.outcome, result.code) == ("rejected", 451)
    assert after.outcome == "accepted"
    assert [e.rcpt_tos for e in rec.delivered] == [["next@example.com"]]


async def test_disconnect_at_rcpt_failed_then_reconnects(relay, make_transport):
    _, rec = relay
    async with make_transport(timeout=2.0).session() as session:
        dropped = await session.send(_msg("droprcpt@example.com"))
        recovered = await session.send(_msg("after@example.com"))
    assert dropped.outcome == "failed"
    assert dropped.code is None
    assert recovered.outcome == "accepted"
    assert [e.rcpt_tos for e in rec.delivered] == [["after@example.com"]]


async def test_disconnect_during_data_unknown(relay, make_transport):
    _, rec = relay
    async with make_transport(timeout=2.0).session() as session:
        result = await session.send(_msg("dropdata@example.com"))
        after = await session.send(_msg("after@example.com"))
    assert result.outcome == "unknown"
    assert result.code is None
    assert after.outcome == "accepted"
    assert [e.rcpt_tos for e in rec.delivered] == [["after@example.com"]]


async def test_reconnect_failure_is_failed_not_raised(make_transport):
    transport = make_transport(timeout=2.0)
    async with transport.session() as session:
        await session.send(_msg("droprcpt@example.com"))
        transport._config = replace(transport._config, port=_closed_port())  # reconnect fails
        result = await session.send(_msg("after@example.com"))
    assert result.outcome == "failed"
    assert "connect" in result.detail


async def test_auth_failure_raises_transport_unavailable_without_password_in_detail(
    make_transport, secrets_logged
):
    wrong = "wrong-" + PASSWORD
    with pytest.raises(TransportUnavailable) as exc:
        async with make_transport(password=wrong).session():
            pass
    assert exc.value.status == 502
    assert exc.value.code == "transport_unavailable"
    assert "auth" in exc.value.detail
    for secret in (wrong, PASSWORD, USERNAME):
        assert secret not in exc.value.detail
        assert secret not in str(exc.value)
        assert secret not in secrets_logged.text
    assert exc.value.__cause__ is None and exc.value.__suppress_context__


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def test_connect_failure_names_stage(make_transport):
    with pytest.raises(TransportUnavailable) as exc:
        async with make_transport(port=_closed_port(), timeout=2.0).session():
            pass
    assert "connect" in exc.value.detail


async def test_untrusted_certificate_names_tls_stage(relay):
    from sm_newsletter.sending.transport.smtp import SmtpConfig, SmtpTransport

    port, _ = relay
    config = SmtpConfig(
        host="127.0.0.1", port=port, security="starttls", username="", password="", timeout=2.0
    )
    with pytest.raises(TransportUnavailable) as exc:
        async with SmtpTransport(config, tls_context=ssl.create_default_context()).session():
            pass
    assert "tls" in exc.value.detail


async def test_no_login_without_username(make_transport):
    async with make_transport(username="", password="").session() as session:
        result = await session.send(_msg("reader@example.com"))
    # The relay requires no AUTH, so an anonymous session still delivers.
    assert result.outcome == "accepted"


async def test_non_ascii_address_rejected_and_session_continues(relay, make_transport):
    _, rec = relay
    async with make_transport().session() as session:
        refused = await session.send(_msg("jürgen@example.com"))
        after = await session.send(_msg("after@example.com", subject="Grüße"))
    assert (refused.outcome, refused.code) == ("rejected", None)
    assert after.outcome == "accepted"
    assert [e.rcpt_tos for e in rec.delivered] == [["after@example.com"]]
    assert all(b < 0x80 for b in rec.delivered[0].original_content)  # 7-bit on the wire
