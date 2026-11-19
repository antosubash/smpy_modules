"""Records and events locks, raced for real: restore, submit, cancel and type delete (Postgres).

The one global order (records type lock -> row -> events event row -> counter -> seats) means none
of these can deadlock and none can leave a counter that disagrees with the seat rows; each test
ends by recomputing the counters from the rows and checking every seat has a live record.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter

import pytest
from sm_records.public_submissions.registration import mail as reg_mail

from tests.pg_support import USING_POSTGRES
from tests.support.app_harness import ADMIN, roles
from tests.support.registration_http import (
    TYPE,
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
ROUNDS = 12


@pytest.fixture(autouse=True)
def _quiet_mail(monkeypatch):
    async def quiet(*_a, **_k):
        return None

    monkeypatch.setattr(reg_mail, "queue_registration_mail", quiet)


async def token(site, event) -> str:
    return (await load_registration(site, event)).json()["definition"]["token"]


async def live_seats_match_records(site) -> int:
    """Every seat belongs to a live (untrashed, pending or registered) record, and conversely."""
    from sm_events.core.tenancy import tenant_scope
    from sm_events.models import RegistrationSeat
    from sqlalchemy import select

    with tenant_scope("default"):
        async with site.db_state.session_factory() as db:
            held = sorted(
                uuid.UUID(s.holder).hex
                for s in (await db.execute(select(RegistrationSeat))).scalars()
            )
    live = sorted(
        r["uuid"] for r in await regs(site) if r["data"]["sm_status"] in ("pending", "registered")
    )
    assert held == live
    assert (await seat_counts(site))[0] == len(held)
    return len(held)


async def test_restore_racing_a_submit_for_the_last_seat_pg(reg_site):
    for n in range(ROUNDS):
        event = await seed_event(reg_site.db_state, uid=f"r{n}@x", registration_capacity=1)
        tokens = [await token(reg_site, event) for _ in range(2)]
        await register(reg_site, f"a{n}@example.org", event=event, token=tokens[0])
        first = next(
            r for r in await regs(reg_site) if r["data"]["sm_email"] == f"a{n}@example.org"
        )
        assert (await reg_site.delete(record_url(first["uuid"]), **A)).status_code == 204
        restore, submit = await asyncio.wait_for(
            asyncio.gather(
                reg_site.post(record_url(first["uuid"], "/restore"), **A),
                register(reg_site, f"b{n}@example.org", event=event, token=tokens[1]),
            ),
            90,
        )
        won = (restore.status_code == 200) + (submit.status_code == 202)
        assert won == 1, (restore.status_code, submit.status_code)  # one seat, one winner
        if restore.status_code != 200:
            assert restore.json()["code"] == "registration_full"
        else:
            assert submit.json()["code"] == "registration_full"
        # clean the event's records so the next round's "live == held" check is about this one
        for r in await regs(reg_site):
            await reg_site.delete(record_url(r["uuid"]), **A)
        assert await live_seats_match_records(reg_site) == 0


async def test_submit_racing_a_cancel_pg(reg_site):
    for n in range(ROUNDS):
        event = await seed_event(reg_site.db_state, uid=f"c{n}@x", registration_capacity=1)
        tokens = [await token(reg_site, event) for _ in range(2)]
        await register(reg_site, f"a{n}@example.org", event=event, token=tokens[0])
        mine = next(r for r in await regs(reg_site) if r["data"]["sm_email"] == f"a{n}@example.org")
        cancel, submit = await asyncio.wait_for(
            asyncio.gather(
                reg_site.post(record_url(mine["uuid"], "/submission/cancel"), **A),
                register(reg_site, f"b{n}@example.org", event=event, token=tokens[1]),
            ),
            90,
        )
        assert cancel.status_code == 200 and submit.status_code in (202, 409)
        assert await live_seats_match_records(reg_site) == (1 if submit.status_code == 202 else 0)
        for r in await regs(reg_site):
            await reg_site.delete(record_url(r["uuid"]), **A)


async def test_two_cancels_free_one_seat_pg(reg_site):
    event = await seed_event(reg_site.db_state, uid="d@x", registration_capacity=5)
    tokens = [await token(reg_site, event) for _ in range(2)]
    await register(reg_site, "a@example.org", event=event, token=tokens[0])
    await register(reg_site, "b@example.org", event=event, token=tokens[1])
    mine = next(r for r in await regs(reg_site) if r["data"]["sm_email"] == "a@example.org")
    got = await asyncio.wait_for(
        asyncio.gather(
            *(reg_site.post(record_url(mine["uuid"], "/submission/cancel"), **A) for _ in range(6))
        ),
        90,
    )
    assert {r.status_code for r in got} == {200}
    assert await live_seats_match_records(reg_site) == 1


async def test_submits_racing_the_type_delete_pg(reg_site):
    event = await seed_event(reg_site.db_state, uid="t@x", registration_capacity=50)
    first = await token(reg_site, event)
    await register(reg_site, "seed@example.org", event=event, token=first)
    tokens = [await token(reg_site, event) for _ in range(5)]
    jobs = [
        reg_site.delete(f"/api/records/types/{TYPE}?confirm_record_count=1", **A),
        *(register(reg_site, f"p{n}@example.org", event=event, token=tokens[n]) for n in range(5)),
    ]
    got = await asyncio.wait_for(asyncio.gather(*jobs, return_exceptions=True), 90)
    deleted = got[0]
    assert not isinstance(deleted, Exception) and deleted.status_code in (204, 409)
    codes = Counter(r.status_code for r in got[1:] if not isinstance(r, Exception))
    assert set(codes) <= {202, 404, 409, 410, 400}
    if deleted.status_code == 204:  # the form is gone, so is every seat of it
        assert await seat_counts(reg_site) == (0, 0)
    else:
        await live_seats_match_records(reg_site)
