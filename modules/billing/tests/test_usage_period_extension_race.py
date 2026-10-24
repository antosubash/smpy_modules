"""A sync that extends a period while a consume is between resolving the
period and inserting its first rollup row: the row still gets the extended
end (``metering.sql._stored_end``)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from simple_module_db import finalize_session
from simple_module_test.database import database_is_postgres
from sm_billing import sync as sync_module
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


async def _setup(app, existing: bool) -> str:
    """A tenant on (START, FIRST_END); with ``existing``, a rollup row already."""
    tenant = await _tenant(app)
    await _sync(app, tenant, (START, FIRST_END))
    if existing:
        assert (await service(app, Clock(CLOCK)).consume(tenant, METER, 1, "k0", source="t")).ok
    return tenant


@postgres_only
@pytest.mark.parametrize("existing", [False, True], ids=["first-row", "row-exists"])
async def test_consume_during_a_sync_waits_and_stores_the_extension(app, monkeypatch, existing):
    """The real ``apply_snapshot`` is paused just after it extended the
    rollups, before its commit; a consume then starts. It must wait (on the
    subscription row the sync updated first), then store the extended end —
    and never deadlock with the sync's rollup update."""
    tenant = await _setup(app, existing)
    paused, go = asyncio.Event(), asyncio.Event()
    follow = sync_module._follow_period_end

    async def follow_then_pause(*args, **kwargs):
        await follow(*args, **kwargs)
        paused.set()
        await go.wait()

    monkeypatch.setattr(sync_module, "_follow_period_end", follow_then_pause)
    syncing = asyncio.create_task(_sync(app, tenant, (START, EXTENDED)))
    await asyncio.wait_for(paused.wait(), 10)
    consume = asyncio.create_task(
        service(app, Clock(CLOCK)).consume(tenant, METER, 3, "k1", source="t")
    )
    await asyncio.sleep(0.5)
    assert not consume.done()  # waiting on the subscription row
    go.set()
    await asyncio.wait_for(syncing, 10)
    assert (await asyncio.wait_for(consume, 10)).ok
    assert await _ends(app, tenant) == [(EXTENDED, 4 if existing else 3)]


@postgres_only
@pytest.mark.parametrize("existing", [False, True], ids=["first-row", "row-exists"])
async def test_sync_during_a_consume_waits_then_extends_the_row(app, existing):
    """A consume holding its locks (joined to a caller's transaction) when the
    real ``apply_snapshot`` runs: the sync waits on the subscription row, then
    extends the row the consume wrote."""
    tenant = await _setup(app, existing)
    async with app.state.sm.db.session_factory() as caller:
        outcome = await service(app, Clock(CLOCK)).consume(
            tenant, METER, 3, "k1", source="t", db=caller
        )
        assert outcome.ok
        syncing = asyncio.create_task(_sync(app, tenant, (START, EXTENDED)))
        await asyncio.sleep(0.5)
        assert not syncing.done()  # waiting on the subscription row
        await finalize_session(caller)
    await asyncio.wait_for(syncing, 10)
    assert await _ends(app, tenant) == [(EXTENDED, 4 if existing else 3)]
