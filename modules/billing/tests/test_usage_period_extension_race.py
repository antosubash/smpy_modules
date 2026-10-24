"""A sync that extends a period while a consume is between resolving the
period and inserting its first rollup row: the row still gets the extended
end (``metering.sql._stored_end``)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from simple_module_test.database import database_is_postgres
from sm_billing.metering.sql import extend_rollups
from sm_billing.models import Subscription
from sqlalchemy import update
from test_usage_period_extension import (
    EXTENDED,
    FIRST_END,
    START,
    _ends,
    _sync,
    _tenant,
)
from usage_helpers import METER, Clock, service

postgres_only = pytest.mark.skipif(not database_is_postgres(), reason="SM_TEST_DATABASE_URL")
CLOCK = START + timedelta(days=1)  # inside the period, before and after the extension


async def test_first_row_after_a_committed_extension_takes_the_new_end(app):
    """The consume resolved the period (stale end), then the sync committed
    the extension, finding no row to extend; then the consume inserts."""
    tenant = await _tenant(app)
    await _sync(app, tenant, (START, FIRST_END))
    usage = service(app, Clock(CLOCK))
    resolve = usage._resolve

    async def resolve_then_extend(*args, **kwargs):
        resolved = await resolve(*args, **kwargs)
        assert resolved.period == (START, FIRST_END)
        await _sync(app, tenant, (START, EXTENDED))
        return resolved

    usage._resolve = resolve_then_extend
    assert (await usage.consume(tenant, METER, 2, "k1", source="t")).ok
    assert await _ends(app, tenant) == [(EXTENDED, 2)]


@postgres_only
async def test_insert_waits_for_an_extension_in_flight(app):
    """The sync has updated the subscription but not committed when the
    consume inserts: the insert's read waits on the subscription row and then
    stores the committed, extended end."""
    tenant = await _tenant(app)
    await _sync(app, tenant, (START, FIRST_END))
    factory = app.state.sm.db.session_factory
    async with factory() as held:
        await held.execute(
            update(Subscription)
            .where(Subscription.tenant_id == tenant)
            .values(current_period_end=EXTENDED)
        )
        await held.execute(extend_rollups(tenant_id=tenant, start=START, end=EXTENDED))
        consume = asyncio.create_task(
            service(app, Clock(CLOCK)).consume(tenant, METER, 3, "k1", source="t")
        )
        await asyncio.sleep(0.5)
        assert not consume.done()  # blocked on the subscription row
        await held.commit()
    assert (await asyncio.wait_for(consume, 10)).ok
    assert await _ends(app, tenant) == [(EXTENDED, 3)]
