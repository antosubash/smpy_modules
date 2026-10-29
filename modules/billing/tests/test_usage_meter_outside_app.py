"""``usage_meter(session_factory)``: billing's meter for code with no app.

A Celery worker never builds the app, so ``app.state.billing_usage`` does not
exist there. The contract builds the same ``UsageService`` over a session
factory the caller owns; each write is still its own short transaction
finished with ``finalize_session``.
"""

from __future__ import annotations

import pytest
from simple_module_db import init_db
from sm_billing.contracts.metering import Allowed, Exceeded, UsageMeter, usage_meter
from sm_billing.models import Base
from usage_helpers import METER, events, seed_limits


@pytest.fixture
async def factory(tmp_path):
    """A file database with only billing's tables: no app, no lifespan."""
    state = init_db(f"sqlite+aiosqlite:///{tmp_path / 'worker.db'}")
    async with state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield state.session_factory
    await state.engine.dispose()


async def test_counts_and_refuses_without_an_app(factory):
    meter = usage_meter(factory)
    assert isinstance(meter, UsageMeter)
    tenant = await seed_limits(factory, {METER: 1})
    first = await meter.consume(tenant, METER, 1, "worker-1", source="images:classify")
    assert isinstance(first, Allowed) and first.used == 1
    refused = await meter.consume(tenant, METER, 1, "worker-2", source="images:classify")
    assert isinstance(refused, Exceeded)
    # Committed (finalize_session), not left in an open transaction.
    assert await events(factory, tenant) == 1


async def test_a_replayed_key_counts_once(factory):
    meter = usage_meter(factory)
    tenant = await seed_limits(factory, {METER: 5})
    a = await meter.consume(tenant, METER, 1, "same", source="images:classify")
    b = await usage_meter(factory).consume(tenant, METER, 1, "same", source="images:classify")
    assert (a.used, b.used, b.replayed) == (1, 1, True)
