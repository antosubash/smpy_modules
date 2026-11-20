"""Confirming racing for seats, cancels and purges (Postgres): exactly the free seats are taken."""

from __future__ import annotations

import asyncio
from collections import Counter

import pytest
from sm_records.public_submissions.registration import mail as reg_mail

from tests.pg_support import USING_POSTGRES
from tests.support.app_harness import ADMIN, roles
from tests.support.registration_http import (
    confirm_record,
    load_registration,
    record_url,
    register,
    regs,
    seat_counts,
    seed_event,
)

pytestmark = [
    pytest.mark.skipif(not USING_POSTGRES, reason="needs real concurrent transactions"),
    pytest.mark.usefixtures("reg_site"),
]
A = {"headers": roles(ADMIN)}


@pytest.fixture(autouse=True)
def _quiet_mail(monkeypatch):
    async def quiet(*_a, **_k):
        return None

    monkeypatch.setattr(reg_mail, "queue_registration_mail", quiet)


async def pending(site, event, n):
    tokens = [
        (await load_registration(site, event)).json()["definition"]["token"] for _ in range(n)
    ]
    for i in range(n):
        await register(site, f"p{i}@example.org", event=event, token=tokens[i])
    return await regs(site)


@pytest.mark.parametrize(("seats", "people"), [(1, 8), (3, 12)])
async def test_n_confirms_racing_for_k_seats_pg(reg_site, seats, people):
    event = await seed_event(reg_site.db_state, uid=f"k{seats}@x", registration_capacity=seats)
    records = await pending(reg_site, event, people)
    got = await asyncio.wait_for(
        asyncio.gather(*(confirm_record(reg_site, r) for r in records)), 120
    )
    codes = Counter(g.status_code if g.status_code == 200 else g.json()["code"] for g in got)
    assert codes == {200: seats, "registration_full": people - seats}
    statuses = Counter(r["data"]["sm_status"] for r in await regs(reg_site))
    assert statuses == {"registered": seats, "pending": people - seats}
    assert (await seat_counts(reg_site))[0] == seats


async def test_confirm_racing_a_cancel_pg(reg_site):
    for n in range(8):
        event = await seed_event(reg_site.db_state, uid=f"c{n}@x", registration_capacity=1)
        (record,) = [r for r in await pending(reg_site, event, 1)
                     if r["data"]["sm_event_id"] == event["event_id"]]  # fmt: skip
        confirm, cancel = await asyncio.wait_for(
            asyncio.gather(
                confirm_record(reg_site, record),
                reg_site.post(record_url(record["uuid"], "/submission/cancel"), **A),
            ),
            90,
        )
        assert cancel.status_code == 200 and confirm.status_code in (200, 410)
        fresh = next(r for r in await regs(reg_site) if r["uuid"] == record["uuid"])
        held = (await seat_counts(reg_site))[0]
        assert held == (1 if fresh["data"]["sm_status"] == "registered" else 0)
        await reg_site.delete(record_url(record["uuid"]), **A)  # tidy: the next round counts alone
        await reg_site.delete(record_url(record["uuid"], "/purge"), **A)
        assert (await seat_counts(reg_site))[0] == 0


async def test_confirm_racing_a_trash_pg(reg_site):
    event = await seed_event(reg_site.db_state, uid="t@x", registration_capacity=5)
    records = await pending(reg_site, event, 6)
    jobs = [confirm_record(reg_site, r) for r in records]
    jobs += [reg_site.delete(record_url(r["uuid"]), **A) for r in records[:3]]
    await asyncio.wait_for(asyncio.gather(*jobs, return_exceptions=True), 120)
    live = [r for r in await regs(reg_site) if r["data"]["sm_status"] == "registered"]
    assert (await seat_counts(reg_site))[0] == len(live)
