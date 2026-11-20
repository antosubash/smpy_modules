"""Registering under real concurrency: N submits for the last K seats (Postgres)."""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter

import pytest
from sm_events.core.tenancy import tenant_scope
from sm_events.models import RegistrationCount, RegistrationSeat
from sm_records.public_submissions.registration import mail as reg_mail
from sqlalchemy import select

from tests.pg_support import USING_POSTGRES
from tests.support.registration_http import (
    load_registration,
    register,
    regs,
    seed_event,
    single_opt_in,
)

pytestmark = [
    pytest.mark.skipif(not USING_POSTGRES, reason="needs real concurrent transactions"),
    pytest.mark.usefixtures("reg_site"),
]


@pytest.fixture(autouse=True)
def _no_mail(monkeypatch):
    async def quiet(*_a, **_k):
        return None

    monkeypatch.setattr(reg_mail, "queue_registration_mail", quiet)


async def recomputed(site):
    """Every counter equals its seat rows, and every seat is a live registration record."""
    with tenant_scope("default"):
        async with site.db_state.session_factory() as db:
            seat_rows = list((await db.execute(select(RegistrationSeat))).scalars())
            counters = list((await db.execute(select(RegistrationCount))).scalars())
    per_key = Counter((s.event_id, s.occurrence_key) for s in seat_rows)
    assert {(c.event_id, c.occurrence_key): c.taken for c in counters} == dict(per_key)
    return [s.holder for s in seat_rows]


@pytest.mark.parametrize(("seats", "people"), [(1, 10), (3, 12)])
async def test_parallel_submits_for_the_last_seats_pg(reg_site, seats, people):
    """Confirmed-at-once registrations (so the cap on unconfirmed holds is not in play): every
    answer is the one 202, exactly ``seats`` records exist, and the losers were told by mail."""
    await single_opt_in(reg_site)
    event = await seed_event(reg_site.db_state, uid=f"p{seats}@x", registration_capacity=seats)
    tokens = [
        (await load_registration(reg_site, event)).json()["definition"]["token"]
        for _ in range(people)
    ]
    before = len(reg_site.outbox.sent)
    got = await asyncio.wait_for(
        asyncio.gather(
            *(
                register(reg_site, f"p{n}@example.org", event=event, token=tokens[n], consent=True)
                for n in range(people)
            )
        ),
        120,
    )
    assert {(r.status_code, r.text) for r in got} == {(202, '{"ok":true}')}
    holders = await recomputed(reg_site)
    items = await regs(reg_site)
    assert sorted(uuid.UUID(h).hex for h in holders) == sorted(r["uuid"] for r in items)
    assert len(items) == seats
    from sm_records.public_submissions import mail_runner

    await mail_runner.drain()
    sent = reg_site.outbox.sent[before:]
    notices = [m for m in sent if "Nothing was saved" in m.text]
    assert len(notices) == people - seats  # each loser was told by mail, not by the form


async def test_the_same_person_many_times_is_one_seat_pg(reg_site):
    event = await seed_event(reg_site.db_state, uid="same@x", registration_capacity=5)
    tokens = [
        (await load_registration(reg_site, event)).json()["definition"]["token"] for _ in range(8)
    ]
    got = await asyncio.wait_for(
        asyncio.gather(
            *(register(reg_site, "same@example.org", event=event, token=t) for t in tokens)
        ),
        120,
    )
    assert {r.status_code for r in got} == {202}
    assert len(await recomputed(reg_site)) == 0 and len(await regs(reg_site)) == 1  # pending
