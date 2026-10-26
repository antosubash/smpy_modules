"""A provider that shortens a period (same start, earlier end): a consume that
resolved the old, longer period before the sync and writes after it stores
the subscription's new end, not its stale one (#240,
``metering.sql._sub_end``)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from simple_module_db import finalize_session
from simple_module_test.database import database_is_postgres
from sm_billing import sync as sync_module
from sm_billing.models import UsagePeriod
from sqlalchemy import select
from test_usage_period_extension import _ends, _sync, _tenant
from usage_helpers import METER, OCT, Clock, service

postgres_only = pytest.mark.skipif(not database_is_postgres(), reason="SM_TEST_DATABASE_URL")
SHORT = (OCT[0], datetime(2026, 10, 20, tzinfo=UTC))  # Oct 1 -> Oct 20
CLOCK = Clock()  # Oct 15: inside both


async def _setup(app, existing: bool) -> str:
    """A tenant on Oct 1 -> Nov 1; with ``existing``, a rollup row already."""
    tenant = await _tenant(app)
    await _sync(app, tenant, OCT)
    if existing:
        assert (await service(app, CLOCK).consume(tenant, METER, 1, "k0", source="t")).ok
    return tenant


async def _flags(app, tenant_id: str) -> list[bool]:
    async with app.state.sm.db.session_factory() as session:
        stmt = select(UsagePeriod.provider_period).where(UsagePeriod.tenant_id == tenant_id)
        return list((await session.execute(stmt)).scalars())


def _resolve_then_shorten(app, usage, tenant: str, moved=SHORT, resolved_as=OCT, later=None):
    """The consume resolves ``resolved_as``; before it writes, the sync moves
    the period to ``moved`` and (``later``) the clock moves on."""
    resolve = usage._resolve

    async def stale(*args, **kwargs):
        resolved = await resolve(*args, **kwargs)
        assert resolved.period == resolved_as and resolved.provider
        await _sync(app, tenant, moved)
        if later is not None:
            usage._clock.now = later
        return resolved

    usage._resolve = stale


@pytest.mark.parametrize("existing", [False, True], ids=["first-row", "row-exists"])
async def test_a_consume_resolved_before_a_shortening_stores_the_new_end(app, existing):
    """The issue's case: the consume resolved Oct 1 -> Nov 1, the sync then
    shortened it to Oct 20 (moving any row there), then the consume writes."""
    tenant = await _setup(app, existing)
    usage = service(app, CLOCK)
    _resolve_then_shorten(app, usage, tenant)
    outcome = await usage.consume(tenant, METER, 3, "k1", source="t")
    assert outcome.ok and outcome.period_end == SHORT[1]
    assert await _ends(app, tenant) == [(SHORT[1], 4 if existing else 3)]
    assert await _flags(app, tenant) == [True]


async def test_an_oversized_consume_on_a_credited_row_stores_the_new_end(app):
    """``qty > limit`` takes the plain ``UPDATE`` (``add_within_limit``); it
    follows the subscription's end the same way."""
    tenant = await _setup(app, existing=True)
    await service(app, CLOCK).adjust(tenant, METER, -50, reason="credit")
    usage = service(app, CLOCK)
    _resolve_then_shorten(app, usage, tenant)
    outcome = await usage.consume(tenant, METER, 120, "k1", source="t")  # limit 100
    assert outcome.ok and outcome.period_end == SHORT[1]
    assert await _ends(app, tenant) == [(SHORT[1], 71)]


@postgres_only
@pytest.mark.parametrize(
    ("existing", "qty", "used"),
    [(False, 3, 3), (True, 3, 4), (True, 120, 71)],
    ids=["first-row", "row-exists", "oversized-on-credit"],
)
async def test_consume_during_a_shortening_sync_waits_and_stores_the_new_end(
    app, monkeypatch, existing, qty, used
):
    """The real ``apply_snapshot`` is paused after its subscription update
    was flushed but before it moves the rollups; a consume that starts then
    must wait on the subscription row *before* it locks the rollup row, or
    the resumed sync's rollup update and the consume deadlock. It then
    stores the shorter end. ``oversized-on-credit`` takes the plain
    ``UPDATE`` (``add_within_limit``)."""
    tenant = await _setup(app, existing)
    if qty > 100:  # the plan's limit
        await service(app, CLOCK).adjust(tenant, METER, -50, reason="credit")
    paused, go = asyncio.Event(), asyncio.Event()
    follow = sync_module._follow_period_end

    async def pause_then_follow(*args, **kwargs):
        paused.set()
        await go.wait()
        await follow(*args, **kwargs)

    monkeypatch.setattr(sync_module, "_follow_period_end", pause_then_follow)
    syncing = asyncio.create_task(_sync(app, tenant, SHORT))
    await asyncio.wait_for(paused.wait(), 10)
    consume = asyncio.create_task(service(app, CLOCK).consume(tenant, METER, qty, "k1", source="t"))
    await asyncio.sleep(0.5)
    assert not consume.done()  # waiting on the subscription row
    go.set()
    await asyncio.wait_for(syncing, 10)
    assert (await asyncio.wait_for(consume, 10)).ok
    assert await _ends(app, tenant) == [(SHORT[1], used)]


@postgres_only
async def test_shortening_sync_during_a_consume_waits_then_moves_the_row(app):
    """A consume holding its locks in a caller's transaction: the shortening
    sync waits on the subscription row, then moves the row the consume wrote."""
    tenant = await _setup(app, existing=True)
    async with app.state.sm.db.session_factory() as caller:
        assert (await service(app, CLOCK).consume(tenant, METER, 3, "k1", source="t", db=caller)).ok
        syncing = asyncio.create_task(_sync(app, tenant, SHORT))
        await asyncio.sleep(0.5)
        assert not syncing.done()
        await finalize_session(caller)
    await asyncio.wait_for(syncing, 10)
    assert await _ends(app, tenant) == [(SHORT[1], 4)]


async def test_a_later_consume_never_restores_the_longer_end(app):
    """After the sync, every write in the period keeps the shorter end."""
    tenant = await _setup(app, existing=True)
    await _sync(app, tenant, SHORT)
    later = service(app, Clock(SHORT[1] - timedelta(days=1)))
    assert (await later.consume(tenant, METER, 1, "k1", source="t")).period_end == SHORT[1]
    assert await _ends(app, tenant) == [(SHORT[1], 2)]


async def test_a_period_that_already_ended_never_ends_a_calendar_month(app):
    """A missed webhook: the subscription's Oct 1 -> Oct 20 is over, so a
    call on Oct 25 counts against the calendar month, which shares its start.
    The row keeps the month's end, not the stale period's past one."""
    tenant = await _tenant(app)
    await _sync(app, tenant, SHORT)
    outcome = await service(app, Clock(datetime(2026, 10, 25, tzinfo=UTC))).consume(
        tenant, METER, 1, "k1", source="t"
    )
    assert outcome.ok and outcome.period_end == OCT[1]
    assert await _ends(app, tenant) == [(OCT[1], 1)]
    assert await _flags(app, tenant) == [False]


@pytest.mark.parametrize("existing", [False, True], ids=["first-row", "row-exists"])
async def test_a_shortening_to_an_end_already_past_still_lands(app, existing):
    """The consume resolved Oct 1 -> Nov 1 as the provider's; the sync then
    shortened it to Oct 20 and the write lands on Oct 25. A provider-resolved
    write takes the subscription's end even when it is past, so after the
    rollover the row is still found by its real boundaries."""
    tenant = await _setup(app, existing)
    usage = service(app, Clock(CLOCK.now))
    _resolve_then_shorten(app, usage, tenant, later=datetime(2026, 10, 25, tzinfo=UTC))
    assert (await usage.consume(tenant, METER, 3, "k1", source="t")).period_end == SHORT[1]
    assert await _ends(app, tenant) == [(SHORT[1], 4 if existing else 3)]
    assert await _flags(app, tenant) == [True]


async def test_an_extension_to_an_end_already_past_still_lands(app):
    """The same for an extension: resolved Oct 1 -> Oct 20, extended to
    Oct 22, written on Oct 25 — the first row stores Oct 22."""
    tenant = await _tenant(app)
    await _sync(app, tenant, SHORT)
    usage = service(app, Clock(CLOCK.now))
    extended = (OCT[0], datetime(2026, 10, 22, tzinfo=UTC))
    _resolve_then_shorten(
        app, usage, tenant, extended, SHORT, later=datetime(2026, 10, 25, tzinfo=UTC)
    )
    assert (await usage.consume(tenant, METER, 2, "k1", source="t")).period_end == extended[1]
    assert await _ends(app, tenant) == [(extended[1], 2)]
    assert await _flags(app, tenant) == [True]
