"""A key's terminal outcome: ``close_key``, admission by the database's clock,
and retention that never purges an outcome before its deadline.

* ``close_key`` returns the outcome a key has (a hold, a refusal, an expired
  call) or commits ``Closed``; a ``swap`` under a closed key answers
  ``Closed`` and writes nothing.
* Codex's P1-1 trace: a swap pauses after the admission check; a takeover's
  swap under its key is refused; retention purges the refusal; the paused
  call resumes. It must not create a hold: admission is decided after the
  key is claimed, by the database's clock, which is past its deadline.
* Retention keeps a settled outcome until a day past its ``not_after``.

The concurrent ``close_key`` against an in-flight swap is in
``test_usage_hold_races``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sm_billing.contracts.metering import Closed, Exceeded, Expired, Hold, Refused
from sm_billing.metering import dbtime
from sm_billing.metering import swap as swap_module
from sm_billing.metering.retention import purge
from sm_billing.models import UsageHold
from sqlalchemy import select, update
from usage_helpers import FAR, GAUGE, Clock, gauge_service, hold_statuses, in_use, seed_limits


@pytest.fixture
def factory(app):
    return app.state.sm.db.session_factory


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def usage(factory, clock):
    return gauge_service(factory, clock)


@pytest.fixture
def db_clock(monkeypatch) -> dict:
    """Move the database's clock (``dbtime.now``) by ``["by"]``."""
    real, shift = dbtime.now, {"by": timedelta(0)}

    async def shifted(session):
        return await real(session) + shift["by"]

    monkeypatch.setattr(dbtime, "now", shifted)
    return shift


async def test_close_key_returns_the_keys_outcome(factory, usage, clock):
    tenant = await seed_limits(factory, {GAUGE: 5})
    held = await usage.swap(tenant, GAUGE, None, 4, "a", source="t", not_after=FAR)
    await usage.swap(tenant, GAUGE, held.id, 9, "b", source="t", not_after=FAR)  # refused
    past = clock.now - timedelta(seconds=1)
    await usage.swap(tenant, GAUGE, held.id, 5, "c", source="t", not_after=past)
    found = await usage.close_key(tenant, GAUGE, "a")
    assert isinstance(found, Hold) and (found.id, found.status) == (held.id, "committed")
    assert await usage.close_key(tenant, GAUGE, "b") == Refused("b")
    assert await usage.close_key(tenant, GAUGE, "c") == Expired("c", past)
    assert await usage.close_key(tenant, GAUGE, "nope") == Closed("nope")
    assert await usage.close_key(tenant, GAUGE, "nope") == Closed("nope")  # idempotent
    other = await seed_limits(factory, {GAUGE: 5})
    assert await usage.close_key(other, GAUGE, "a") == Closed("a")  # tenant-scoped
    assert await in_use(factory, tenant) == 4 and await in_use(factory, other) is None
    assert await hold_statuses(factory, tenant) == [
        "closed",
        "committed",
        "expired_call",
        "refused",
    ]


async def test_a_swap_on_a_closed_key_answers_closed_and_writes_nothing(factory, usage):
    """Closed is key-wide: any call under the key, whatever its quantity,
    source, old hold or deadline, answers ``Closed``."""
    tenant = await seed_limits(factory, {GAUGE: 50})
    old = await usage.swap(tenant, GAUGE, None, 4, "seed", source="t", not_after=FAR)
    assert await usage.close_key(tenant, GAUGE, "k") == Closed("k")
    for qty, source, old_id in ((9, "t", old.id), (1, "u", None)):
        late = await usage.swap(tenant, GAUGE, old_id, qty, "k", source=source, not_after=FAR)
        assert late == Closed("k") and not late.ok
    assert await in_use(factory, tenant) == 4
    assert await hold_statuses(factory, tenant) == ["closed", "committed"]
    assert await usage.close_key(tenant, GAUGE, "k") == Closed("k")


async def test_codex_p1_1_a_paused_swap_creates_no_hold(
    factory, usage, clock, db_clock, monkeypatch
):
    tenant = await seed_limits(factory, {GAUGE: 10})
    old = await usage.swap(tenant, GAUGE, None, 4, "seed", source="t", not_after=FAR)
    filler = await usage.reserve(tenant, GAUGE, 6, "filler", source="t")  # full
    deadline = datetime.now(UTC) + timedelta(days=7)
    real, reached, go = swap_module.run_write, asyncio.Event(), asyncio.Event()

    async def paused(*args, **kwargs):
        if not reached.is_set():  # the executor's call, past its admission check
            reached.set()
            await go.wait()
        return await real(*args, **kwargs)

    monkeypatch.setattr(swap_module, "run_write", paused)
    call = {"source": "t", "not_after": deadline}
    executor = asyncio.create_task(usage.swap(tenant, GAUGE, old.id, 6, "k", **call))
    await asyncio.wait_for(reached.wait(), 10)
    assert isinstance(await usage.swap(tenant, GAUGE, old.id, 6, "k", **call), Exceeded)
    await usage.release(filler.id)  # room again
    clock.now += timedelta(days=31)  # retention purges the refusal
    db_clock["by"] = timedelta(days=31)
    assert (await purge(usage, retention_days=0)).holds >= 1
    assert "refused" not in await hold_statuses(factory, tenant)
    go.set()
    late = await executor
    assert late == Expired("k", deadline)  # the database's clock is past its deadline
    assert await in_use(factory, tenant) == 4
    assert [s for s in await hold_statuses(factory, tenant) if s == "committed"] == ["committed"]


async def _backdate(factory, key: str, days: int) -> None:
    async with factory() as s:
        settled = datetime.now(UTC) - timedelta(days=days)
        await s.execute(
            update(UsageHold).where(UsageHold.idempotency_key == key).values(settled_at=settled)
        )
        await s.commit()


async def test_retention_never_purges_an_outcome_before_its_deadline(factory, usage, clock):
    tenant = await seed_limits(factory, {GAUGE: 1})
    now = datetime.now(UTC)
    for key, not_after in (("soon", now + timedelta(days=10)), ("past", now - timedelta(days=2))):
        refused = await usage.swap(tenant, GAUGE, None, 5, key, source="t", not_after=not_after)
        assert isinstance(refused, Exceeded if key == "soon" else Expired)
        await _backdate(factory, key, 31)
    await usage.close_key(tenant, GAUGE, "closed-old")
    await _backdate(factory, "closed-old", 31)
    await usage.close_key(tenant, GAUGE, "closed-young")
    await _backdate(factory, "closed-young", 29)
    assert (await purge(usage, retention_days=0)).holds == 2
    async with factory() as s:
        kept = set((await s.scalars(select(UsageHold.idempotency_key))).all())
    assert kept == {"soon", "closed-young"}  # "soon": settled 31 days ago, deadline ahead
