"""A provider that extends a period (same start, later end) moves its usage
counters' stored end too, so after the rollover that period is still found
as "previous" — through the snapshot sync and through a consume."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from api_helpers import arm_csrf
from helpers import make_plan, make_tenant
from simple_module_db import finalize_session
from sm_billing.contracts.provider import SubscriptionSnapshot
from sm_billing.metering.periods import calendar_month
from sm_billing.models import Subscription, UsagePeriod
from sm_billing.sync import apply_snapshot
from sqlalchemy import select, update
from usage_helpers import METER, Clock, service

ADMIN = "/api/billing/admin/usage"
NOW = datetime.now(UTC).replace(microsecond=0)
START = NOW - timedelta(days=50)
FIRST_END = NOW - timedelta(days=20)  # the period as first synced
EXTENDED = NOW - timedelta(days=10)  # the provider moved the end out
NEXT = (EXTENDED, NOW + timedelta(days=20))  # the period after: current now


@pytest.fixture
async def admin(authenticated_client):
    await arm_csrf(authenticated_client, "/admin/billing/usage")
    return authenticated_client


def _snap(
    tenant_id: str, period: tuple[datetime, datetime], status: str = "active"
) -> SubscriptionSnapshot:
    return SubscriptionSnapshot(
        id="sub_1",
        customer_id="cus_1",
        tenant_id=tenant_id,
        status=status,
        price_id="price_team_m",
        quantity=1,
        trial_end=None,
        current_period_end=period[1],
        cancel_at_period_end=False,
        current_period_start=period[0],
    )


async def _sync(
    app, tenant_id: str, period: tuple[datetime, datetime], status: str = "active"
) -> None:
    async with app.state.sm.db.session_factory() as session:
        await apply_snapshot(session, app, _snap(tenant_id, period, status), provider="stripe")
        await finalize_session(session)


async def _tenant(app) -> str:
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session, "acme")
        await make_plan(session, "team", limits={METER: 100})
        await finalize_session(session)
        return tenant.id


async def _ends(app, tenant_id: str) -> list[tuple[datetime, int]]:
    async with app.state.sm.db.session_factory() as session:
        stmt = select(UsagePeriod.period_end, UsagePeriod.used).where(
            UsagePeriod.tenant_id == tenant_id
        )
        return [(end.replace(tzinfo=UTC), used) for end, used in (await session.execute(stmt))]


async def _previous(admin) -> list[tuple[str, int, str]]:
    items = (await admin.get(ADMIN, params={"period": "previous"})).json()["items"]
    return [(r["meter"], r["used"], r["period_end"][:16]) for r in items]


async def test_snapshot_extension_moves_the_stored_end(app, admin):
    tenant = await _tenant(app)
    await _sync(app, tenant, (START, FIRST_END))
    usage = service(app, Clock(START + timedelta(days=1)))
    assert (await usage.consume(tenant, METER, 4, "k1", source="t")).ok
    assert await _ends(app, tenant) == [(FIRST_END, 4)]

    await _sync(app, tenant, (START, EXTENDED))  # same start, later end
    assert await _ends(app, tenant) == [(EXTENDED, 4)]

    await _sync(app, tenant, NEXT)  # rollover: the extended period is previous
    assert await _previous(admin) == [(METER, 4, EXTENDED.isoformat()[:16])]


async def test_a_consume_after_the_extension_moves_the_stored_end(app, admin):
    tenant = await _tenant(app)
    await _sync(app, tenant, (START, FIRST_END))
    assert (
        await service(app, Clock(START + timedelta(days=1))).consume(
            tenant, METER, 2, "k1", source="t"
        )
    ).ok
    # The extension reaches the subscription without the sync's rollup step
    # (say, a row written by an older build): the next write in the
    # extended period carries the resolved end into the row.
    async with app.state.sm.db.session_factory() as session:
        await session.execute(
            update(Subscription)
            .where(Subscription.tenant_id == tenant)
            .values(current_period_end=EXTENDED)
        )
        await session.commit()
    late = service(app, Clock(FIRST_END + timedelta(days=2)))
    assert (await late.consume(tenant, METER, 3, "k2", source="t")).ok
    assert await _ends(app, tenant) == [(EXTENDED, 5)]

    await _sync(app, tenant, NEXT)
    assert await _previous(admin) == [(METER, 5, EXTENDED.isoformat()[:16])]


async def test_a_write_resolving_an_earlier_end_never_moves_it_back(app):
    """A consume that resolved the period before a concurrent extension
    landed must not undo the extension: the subscription's end wins."""
    tenant = await _tenant(app)
    await _sync(app, tenant, (START, EXTENDED))
    usage = service(app, Clock(START + timedelta(days=1)))
    assert (await usage.consume(tenant, METER, 1, "k1", source="t")).ok
    resolve = usage._resolve

    async def stale(*args, **kwargs):  # the view from before the extension
        return replace(await resolve(*args, **kwargs), period=(START, FIRST_END))

    usage._resolve = stale
    outcome = await usage.consume(tenant, METER, 1, "k2", source="t")
    assert outcome.ok and outcome.period_end == EXTENDED
    assert await _ends(app, tenant) == [(EXTENDED, 2)]


async def test_an_older_period_is_still_not_previous(app, admin):
    """Two periods back stays out, extension or not."""
    tenant = await _tenant(app)
    older = (START - timedelta(days=30), START)
    await _sync(app, tenant, older)
    assert (
        await service(app, Clock(older[0] + timedelta(days=1))).consume(
            tenant, METER, 7, "k1", source="t"
        )
    ).ok
    # The period after it had no usage; then today's period.
    await _sync(app, tenant, (START, EXTENDED))
    await _sync(app, tenant, NEXT)
    assert await _previous(admin) == []


async def test_a_lapsed_subscription_never_moves_a_calendar_month(app):
    """A canceled subscription's counters are calendar months; one whose
    start coincides with the month's keeps the month's end, through a
    consume and through the snapshot sync."""
    tenant = await _tenant(app)
    month = calendar_month(NOW)
    yearly = (month[0], month[0] + timedelta(days=365))
    await _sync(app, tenant, yearly)
    await _sync(app, tenant, yearly, status="canceled")
    assert (await service(app, Clock(NOW)).consume(tenant, METER, 1, "k1", source="t")).ok
    await _sync(app, tenant, yearly, status="canceled")
    assert await _ends(app, tenant) == [(month[1], 1)]


async def test_a_lapse_still_corrects_the_end_of_its_own_period(app, admin):
    """Rows written while the subscription was in force are its period's: a
    lapsed snapshot that moves that period's end moves theirs, so after the
    recovery they are still "previous"."""
    tenant = await _tenant(app)
    await _sync(app, tenant, (START, FIRST_END))
    assert (
        await service(app, Clock(START + timedelta(days=1))).consume(
            tenant, METER, 4, "k1", source="t"
        )
    ).ok
    await _sync(app, tenant, (START, EXTENDED), status="unpaid")
    assert await _ends(app, tenant) == [(EXTENDED, 4)]

    await _sync(app, tenant, NEXT)  # recovered into the next period
    assert await _previous(admin) == [(METER, 4, EXTENDED.isoformat()[:16])]


async def test_a_lapse_corrects_a_provider_period_that_matches_a_calendar_month(app, admin):
    """A provider period aligned to a calendar month: its rows are still the
    provider's (recorded when written, not guessed from the boundaries), so
    a lapsed snapshot moving its end moves theirs."""
    tenant = await _tenant(app)
    start = calendar_month(NOW - timedelta(days=40))[0]
    aligned = (start, calendar_month(start)[1])  # Sep 1 -> Oct 1, say
    await _sync(app, tenant, aligned)
    usage = service(app, Clock(start + timedelta(days=1)))
    assert (await usage.consume(tenant, METER, 2, "k1", source="t")).ok
    moved = aligned[1] + timedelta(days=9)
    await _sync(app, tenant, (start, moved), status="unpaid")
    assert await _ends(app, tenant) == [(moved, 2)]

    await _sync(app, tenant, (moved, moved + timedelta(days=60)))
    assert await _previous(admin) == [(METER, 2, moved.isoformat()[:16])]
