"""The landing page of a registration's confirm link: its own words, and a state for an event that
filled up or a database that was busy meanwhile (the seat is taken at the confirmation)."""

from __future__ import annotations

import pytest

from tests.support.registration_http import (
    confirm_link_for,
    load_registration,
    reg_links,
    register,
    regs,
    seed_event,
)

pytestmark = pytest.mark.usefixtures("reg_site")
PAGE = "/records/submissions/confirm-registration"
WORDS = ("title", "intro", "button", "done", "already", "expired", "full", "closed", "busy")


async def test_the_confirm_mail_links_to_the_registration_page(reg_site, monkeypatch):
    event = await seed_event(reg_site.db_state, uid="p@x", registration_capacity=5)
    await load_registration(reg_site, event)
    await register(reg_site, "ada@example.org", event=event)
    mail = next(m for m in reg_site.outbox.sent if m.to == "ada@example.org")
    assert "/records/submissions/confirm-registration?t=" in mail.text
    assert "/records/submissions/confirm?" not in mail.text
    assert "confirm" in reg_links(mail)  # the action; the page has its own words


@pytest.mark.parametrize("lang", ["en", "de"])
async def test_the_page_has_registration_words_and_a_state_for_full_closed_and_busy(reg_site, lang):
    event = await seed_event(reg_site.db_state, uid="w@x", registration_capacity=5)
    await load_registration(reg_site, event)
    await register(reg_site, "ada@example.org", event=event)
    token = await confirm_link_for(reg_site, (await regs(reg_site))[0])
    got = await reg_site.get(
        PAGE,
        params={"t": token, "l": lang},
        headers={"X-Inertia": "true", "X-Inertia-Version": "1.0"},
    )
    assert got.status_code == 200 and got.headers["cache-control"] == "no-store"
    props = got.json()["props"]
    assert props["action"] == "confirm" and props["endpoint"].endswith("/submissions/confirm")
    assert set(WORDS) <= set(props["copy"])
    assert "subscription" not in props["copy"]["title"].lower()
    assert all(props["copy"][w] for w in WORDS)
    assert (await regs(reg_site))[0]["data"]["sm_status"] == "pending"  # GET is inert


async def test_the_newsletter_page_keeps_its_own_words(reg_site):
    got = await reg_site.get(
        "/records/submissions/confirm",
        params={"t": "x", "l": "en"},
        headers={"X-Inertia": "true", "X-Inertia-Version": "1.0"},
    )
    assert "subscription" in got.json()["props"]["copy"]["title"].lower()
