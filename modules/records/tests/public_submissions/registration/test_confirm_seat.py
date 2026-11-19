"""On a double opt-in form the seat is taken when the address is confirmed, not at submit."""

from __future__ import annotations

import pytest

from tests.support.registration_http import (
    confirm_record,
    load_registration,
    register,
    regs,
    seat_counts,
    seed_event,
    single_opt_in,
)

pytestmark = pytest.mark.usefixtures("reg_site")


async def token(site, event):
    return (await load_registration(site, event)).json()["definition"]["token"]


async def test_a_submit_takes_no_seat_and_the_count_does_not_move(reg_site):
    event = await seed_event(
        reg_site.db_state, uid="n@x", registration_capacity=3, registration_show_seats=True
    )
    tokens = [await token(reg_site, event) for _ in range(50)]
    before = (await load_registration(reg_site, event)).json()["availability"]
    for n in range(50):
        got = await register(reg_site, f"p{n}@example.org", event=event, token=tokens[n])
        assert got.status_code == 202
    after = (await load_registration(reg_site, event)).json()["availability"]
    assert before == after and after["seats_left"] == 3 and after["state"] == "open"
    from tests.support.app_harness import ADMIN, roles
    from tests.support.registration_http import TYPE

    listed = await reg_site.get(f"/api/records/types/{TYPE}/records", headers=roles(ADMIN))
    assert listed.json()["total"] == 50 and await seat_counts(reg_site) == (0, 0)


async def test_confirming_takes_the_seat_and_the_fourth_is_told_it_is_full(reg_site):
    event = await seed_event(reg_site.db_state, uid="c@x", registration_capacity=3)
    tokens = [await token(reg_site, event) for _ in range(5)]
    for n in range(5):
        await register(reg_site, f"p{n}@example.org", event=event, token=tokens[n])
    items = sorted(await regs(reg_site), key=lambda r: r["data"]["sm_email"])
    codes = []
    for record in items:
        got = await confirm_record(reg_site, record)
        codes.append(got.status_code if got.status_code == 200 else got.json()["code"])
    assert codes == [200, 200, 200, "registration_full", "registration_full"]
    statuses = [
        r["data"]["sm_status"]
        for r in sorted(await regs(reg_site), key=lambda r: r["data"]["sm_email"])
    ]
    assert statuses == ["registered"] * 3 + ["pending"] * 2  # the rest are left to expire
    assert await seat_counts(reg_site) == (3, 3)


async def test_a_declined_confirm_leaves_nothing_behind(reg_site):
    """V3, confirm path: the admit declines after the page said open: still pending, no seat."""
    event = await seed_event(reg_site.db_state, uid="d@x", registration_capacity=1)
    tokens = [await token(reg_site, event) for _ in range(2)]
    await register(reg_site, "a@example.org", event=event, token=tokens[0])
    await register(reg_site, "b@example.org", event=event, token=tokens[1])
    a, b = sorted(await regs(reg_site), key=lambda r: r["data"]["sm_email"])
    assert (await confirm_record(reg_site, a)).status_code == 200
    declined = await confirm_record(reg_site, b)
    assert (declined.status_code, declined.json()["code"]) == (409, "registration_full")
    after = {r["data"]["sm_email"]: r["data"]["sm_status"] for r in await regs(reg_site)}
    assert after == {"a@example.org": "registered", "b@example.org": "pending"}
    assert await seat_counts(reg_site) == (1, 1)


async def test_a_declined_single_opt_in_submit_leaves_nothing_behind(reg_site, monkeypatch):
    """V3, submit path (single opt-in): the admit declines after describe said open."""
    from sm_records.public_submissions.registration import register as module

    await single_opt_in(reg_site)
    event = await seed_event(reg_site.db_state, uid="s@x", registration_capacity=1)
    tokens = [await token(reg_site, event) for _ in range(2)]
    assert (
        await register(reg_site, "a@example.org", event=event, token=tokens[0], consent=True)
    ).status_code == 202
    monkeypatch.setattr(module, "_availability_refusal", lambda state: None)  # the stale read
    got = await register(reg_site, "b@example.org", event=event, token=tokens[1], consent=True)
    assert got.status_code == 202
    assert [r["data"]["sm_email"] for r in await regs(reg_site)] == ["a@example.org"]
    assert await seat_counts(reg_site) == (1, 1)


async def test_pending_records_have_no_seat_to_release(reg_site):
    from tests.support.app_harness import ADMIN, roles
    from tests.support.registration_http import record_url

    await register(reg_site, "a@example.org")
    (record,) = await regs(reg_site)
    assert (
        await reg_site.post(record_url(record["uuid"], "/submission/cancel"), headers=roles(ADMIN))
    ).status_code == 200
    assert await seat_counts(reg_site) == (0, 0)
    await register(reg_site, "b@example.org")
    (pending,) = [r for r in await regs(reg_site) if r["data"]["sm_status"] == "pending"]
    assert (
        await reg_site.delete(record_url(pending["uuid"]), headers=roles(ADMIN))
    ).status_code == 204
    assert (
        await reg_site.post(record_url(pending["uuid"], "/restore"), headers=roles(ADMIN))
    ).status_code == 200
    assert await seat_counts(reg_site) == (0, 0)  # a pending record restores without taking a seat


def test_one_pending_ttl_for_every_reader():
    from datetime import timedelta

    from sm_records.contracts.public_submissions import DEFAULT_PENDING_HOLD_HOURS
    from sm_records.public_submissions.retention_rules import window_for

    assert window_for({"kind": "registration", "retention_days": 0}) == timedelta(
        hours=DEFAULT_PENDING_HOLD_HOURS
    )
    assert window_for(
        {"kind": "registration", "retention_days": 0, "pending_hold_hours": 5}
    ) == timedelta(hours=5)
