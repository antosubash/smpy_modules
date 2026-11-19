"""The registration mail: text only, every value one line, links from the live base URL (PR 9)."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from sm_events.core.tenancy import tenant_scope
from sm_events.models import EventText
from sm_records.public_submissions.registration import mail
from sqlalchemy import update

from tests.support.registration_http import (
    STORED,
    reg_links,
    register,
    regs,
    single_opt_in,
)

pytestmark = pytest.mark.usefixtures("reg_site")


async def test_pending_mail(reg_site):
    assert (await register(reg_site, data={"diet": "vegan"})).status_code == 202
    (message,) = reg_site.outbox.sent
    assert message.to == STORED and message.html is None
    assert "Open day" in message.subject and "\n" not in message.subject
    text = message.text
    assert "Open day" in text and "2099" in text and "Europe" not in text
    assert "https://site.example/events/open-day-" in text and ".ics" in text
    found = reg_links(message)
    assert set(found) == {"confirm", "cancel"}
    (record,) = await regs(reg_site)
    assert record["data"]["sm_confirm_sent_at"], "the mark is written once the mail is out"
    assert record["data"]["sm_nonce"] not in text and "vegan" not in text


async def test_registered_mail_has_no_confirm_link(reg_site):
    await single_opt_in(reg_site)
    await register(reg_site, consent=True)
    (message,) = reg_site.outbox.sent
    assert set(reg_links(message)) == {"cancel"}


async def test_the_mail_speaks_the_registrants_language(reg_site):
    await register(reg_site, locale="de")
    (message,) = reg_site.outbox.sent
    assert "Anmeldung" in message.subject
    assert reg_links(message)["confirm"]["l"] == "de"


async def test_a_hostile_title_cannot_split_the_subject(reg_site):
    with tenant_scope("default"):
        async with reg_site.db_state.session_factory() as db:
            await db.execute(
                update(EventText.__table__).values(
                    title="Open\r\nBcc: evil@example.org " + "x" * 200
                )  # type: ignore[attr-defined]
            )
            await db.commit()
    await register(reg_site)
    (message,) = reg_site.outbox.sent
    assert "\r" not in message.subject and "\n" not in message.subject
    assert len(message.subject) <= 200
    assert not any(line.startswith("Bcc:") for line in message.text.splitlines())


def _request(origin: str | None) -> SimpleNamespace:
    headers = {} if origin is None else {"origin": origin}
    app = SimpleNamespace(
        state=SimpleNamespace(
            host=SimpleNamespace(settings=SimpleNamespace(public_base_url="https://apex.example"))
        )
    )
    return SimpleNamespace(app=app, headers=headers)


def test_multi_tenant_origin(monkeypatch):
    monkeypatch.setattr(mail, "_multi_tenant", lambda app: True)
    assert mail.event_base_url(_request("https://acme.example")) == "https://acme.example"
    assert mail.event_base_url(_request(None)) == "https://apex.example"
    monkeypatch.setattr(mail, "_multi_tenant", lambda app: False)
    assert mail.event_base_url(_request("https://acme.example")) == "https://apex.example"


async def test_logs_carry_no_address_or_name(reg_site, caplog):
    with caplog.at_level(logging.DEBUG):
        await register(reg_site, "secret.person@example.org", name="Zed Zebra")
    ours = "\n".join(
        r.getMessage() for r in caplog.records if r.name.startswith(("sm_records", "sm_events"))
    )
    assert "secret.person" not in ours and "Zed Zebra" not in ours
