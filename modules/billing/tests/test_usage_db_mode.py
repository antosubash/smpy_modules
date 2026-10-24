"""``consume(db=…)``: the usage commits or rolls back with the caller.

Also the fail-closed path: SQLite that cannot take the write lock is a 503
``usage_busy``, never an admission.
"""

from __future__ import annotations

import json

import pytest
from helpers import make_tenant
from simple_module_db import finalize_session, init_db
from sm_billing.contracts.metering import Allowed, Exceeded
from sm_billing.errors import _billing_error
from sm_billing.metering.errors import UsageBusyError
from sm_billing.metering.service import UsageService
from sm_billing.models import Base, Plan
from sqlalchemy import select, text
from tenants.models import Tenant
from usage_helpers import METER, OCT, Clock, events, seed_limits, service, used


@pytest.fixture
def factory(app):
    return app.state.sm.db.session_factory


@pytest.fixture
def usage(app):
    return service(app, Clock())


async def test_usage_rolls_back_with_the_caller(factory, usage):
    tenant = await seed_limits(factory, {METER: 3})
    async with factory() as caller:
        outcome = await usage.consume(tenant, METER, 1, "k", source="t", db=caller)
        assert outcome == Allowed(1, 3, OCT[1])
        await caller.rollback()
    assert await used(factory, tenant, OCT[0]) is None
    assert await events(factory, tenant) == 0


async def test_usage_commits_with_the_caller(factory, usage):
    tenant = await seed_limits(factory, {METER: 3})
    async with factory() as caller:
        await usage.consume(tenant, METER, 2, "k", source="t", db=caller)
        await usage.record(tenant, METER, 1, "late", source="t", db=caller)
        await finalize_session(caller)
    assert await used(factory, tenant, OCT[0]) == 3


async def test_a_refusal_rolls_back_only_the_metering(factory, usage):
    tenant = await seed_limits(factory, {METER: 1})
    await usage.consume(tenant, METER, 1, "k1", source="t")
    async with factory() as caller:
        org = await make_tenant(caller, "kept")
        refused = await usage.consume(tenant, METER, 1, "k2", source="t", db=caller)
        replay = await usage.consume(tenant, METER, 1, "k1", source="t", db=caller)
        assert isinstance(refused, Exceeded) and replay.replayed
        await finalize_session(caller)
    async with factory() as session:
        assert await session.get(Tenant, org.id) is not None
    assert await used(factory, tenant, OCT[0]) == 1
    assert await events(factory, tenant) == 1


async def test_sqlite_lock_timeout_fails_closed(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'busy.db'}"
    holder_state, meter_state = init_db(url), init_db(url, sqlite_busy_timeout_ms=50)
    try:
        async with holder_state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        tenant = await seed_limits(holder_state.session_factory, {METER: 3})
        meter = UsageService(meter_state.session_factory, clock=Clock())
        async with holder_state.session_factory() as holder:
            # Another writer holds the write lock past the meter's busy_timeout.
            await holder.execute(text("UPDATE billing_plan SET sort_order = sort_order + 1"))
            with pytest.raises(UsageBusyError):
                await meter.consume(tenant, METER, 1, "k", source="t")
            await holder.rollback()
        assert await used(holder_state.session_factory, tenant, OCT[0]) is None
        async with holder_state.session_factory() as session:
            assert (await session.execute(select(Plan))).first() is not None
    finally:
        for state in (holder_state, meter_state):
            await state.engine.dispose()


async def test_usage_busy_maps_to_503_with_retry_after():
    response = await _billing_error(None, UsageBusyError())  # ty: ignore[invalid-argument-type]
    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert json.loads(response.body) == {"detail": "usage_busy"}
