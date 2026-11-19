"""The registration mail: text only, every value one line, links from the live base URL (PR 9)."""

from __future__ import annotations

import logging
import re
from types import SimpleNamespace

import pytest
from sm_events.core.tenancy import tenant_scope
from sm_events.models import EventText
from sm_records.public_submissions import mail_runner
from sqlalchemy import update

from tests.support.registration_http import (
    STORED,
    TYPE,
    load_registration,
    reg_links,
    register,
    regs,
    single_opt_in,
)
from tests.support.submissions_http import JSON, SUBMISSIONS

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


async def test_links_never_come_from_request_headers(reg_site):
    """Spoofed forwarded headers change nothing (a spoofed Host is the Origin check's 403): every URL is the configured origin's."""
    spoof = {"X-Forwarded-Host": "evil.example", "Forwarded": "host=evil.example"}
    loaded = (await load_registration(reg_site, reg_site.event)).json()
    resp = await reg_site.post(
        f"{SUBMISSIONS}/{TYPE}/submit",
        json={
            "data": {"sm_email": "g@example.org", "sm_name": "G"},
            "token": loaded["definition"]["token"],
        },
        headers={**JSON, **spoof},
    )
    await mail_runner.drain()
    assert resp.status_code == 202, resp.text
    (message,) = reg_site.outbox.sent
    urls = re.findall(r"https?://\S+", message.text)
    assert urls and all(u.startswith("https://site.example/") for u in urls), urls
    assert "evil" not in message.text


async def test_a_forged_origin_is_refused_by_the_check_and_is_never_output(reg_site):
    token = (await load_registration(reg_site, reg_site.event)).json()["definition"]["token"]
    resp = await reg_site.post(
        f"{SUBMISSIONS}/{TYPE}/submit",
        json={"data": {"sm_email": "g@example.org", "sm_name": "G"}, "token": token},
        headers={**JSON, "Origin": "https://evil.example"},
    )
    assert (resp.status_code, resp.json()["code"]) == (403, "bad_origin")
    assert reg_site.outbox.sent == []


def _app(*, multi, base="https://apex.example", sub="example.org"):
    host = SimpleNamespace(settings=SimpleNamespace(public_base_url=base))
    tenants = SimpleNamespace(settings=SimpleNamespace(subdomain_base=sub))
    return SimpleNamespace(
        state=SimpleNamespace(host=host, tenants=tenants, sm=SimpleNamespace(db=None))
    ), multi


async def test_the_event_base_is_configuration_only(monkeypatch):
    from sm_records.public_submissions.registration import origin

    async def slug(app, tenant_id, db):
        return "acme" if tenant_id == "acme" else None

    monkeypatch.setattr(origin, "_org_slug", slug)
    for multi, tenant, sub, expected in (
        (False, "acme", "example.org", "https://apex.example"),
        (True, "acme", "example.org", "https://acme.example.org"),
        (True, "nobody", "example.org", ""),  # no organisation: no guessed link
        (True, "acme", "", ""),  # no subdomain base configured: none either
    ):
        app, _ = _app(multi=multi, sub=sub)
        monkeypatch.setattr(origin, "_multi_tenant", lambda a, m=multi: m)
        assert await origin.event_base(app, tenant, None) == expected, (multi, tenant, sub)
    app, _ = _app(multi=False, base="")
    monkeypatch.setattr(origin, "_multi_tenant", lambda a: False)
    assert await origin.event_base(app, "acme", None) == ""


def test_no_event_base_means_no_event_links():
    from sm_records.public_submissions.registration import mail as m

    event = SimpleNamespace(
        title="T",
        when_text="soon",
        venue_name=None,
        address=None,
        online_url=None,
        page_path="/events/t",
        ics_path="/events/t.ics",
    )
    rtype = SimpleNamespace(
        tenant_id="default", key="k", public_submissions={"pending_hold_hours": 24}
    )
    record = SimpleNamespace(
        uuid="a" * 32, data={"sm_status": "registered", "sm_email": "a@b.org", "sm_nonce": "n"}
    )
    out = m.message(
        rtype,
        record,
        event,
        secret="s",
        base_url="https://site.example",
        event_base="",
        locale="en",
        ttl_hours=24,
    )
    assert (
        "/events/" not in out.text and "https://site.example/records/submissions/cancel" in out.text
    )


async def test_logs_carry_no_address_or_name(reg_site, caplog):
    with caplog.at_level(logging.DEBUG):
        await register(reg_site, "secret.person@example.org", name="Zed Zebra")
    ours = "\n".join(
        r.getMessage() for r in caplog.records if r.name.startswith(("sm_records", "sm_events"))
    )
    assert "secret.person" not in ours and "Zed Zebra" not in ours
