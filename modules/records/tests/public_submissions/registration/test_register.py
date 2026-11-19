"""A visitor registers: the record and its seat in one transaction, and one answer (PR 9)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import pytest
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Event, RegistrationCount, RegistrationSeat
from sm_records.public_submissions import tokens
from sm_records.public_submissions.registration import mail as reg_mail
from sqlalchemy import select, update

from tests.support.public_submissions_support import update as update_type
from tests.support.registration_http import (
    ADDRESS,
    STORED,
    TYPE,
    load_registration,
    reg_config,
    register,
    regs,
    seed_event,
)
from tests.support.submissions_http import JSON, SUBMISSIONS

pytestmark = pytest.mark.usefixtures("reg_site")


@pytest.fixture
def mails(monkeypatch):
    """Every confirmation the registration code asked for (Task 10 sends them)."""
    queued: list = []

    async def capture(db, request, rtype, record, event):
        queued.append((record.uuid, event.title))

    monkeypatch.setattr(reg_mail, "queue_registration_mail", capture)
    return queued


async def seats(site) -> tuple[list[RegistrationSeat], list[RegistrationCount]]:
    with tenant_scope("default"):
        async with site.db_state.session_factory() as db:
            return (
                list((await db.execute(select(RegistrationSeat))).scalars()),
                list((await db.execute(select(RegistrationCount))).scalars()),
            )


async def test_registers_pending(reg_site, mails):
    resp = await register(reg_site, data={"diet": "vegan"})
    assert (resp.status_code, resp.json()) == (202, {"ok": True})
    assert resp.headers["cache-control"] == "no-store"
    (record,) = await regs(reg_site)
    data = record["data"]
    assert record["status"] == "draft" and data["diet"] == "vegan"
    assert (data["sm_email"], data["sm_name"], data["sm_status"]) == (STORED, "Ada", "pending")
    assert data["sm_event_id"] == reg_site.event["event_id"]
    assert data["sm_occurrence_key"] == reg_site.event["key"]
    assert (
        data["sm_occurrence_start"].startswith("2099-07-01T08:00")
        and data["sm_event_title"] == "Open day"
    )
    assert data["sm_consent_at"] and data["sm_confirmed_at"] is None and len(data["sm_nonce"]) == 32
    assert data["sm_cancelled_at"] is None
    seat_rows, counters = await seats(reg_site)
    assert [uuid.UUID(s.holder).hex for s in seat_rows] == [record["uuid"]]
    assert counters[0].taken == 1
    assert mails == [(record["uuid"], "Open day")]


async def test_single_opt_in(reg_site, mails):
    off = await update_type(
        reg_site,
        TYPE,
        public_submissions=reg_config(
            double_opt_in=False, consent={"required": True, "text": {"en": "I agree"}}
        ),
    )
    assert off.status_code == 200, off.text
    assert (await register(reg_site)).status_code == 422  # consent not ticked
    assert (await register(reg_site, consent=True)).status_code == 202
    (record,) = await regs(reg_site)
    assert record["data"]["sm_status"] == "registered" and record["data"]["sm_confirmed_at"]
    assert record["data"]["sm_consent_text"] == "I agree"


async def _close_after_token(site, **changes):
    with tenant_scope("default"):
        async with site.db_state.session_factory() as db:
            await db.execute(
                update(Event.__table__)  # type: ignore[attr-defined]
                .where(Event.__table__.c.id == uuid.UUID(site.event["event_id"]))  # type: ignore[attr-defined]
                .values(**changes)
            )
            await db.commit()


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"registration_closes_at": datetime(2020, 1, 1, tzinfo=UTC)}, "registration_closed"),
        ({"cancelled": True}, "registration_closed"),
        ({"status": "draft"}, "event_unavailable"),
        ({"registration_target": "elsewhere"}, "event_unavailable"),
        ({"registration_mode": "external"}, "event_unavailable"),
    ],
)
async def test_refusal_codes(reg_site, mails, changes, code):
    token = (await load_registration(reg_site, reg_site.event)).json()["definition"]["token"]
    await _close_after_token(reg_site, **changes)
    resp = await register(reg_site, token=token)
    assert (resp.status_code, resp.json()["code"]) == (409, code)
    assert await regs(reg_site) == [] and mails == []
    assert await seats(reg_site) == ([], [])


async def test_full_is_refused_and_leaves_no_record(reg_site, mails):
    event = await seed_event(reg_site.db_state, uid="one@x", registration_capacity=1)
    first, second = [
        (await load_registration(reg_site, event)).json()["definition"]["token"] for _ in range(2)
    ]  # both loaded while a seat was free
    assert (await register(reg_site, "a@example.org", event=event, token=first)).status_code == 202
    resp = await register(reg_site, "b@example.org", event=event, token=second)
    assert (resp.status_code, resp.json()["code"]) == (409, "registration_full")
    items = await regs(reg_site)
    assert [r["data"]["sm_email"] for r in items] == ["a@example.org"]
    seat_rows, counters = await seats(reg_site)
    assert len(seat_rows) == 1 and counters[0].taken == 1 and len(mails) == 1


async def test_event_never_from_body(reg_site, mails):
    other = await seed_event(reg_site.db_state, uid="other@x")
    for data in (
        {"sm_event_id": other["event_id"]},
        {"sm_occurrence_key": other["key"]},
        {"event": other["event_id"]},
        {"sm_status": "registered"},
        {"sm_nonce": "x" * 32},
    ):
        resp = await register(reg_site, data=data)
        assert (resp.status_code, resp.json()["code"]) == (422, "unknown_field"), data
    assert await regs(reg_site) == []
    assert (await register(reg_site)).status_code == 202
    (record,) = await regs(reg_site)
    assert record["data"]["sm_event_id"] == reg_site.event["event_id"]


async def test_duplicate_same_answer(reg_site, mails):
    first = await register(reg_site)
    second = await register(reg_site, "GUEST@example.ORG")
    assert (
        (first.status_code, first.text) == (second.status_code, second.text) == (202, '{"ok":true}')
    )
    assert len(await regs(reg_site)) == 1 and len((await seats(reg_site))[0]) == 1
    assert len(mails) == 2  # a pending duplicate is sent its confirmation again


async def test_a_registered_duplicate_queues_nothing(reg_site, mails):
    await update_type(
        reg_site,
        TYPE,
        public_submissions=reg_config(
            double_opt_in=False, consent={"required": True, "text": {"en": "ok"}}
        ),
    )
    await register(reg_site, consent=True)
    again = await register(reg_site, consent=True)
    assert again.status_code == 202 and len(mails) == 1 and len(await regs(reg_site)) == 1


async def test_same_address_other_occurrence(reg_site, mails):
    other = await seed_event(reg_site.db_state, uid="two@x")
    assert (await register(reg_site)).status_code == 202
    assert (await register(reg_site, event=other)).status_code == 202
    assert len(await regs(reg_site)) == 2 and len((await seats(reg_site))[0]) == 2


async def test_cross_tenant_and_form_tokens_are_expired(reg_site, mails):
    from sm_records.public_submissions.registration.tokens import sign_registration

    secret = "submissions-test-secret"
    ev = reg_site.event
    foreign = sign_registration(secret, "a", TYPE, "abc", ev["event_id"], ev["key"], now=1)
    form = tokens.sign_form(secret, "default", TYPE, "abc", now=1)
    for token in (foreign, form, "x.y", ""):
        resp = await register(reg_site, token=token)
        assert (resp.status_code, resp.json()["code"]) == (400, "form_expired"), token
    assert await regs(reg_site) == []


async def test_a_changed_form_is_form_changed(reg_site, mails):
    token = (await load_registration(reg_site, reg_site.event)).json()["definition"]["token"]
    await update_type(
        reg_site,
        TYPE,
        public_submissions=reg_config(consent={"required": True, "text": {"en": "new"}}),
    )
    resp = await register(reg_site, token=token)
    assert resp.status_code == 409 and resp.json()["code"] == "form_changed"
    assert resp.json()["definition"]["kind"] == "registration" and await regs(reg_site) == []


async def test_a_disabled_type_is_closed(reg_site, mails):
    token = (await load_registration(reg_site, reg_site.event)).json()["definition"]["token"]
    await update_type(reg_site, TYPE, public_submissions={**reg_config(), "enabled": False})
    resp = await register(reg_site, token=token)
    assert (resp.status_code, resp.json()["code"]) == (409, "registration_closed")


async def test_validation_is_the_same_whoever_is_registered(reg_site, mails):
    await register(reg_site)
    long = {"diet": "x" * 5000}
    fresh = await register(reg_site, "new@example.org", data=long)
    dup = await register(reg_site, data=long)
    assert fresh.status_code == dup.status_code == 422
    assert fresh.json()["code"] == dup.json()["code"] == "invalid"


async def test_a_failure_after_admit_leaves_neither_seat_nor_record(reg_site, monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("mail queue is down")

    monkeypatch.setattr(reg_mail, "queue_registration_mail", boom)
    resp = await register(reg_site)
    assert resp.status_code == 500
    assert await regs(reg_site) == [] and await seats(reg_site) == ([], [])


async def test_the_form_token_route_still_rejects_other_origins(reg_site, mails):
    token = (await load_registration(reg_site, reg_site.event)).json()["definition"]["token"]
    resp = await reg_site.post(
        f"{SUBMISSIONS}/{TYPE}/submit",
        json={"data": {"sm_email": ADDRESS, "sm_name": "A"}, "token": token},
        headers={**JSON, "Origin": "https://evil.example"},
    )
    assert (resp.status_code, resp.json()["code"]) == (403, "bad_origin")


async def test_logs_carry_no_address_or_name(reg_site, mails, caplog):
    with caplog.at_level(logging.DEBUG):
        await register(reg_site, "secret.person@example.org", name="Zed Zebra")
        await register(
            reg_site, "secret.person@example.org", name="Zed Zebra", data={"diet": "x" * 5000}
        )
    ours = "\n".join(
        r.getMessage() + repr(r.__dict__.get("args", ""))
        for r in caplog.records
        if r.name.startswith(("sm_records", "sm_events"))
    )
    assert "secret.person" not in ours and "Zed Zebra" not in ours
