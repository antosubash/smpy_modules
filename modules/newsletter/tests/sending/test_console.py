import logging

import pytest
from sm_newsletter.core.settings import NewsletterSettings
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.sending.transport import console, transport_for
from sm_newsletter.sending.transport.console import ConsoleTransport
from sm_newsletter.sending.transport.message import OutgoingMessage
from sm_newsletter.sending.transport.smtp import SmtpTransport


@pytest.fixture(autouse=True)
def _empty_outbox(monkeypatch):
    monkeypatch.setattr(console, "_outbox", {})
    monkeypatch.setattr(console, "_hooks", [])


def _msg(to: str, subject: str = "Hello") -> OutgoingMessage:
    return OutgoingMessage(
        sender="news@example.org",
        to=to,
        subject=subject,
        html="<p>secret body</p>",
        text="secret body",
        reply_to=None,
        headers={"Precedence": "bulk"},
    )


@pytest.mark.unbound_tenant
async def test_capture_is_per_tenant(caplog):
    caplog.set_level(logging.INFO, logger="sm_newsletter")
    transport = ConsoleTransport()
    with tenant_scope("acme"):
        async with transport.session() as session:
            result = await session.send(_msg("a@example.com", "First"))
            await session.send(_msg("b@example.com", "Second"))
    with tenant_scope("globex"):
        async with transport.session() as session:
            await session.send(_msg("c@example.com"))
    assert (result.outcome, result.code) == ("accepted", 250)
    acme = console.captured("acme")
    assert [m.to for m in acme] == ["b@example.com", "a@example.com"]  # newest first
    assert all(m.tenant_id == "acme" for m in acme)
    assert acme[0].headers["Precedence"] == "bulk"
    assert acme[0].text == "secret body"
    assert [m.to for m in console.captured("globex")] == ["c@example.com"]
    assert console.captured("nobody") == []
    assert "a@example.com" in caplog.text and "First" in caplog.text
    assert "secret body" not in caplog.text


async def test_capture_ring_keeps_fifty():
    async with ConsoleTransport().session() as session:
        for i in range(55):
            await session.send(_msg(f"r{i}@example.com"))
    kept = console.captured("default")
    assert len(kept) == 50
    assert kept[0].to == "r54@example.com" and kept[-1].to == "r5@example.com"


async def test_hook_called_and_removed():
    seen = []
    remove = console.add_capture_hook(seen.append)
    async with ConsoleTransport().session() as session:
        await session.send(_msg("a@example.com"))
        remove()
        await session.send(_msg("b@example.com"))
    assert [m.to for m in seen] == ["a@example.com"]
    remove()  # idempotent


async def test_failing_hook_does_not_fail_the_send():
    def boom(_):
        raise RuntimeError("hook broke")

    console.add_capture_hook(boom)
    async with ConsoleTransport().session() as session:
        result = await session.send(_msg("a@example.com"))
    assert result.outcome == "accepted"


def test_transport_for_picks_by_setting():
    assert isinstance(transport_for(NewsletterSettings(transport="console")), ConsoleTransport)
    smtp = transport_for(
        NewsletterSettings(transport="smtp", smtp_username="u", smtp_password="plain-pw")
    )
    assert isinstance(smtp, SmtpTransport)
    assert smtp.name == "smtp" and smtp.supports_list_unsubscribe
    assert "plain-pw" not in repr(smtp)


@pytest.mark.parametrize("subject", ["Hi\u2028there", "Hi\x85there", "Hi\r\nBcc: x@evil.test"])
async def test_bad_header_is_rejected_not_raised(subject):
    # I1: answer like the SMTP session, so the caller closes its attempt row.
    async with ConsoleTransport().session() as session:
        result = await session.send(_msg("a@example.com", subject))
    assert (result.outcome, result.code) == ("rejected", None)
    assert result.detail == "a header value is not valid"
    assert console.captured("default") == []
