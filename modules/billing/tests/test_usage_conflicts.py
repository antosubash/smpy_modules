"""A key answers only for the call it was first used with.

Reusing a key with another quantity, kind or source must never replay an
admission it did not pay for, and a refunded key must not replay as admitted.
"""

from __future__ import annotations

import json

import pytest
from sm_billing.contracts.metering import Allowed, IdempotencyConflict, Refunded
from sm_billing.errors import _idempotency_conflict
from usage_helpers import METER, OCT, Clock, events, seed_limits, service, used


@pytest.fixture
def factory(app):
    return app.state.sm.db.session_factory


@pytest.fixture
def usage(app):
    return service(app, Clock())


async def test_a_bigger_quantity_on_a_used_key_conflicts(factory, usage):
    tenant = await seed_limits(factory, {METER: 5})
    await usage.consume(tenant, METER, 1, "req-1", source="test")
    with pytest.raises(IdempotencyConflict):
        await usage.consume(tenant, METER, 4, "req-1", source="test")
    assert await used(factory, tenant, OCT[0]) == 1


async def test_a_quantity_over_the_limit_on_a_used_key_conflicts(factory, usage):
    # The qty > limit path replays before refusing; it must check the call too.
    tenant = await seed_limits(factory, {METER: 3})
    await usage.consume(tenant, METER, 1, "req-1", source="test")
    with pytest.raises(IdempotencyConflict):
        await usage.consume(tenant, METER, 50, "req-1", source="test")


async def test_another_source_on_a_used_key_conflicts(factory, usage):
    tenant = await seed_limits(factory, {METER: 5})
    await usage.consume(tenant, METER, 1, "req-1", source="ai")
    with pytest.raises(IdempotencyConflict):
        await usage.consume(tenant, METER, 1, "req-1", source="exports")


async def test_record_on_a_consume_key_conflicts(factory, usage):
    tenant = await seed_limits(factory, {METER: 5})
    await usage.consume(tenant, METER, 2, "req-1", source="test")
    with pytest.raises(IdempotencyConflict):
        await usage.record(tenant, METER, 2, "req-1", source="test")
    assert await events(factory, tenant) == 1


async def test_the_same_call_still_replays(factory, usage):
    tenant = await seed_limits(factory, {METER: 5})
    await usage.consume(tenant, METER, 2, "req-1", source="test")
    again = await usage.consume(tenant, METER, 2, "req-1", source="test")
    assert again == Allowed(2, 5, OCT[1], replayed=True)


async def test_a_refunded_key_replays_as_refunded_not_admitted(factory, usage):
    tenant = await seed_limits(factory, {METER: 5})
    await usage.consume(tenant, METER, 2, "req-1", source="test")
    assert await usage.refund(tenant, METER, "req-1")
    again = await usage.consume(tenant, METER, 2, "req-1", source="test")
    assert again == Refunded(0, 5, OCT[1])
    assert not again.ok
    assert await used(factory, tenant, OCT[0]) == 0
    # A retry that should count again uses a new key.
    assert (await usage.consume(tenant, METER, 2, "req-2", source="test")).ok


async def test_a_refunded_record_replays_as_refunded(factory, usage):
    tenant = await seed_limits(factory, {METER: 5})
    await usage.record(tenant, METER, 3, "job-1", source="worker")
    await usage.refund(tenant, METER, "job-1")
    again = await usage.record(tenant, METER, 3, "job-1", source="worker")
    assert isinstance(again, Refunded)
    assert await used(factory, tenant, OCT[0]) == 0


async def test_conflict_maps_to_409():
    conflict = IdempotencyConflict("k")
    response = await _idempotency_conflict(None, conflict)  # ty: ignore[invalid-argument-type]
    assert response.status_code == 409
    assert json.loads(response.body) == {"detail": "idempotency_conflict"}
