"""Cancelling a registration: by link, from the console, never by a GET; the seat goes once."""

from __future__ import annotations

import uuid

import pytest
from sm_events.core.tenancy import tenant_scope
from sm_events.models import RegistrationCount, RegistrationSeat
from sm_records.public_submissions import links
from sqlalchemy import select

from tests.support.app_harness import ADMIN, roles
from tests.support.public_submissions_support import create
from tests.support.registration_http import (
    TYPE,
    follow,
    reg_links,
    register,
    regs,
    seed_event,
    single_opt_in,
)
from tests.support.submissions_http import SUBMISSIONS

pytestmark = pytest.mark.usefixtures("reg_site")
GONE = {"status": "cancelled"}


async def taken(site) -> tuple[int, int]:
    with tenant_scope("default"):
        async with site.db_state.session_factory() as db:
            seats = len(list((await db.execute(select(RegistrationSeat))).scalars()))
            counters = sum(c.taken for c in (await db.execute(select(RegistrationCount))).scalars())
    return seats, counters


async def cancel_token(site) -> str:
    return reg_links(site.outbox.sent[0])["cancel"]["t"]


async def test_cancel_link(reg_site):
    await register(reg_site)
    token = await cancel_token(reg_site)
    before = (await regs(reg_site))[0]["data"]["sm_nonce"]
    resp = await follow(reg_site, "cancel", token)
    assert (resp.status_code, resp.json()) == (200, GONE)
    assert resp.headers["cache-control"] == "no-store"
    (record,) = await regs(reg_site)  # kept, so the organiser sees who cancelled
    assert record["data"]["sm_status"] == "cancelled" and record["data"]["sm_cancelled_at"]
    assert record["data"]["sm_nonce"] != before
    assert await taken(reg_site) == (0, 0)


async def test_every_other_answer_is_the_same_page_and_changes_nothing(reg_site):
    await register(reg_site)
    token = await cancel_token(reg_site)
    other = await seed_event(reg_site.db_state, uid="o@x")
    await register(reg_site, "other@example.org", event=other)
    secret = "submissions-test-secret"
    (record,) = [r for r in await regs(reg_site) if r["data"]["sm_email"] == "guest@example.org"]
    forged = [
        "",
        "junk",
        token[:-2] + "aa",
        links.sign(
            secret,
            links.CANCEL,
            tenant="other",
            type_key=TYPE,
            uuid=record["uuid"],
            nonce=record["data"]["sm_nonce"],
        ),
        links.sign(
            "wrong",
            links.CANCEL,
            tenant="default",
            type_key=TYPE,
            uuid=record["uuid"],
            nonce=record["data"]["sm_nonce"],
        ),
        links.sign(
            secret,
            links.CANCEL,
            tenant="default",
            type_key=TYPE,
            uuid=record["uuid"],
            nonce="not-the-nonce",
        ),
    ]
    before = await taken(reg_site)
    for bad in forged:
        resp = await follow(reg_site, "cancel", bad)
        assert (resp.status_code, resp.json()) == (200, GONE), bad
    assert await taken(reg_site) == before == (2, 2)
    assert (await follow(reg_site, "cancel", token)).json() == GONE
    assert await taken(reg_site) == (1, 1)
    assert (await follow(reg_site, "cancel", token)).json() == GONE  # the second click
    assert await taken(reg_site) == (1, 1)


async def test_an_occurrence_that_has_started_cannot_be_cancelled(reg_site, monkeypatch):
    from datetime import UTC, datetime

    from sm_records.public_submissions.registration import cancel as cancel_module

    await register(reg_site)
    token = await cancel_token(reg_site)
    monkeypatch.setattr(cancel_module, "_now", lambda: datetime(2100, 1, 1, tzinfo=UTC))
    resp = await follow(reg_site, "cancel", token)
    assert (resp.status_code, resp.json()) == (200, GONE)  # the same page
    assert (await regs(reg_site))[0]["data"]["sm_status"] == "pending"
    assert await taken(reg_site) == (1, 1)


async def test_get_is_inert(reg_site):
    await register(reg_site)
    token = await cancel_token(reg_site)
    page = await reg_site.get("/records/submissions/cancel", params={"t": token, "l": "en"})
    assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
    assert (await regs(reg_site))[0]["data"]["sm_status"] == "pending"
    api = await reg_site.get(f"{SUBMISSIONS}/cancel", params={"t": token})
    assert api.status_code in (404, 405)
    assert await taken(reg_site) == (1, 1)


async def test_cancel_after_confirmation_and_register_again(reg_site):
    await single_opt_in(reg_site)
    await register(reg_site, consent=True)
    assert (await follow(reg_site, "cancel", await cancel_token(reg_site))).json() == GONE
    assert await taken(reg_site) == (0, 0)
    assert (await register(reg_site, consent=True)).status_code == 202  # a cancelled one may return
    records = await regs(reg_site)
    assert sorted(r["data"]["sm_status"] for r in records) == ["cancelled", "registered"]
    assert await taken(reg_site) == (1, 1)


async def test_admin_cancel(reg_site):
    await register(reg_site)
    (record,) = await regs(reg_site)
    url = f"/api/records/types/{TYPE}/records/{record['uuid']}/submission/cancel"
    resp = await reg_site.post(url, headers=roles(ADMIN))
    assert resp.status_code == 200 and resp.json()["data"]["sm_status"] == "cancelled"
    assert await taken(reg_site) == (0, 0)
    again = await reg_site.post(url, headers=roles(ADMIN))
    assert again.status_code == 200 and await taken(reg_site) == (0, 0)  # idempotent


async def test_admin_cancel_on_a_form_type_is_wrong_kind(reg_site):
    made = await create(reg_site, "contact")
    assert made.status_code == 201
    missing = uuid.uuid4().hex
    resp = await reg_site.post(
        f"/api/records/types/contact/records/{missing}/submission/cancel", headers=roles(ADMIN)
    )
    assert resp.status_code == 409 and resp.json()["code"] == "wrong_kind"
