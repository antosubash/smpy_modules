"""The ledger retention purge: paired refunds, settled holds, bounded batches."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sm_billing.constants import USAGE_STATE_ATTR
from sm_billing.contracts.metering import Allowed
from sm_billing.metering.retention import purge
from sm_billing.metering.sweeper import UsageSweeper
from usage_helpers import GAUGE, METER, OCT, Clock, events, gauge_service, hold_statuses, used
from usage_helpers import seed_limits as seed


@pytest.fixture
def factory(app):
    return app.state.sm.db.session_factory


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def usage(factory, clock):
    return gauge_service(factory, clock)


async def test_old_ledger_rows_and_settled_holds_go(factory, usage, clock):
    tenant = await seed(factory, {})
    await usage.consume(tenant, METER, 1, "old", source="t")
    old = await usage.reserve(tenant, GAUGE, 1, "old", source="t")
    await usage.release(old.id)
    await usage.reserve(tenant, GAUGE, 1, "live", source="t")
    clock.now += timedelta(days=31)
    await usage.consume(tenant, METER, 1, "new", source="t")
    first = await purge(usage, retention_days=400)
    assert (first.events, first.holds, first.done) == (0, 1, True)
    assert await hold_statuses(factory, tenant) == ["held"]  # live holds stay
    clock.now += timedelta(days=380)
    assert (await purge(usage, retention_days=0)).events == 0  # 0 keeps the ledger
    assert (await purge(usage, retention_days=400)).events == 1
    assert await events(factory, tenant) == 1


async def test_a_charge_and_its_refund_are_purged_together(factory, usage, clock):
    """1-day retention: the charge is past it, its refund (20 hours later) not yet."""
    tenant = await seed(factory, {})
    await usage.consume(tenant, METER, 1, "job", source="t")
    clock.now += timedelta(hours=20)
    assert await usage.refund(tenant, METER, "job") is True
    clock.now += timedelta(hours=5)  # charge 25 h old, refund 5 h old
    purged = await purge(usage, retention_days=1)
    assert purged.events == 2  # the refund went with its charge, though younger
    assert await events(factory, tenant) == 0
    # The key is forgotten whole: reusing it is a fresh call, not a Refunded replay.
    again = await usage.consume(tenant, METER, 1, "job", source="t")
    assert isinstance(again, Allowed) and not again.replayed
    assert await usage.refund(tenant, METER, "job") is True


async def test_a_young_charge_keeps_its_refund(factory, usage, clock):
    tenant = await seed(factory, {})
    await usage.consume(tenant, METER, 1, "keep", source="t")
    await usage.refund(tenant, METER, "keep")
    clock.now += timedelta(hours=12)
    assert (await purge(usage, retention_days=1)).events == 0
    assert await events(factory, tenant) == 2


async def test_a_backlog_is_purged_in_batches_across_ticks(app, factory, usage, clock, monkeypatch):
    from sm_billing.metering import retention

    tenant = await seed(factory, {})
    for i in range(7):
        await usage.consume(tenant, METER, 1, f"k{i}", source="t")
    await usage.refund(tenant, METER, "k0")
    clock.now += timedelta(days=401)
    capped = await purge(usage, 400, batch=2, max_batches=2)
    assert (capped.events, capped.done) == (5, False)  # 4 charges and k0's refund
    assert await events(factory, tenant) == 3

    # The sweeper carries on next tick until the backlog is gone.
    monkeypatch.setattr(app.state, USAGE_STATE_ATTR, usage)
    monkeypatch.setattr(retention, "PURGE_BATCH", 2)
    monkeypatch.setattr(retention, "MAX_BATCHES", 1)
    sweep = UsageSweeper()
    ticks = [await sweep.tick(app) for _ in range(3)]
    assert [t.events_purged for t in ticks] == [2, 1, 0]
    assert await events(factory, tenant) == 0
    assert sweep._purged_at == clock.now  # done: the next purge waits a day


async def test_a_stale_batch_never_takes_a_newer_calls_refund(factory, usage, clock):
    """B selects an old charge; A purges it; the key is reused, charged and
    refunded; B's delete then runs with its stale selection."""
    from sm_billing.metering.retention import delete_charges, select_charges

    tenant = await seed(factory, {})
    await usage.consume(tenant, METER, 1, "job", source="t")
    await usage.refund(tenant, METER, "job")
    clock.now += timedelta(days=2)
    cutoff = clock.now - timedelta(days=1)
    stale = await select_charges(factory, cutoff, 10)  # instance B
    assert len(stale) == 1
    assert (await purge(usage, retention_days=1)).events == 2  # instance A
    again = await usage.consume(tenant, METER, 1, "job", source="t")
    assert isinstance(again, Allowed) and not again.replayed
    assert await usage.refund(tenant, METER, "job") is True
    assert await delete_charges(factory, stale, cutoff) == 0  # B's stale batch: nothing
    assert await events(factory, tenant) == 2  # the new charge and its refund stay
    assert await usage.refund(tenant, METER, "job") is False  # no double refund
    assert await used(factory, tenant, OCT[0]) == 0
