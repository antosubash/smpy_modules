"""Confirming a registration: a POST of the link, never a GET; pending becomes registered."""

from __future__ import annotations

import time

import pytest
from sm_events.core.tenancy import tenant_scope
from sm_records.contracts.events import SubscriptionChanged
from sm_records.public_submissions import links

from tests.support.public_submissions_support import update
from tests.support.registration_http import TYPE, follow, reg_config, reg_links, register, regs

pytestmark = pytest.mark.usefixtures("reg_site")


async def test_confirm(reg_site):
    seen: list = []

    async def note(event):
        seen.append(event)

    reg_site.app.state.sm.event_bus.subscribe(SubscriptionChanged, note)
    await register(reg_site)
    token = reg_links(reg_site.outbox.sent[0])["confirm"]["t"]
    resp = await follow(reg_site, "confirm", token)
    assert (resp.status_code, resp.json()) == (200, {"status": "confirmed"})
    (record,) = await regs(reg_site)
    assert record["data"]["sm_status"] == "registered" and record["data"]["sm_confirmed_at"]
    again = await follow(reg_site, "confirm", token)
    assert again.json() == {"status": "already_confirmed"}
    assert seen == [], "a registration is not a newsletter subscription"


async def test_the_link_expires_with_the_hold(reg_site):
    await update(reg_site, TYPE, public_submissions=reg_config(pending_hold_hours=1))
    await register(reg_site)
    token = reg_links(reg_site.outbox.sent[0])["confirm"]["t"]
    link = links.parse("submissions-test-secret", links.CONFIRM, token)
    assert link.exp is not None and link.exp - time.time() <= 3600 + 5
    with tenant_scope("default"):
        pass
    resp = await _later(reg_site, token, hours=2)
    assert (resp.status_code, resp.json()["code"]) == (410, "link_expired")
    (record,) = await regs(reg_site)
    assert record["data"]["sm_status"] == "pending"


async def _later(site, token, *, hours):
    import sm_records.public_submissions.links as module

    real = module.time.time
    module.time.time = lambda: real() + hours * 3600  # type: ignore[assignment]
    try:
        return await follow(site, "confirm", token)
    finally:
        module.time.time = real  # type: ignore[assignment]


async def test_a_cancelled_registration_cannot_be_confirmed(reg_site):
    await register(reg_site)
    mail = reg_site.outbox.sent[0]
    found = reg_links(mail)
    assert (await follow(reg_site, "cancel", found["cancel"]["t"])).status_code == 200
    resp = await follow(reg_site, "confirm", found["confirm"]["t"])
    assert (resp.status_code, resp.json()["code"]) == (410, "link_expired")


async def test_forged_and_foreign_links_are_expired(reg_site):
    for token in (
        "",
        "x",
        "a.b.c.d.e.f",
        links.sign(
            "wrong",
            links.CONFIRM,
            tenant="default",
            type_key=TYPE,
            uuid="a" * 32,
            nonce="n",
            exp=int(time.time()) + 99,
        ),
    ):
        resp = await follow(reg_site, "confirm", token)
        assert (resp.status_code, resp.json()["code"]) == (410, "link_expired")
