"""Seats under real concurrency: separate sessions racing on Postgres (PR 9).

SQLite cannot reproduce these races: it has one writer at a time, which the caller's records type
lock already guarantees there, so the sequential tests in ``test_seats.py`` cover its behaviour.
Every test here recomputes the counters from the seat rows at the end.

The lock order, in every path that writes seats: the event row (``FOR SHARE``, admit only), then
the occurrence's counter row (``FOR UPDATE``, in ascending id when there are several), then the
seat rows. Two paths therefore never wait on each other in a cycle.
"""

from __future__ import annotations

import asyncio
from collections import Counter

import pytest
from sm_events.content.workflow import transition
from sm_events.core.tenancy import tenant_scope
from sm_events.models import RegistrationSeat
from sm_events.registration.seats import admit, release, release_target
from sqlalchemy import select

from tests.pg_support import USING_POSTGRES
from tests.registration.support import NOW, SECOND_KEY, consistent, one_off, public_calendar, series
from tests.support.providers import KNOWN_TARGET, PROVIDER_ID
from tests.support.writes import OWNER_P

pytestmark = pytest.mark.skipif(not USING_POSTGRES, reason="needs real concurrent transactions")

RACERS = 20
TIMEOUT = 60


async def seeded(state, *, capacity, series_event=False, **fields):
    with tenant_scope("default"):
        async with state.session_factory() as db:
            cal = await public_calendar(db)
            make = series if series_event else one_off
            event = await make(db, cal, registration_capacity=capacity, **fields)
            event_id, key = (
                event.id,
                (SECOND_KEY.format(id=event.id) if series_event else str(event.id)),
            )
            await db.commit()
    return event_id, key


async def try_admit(state, event_id, key, holder, *, hold=None, **kw):
    """Admit in a transaction of its own, then commit (or wait for ``hold`` first)."""
    with tenant_scope("default"):
        async with state.session_factory() as db:
            got = await admit(
                db,
                tenant_id="default",
                event_id=event_id,
                occurrence_key=key,
                provider=PROVIDER_ID,
                target=KNOWN_TARGET,
                holder=holder,
                now=NOW,
                **kw,
            )
            if hold is not None:
                await hold.wait()
            await db.commit()
            return got


async def try_release(state, *holders):
    with tenant_scope("default"):
        async with state.session_factory() as db:
            got = await release(
                db, tenant_id="default", provider=PROVIDER_ID, holders=list(holders)
            )
            await db.commit()
            return got


async def final(state):
    with tenant_scope("default"):
        async with state.session_factory() as db:
            counters = await consistent(db)
            holders = [r.holder for r in (await db.execute(select(RegistrationSeat))).scalars()]
    return counters, sorted(holders)


async def test_admit_last_seat_parallel_pg(db_state):
    event_id, key = await seeded(db_state, capacity=1)
    got = await asyncio.wait_for(
        asyncio.gather(*(try_admit(db_state, event_id, key, f"h{n}") for n in range(RACERS))),
        TIMEOUT,
    )
    assert Counter(g.code for g in got) == {None: 1, "registration_full": RACERS - 1}
    assert sum(g.admitted for g in got) == 1
    counters, holders = await final(db_state)
    assert counters == {(event_id, key): 1} and len(holders) == 1


async def test_admit_for_the_last_k_seats_parallel_pg(db_state):
    event_id, key = await seeded(db_state, capacity=5)
    got = await asyncio.wait_for(
        asyncio.gather(*(try_admit(db_state, event_id, key, f"h{n}") for n in range(30))), TIMEOUT
    )
    assert sum(g.admitted for g in got) == 5
    counters, holders = await final(db_state)
    assert counters == {(event_id, key): 5} and len(holders) == 5


async def test_admit_on_a_series_occurrence_parallel_pg(db_state):
    event_id, key = await seeded(db_state, capacity=2, series_event=True)
    other = f"{event_id}:20260715T080000Z"
    jobs = [try_admit(db_state, event_id, key, f"a{n}") for n in range(8)]
    jobs += [try_admit(db_state, event_id, other, f"b{n}") for n in range(8)]
    got = await asyncio.wait_for(asyncio.gather(*jobs), TIMEOUT)
    assert sum(g.admitted for g in got[:8]) == 2 and sum(g.admitted for g in got[8:]) == 2
    counters, _ = await final(db_state)
    assert counters == {(event_id, key): 2, (event_id, other): 2}


async def test_the_same_holder_many_times_is_one_seat_pg(db_state):
    event_id, key = await seeded(db_state, capacity=3)
    got = await asyncio.wait_for(
        asyncio.gather(*(try_admit(db_state, event_id, key, "same") for _ in range(10))), TIMEOUT
    )
    assert all(g.admitted for g in got)
    counters, holders = await final(db_state)
    assert counters == {(event_id, key): 1} and holders == ["same"]


async def test_a_release_racing_an_admit_pg(db_state):
    event_id, key = await seeded(db_state, capacity=1)
    assert (await try_admit(db_state, event_id, key, "h1")).admitted
    admitted, freed = await asyncio.wait_for(
        asyncio.gather(try_admit(db_state, event_id, key, "h2"), try_release(db_state, "h1")),
        TIMEOUT,
    )
    assert freed == 1
    counters, holders = await final(db_state)
    # Either the admit saw the seat freed (h2 sits), or it ran first and was refused (nobody does):
    # never both seated, never a counter that disagrees with the rows.
    assert (admitted.admitted, holders) in [(True, ["h2"]), (False, [])]
    assert counters == {(event_id, key): len(holders)}


async def test_many_releases_and_admits_end_consistent_pg(db_state):
    event_id, key = await seeded(db_state, capacity=10)
    await asyncio.gather(*(try_admit(db_state, event_id, key, f"old{n}") for n in range(10)))
    jobs = [try_release(db_state, f"old{n}") for n in range(10)]
    jobs += [try_admit(db_state, event_id, key, f"new{n}") for n in range(15)]
    await asyncio.wait_for(asyncio.gather(*jobs), TIMEOUT)
    counters, holders = await final(db_state)
    assert len(holders) <= 10 and counters == {(event_id, key): len(holders)}
    assert not [h for h in holders if h.startswith("old")]


async def test_a_release_waits_for_an_admit_in_flight_pg(db_state):
    """The case a plain ``UPDATE ... SET taken = count(*)`` gets wrong: the release's count must
    see the seat an admit committed while the release was waiting for the counter's lock."""
    event_id, key = await seeded(db_state, capacity=5)
    assert (await try_admit(db_state, event_id, key, "h1")).admitted
    gate = asyncio.Event()
    admitting = asyncio.create_task(try_admit(db_state, event_id, key, "h2", hold=gate))
    await asyncio.sleep(1)  # the admit has its seat and the counter lock, and has not committed
    releasing = asyncio.create_task(try_release(db_state, "h1"))
    await asyncio.sleep(1)
    assert not releasing.done()  # it is waiting for the counter row, not computing a stale count
    gate.set()
    assert (await asyncio.wait_for(admitting, TIMEOUT)).admitted
    assert await asyncio.wait_for(releasing, TIMEOUT) == 1
    counters, holders = await final(db_state)
    assert holders == ["h2"] and counters == {(event_id, key): 1}


async def test_admit_serialises_with_an_unpublish_pg(db_state):
    """``admit`` holds the event row ``FOR SHARE`` until its transaction ends, so a change that
    unpublishes the event (PR 2's compare-and-set takes the row exclusively) waits for it, and a
    seat can never be admitted into an event that is already gone."""
    event_id, key = await seeded(db_state, capacity=5)
    gate = asyncio.Event()
    admitting = asyncio.create_task(try_admit(db_state, event_id, key, "h1", hold=gate))
    await asyncio.sleep(1)

    async def unpublish():
        with tenant_scope("default"):
            async with db_state.session_factory() as db:
                await transition(db, OWNER_P, event_id, "unpublish", expected=1, now=NOW)
                await db.commit()

    unpublishing = asyncio.create_task(unpublish())
    await asyncio.sleep(1)
    assert not unpublishing.done()
    gate.set()
    assert (await asyncio.wait_for(admitting, TIMEOUT)).admitted
    await asyncio.wait_for(unpublishing, TIMEOUT)
    late = await try_admit(db_state, event_id, key, "h2")
    assert (late.admitted, late.code) == (False, "event_unavailable")
    counters, holders = await final(db_state)
    assert holders == ["h1"] and counters == {(event_id, key): 1}


async def test_no_deadlock_across_occurrences_and_target_release_pg(db_state):
    event_id, key = await seeded(db_state, capacity=50, series_event=True)
    keys = [key, f"{event_id}:20260715T080000Z", f"{event_id}:20260722T080000Z"]
    jobs = []
    for n in range(12):
        jobs.append(try_admit(db_state, event_id, keys[n % 3], f"h{n}"))
        jobs.append(try_release(db_state, f"h{(n + 6) % 12}"))

    async def release_all():
        with tenant_scope("default"):
            async with db_state.session_factory() as db:
                got = await release_target(
                    db, tenant_id="default", provider=PROVIDER_ID, target=KNOWN_TARGET
                )
                await db.commit()
                return got

    jobs += [release_all(), release_all()]
    await asyncio.wait_for(asyncio.gather(*jobs), TIMEOUT)
    counters, holders = await final(db_state)
    assert sum(counters.values()) == len(holders)
