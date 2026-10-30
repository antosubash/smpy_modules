"""Builders shared by the usage-metering tests."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sm_billing.constants import PricingModel
from sm_billing.metering.registry import MeterRegistry
from sm_billing.metering.service import UsageService
from sm_billing.models import Plan, Subscription, UsageEvent, UsageGauge, UsageHold, UsagePeriod
from sm_billing.plans import seed_default_plan
from sqlalchemy import func, select

METER = "ai.requests"
GAUGE = "jobs.concurrent"
OCT = (datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC))
NOV = (datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC))
#: A ``swap`` deadline no test reaches.
FAR = datetime(2100, 1, 1, tzinfo=UTC)


@dataclass
class Clock:
    """A settable ``now`` for the service: rollover without waiting a month."""

    now: datetime = datetime(2026, 10, 15, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


async def seed_limits(factory, limits: dict[str, int] | None, **sub: Any) -> str:
    """A tenant on a plan with ``limits``, entitled; returns its id.

    No ``tenants_tenant`` row: nothing in metering reads it, which lets the
    file-based race tests build only billing's tables.
    """
    await seed_default_plan(factory)
    tenant_id = uuid.uuid4().hex
    async with factory() as session:
        plan = Plan(
            key=f"p-{tenant_id[:8]}",
            name="Team",
            pricing_model=PricingModel.FLAT,
            limits=limits or {},
        )
        session.add(plan)
        await session.flush()
        session.add(Subscription(tenant_id=tenant_id, plan_id=plan.id, **sub))
        await session.commit()
    return tenant_id


def service(app, clock: Clock | None = None) -> UsageService:
    factory = app.state.sm.db.session_factory
    return UsageService(factory, clock=clock) if clock else UsageService(factory)


async def used(factory, tenant_id: str, start: datetime, meter: str = METER) -> int | None:
    async with factory() as session:
        stmt = select(UsagePeriod.used).where(
            UsagePeriod.tenant_id == tenant_id,
            UsagePeriod.meter == meter,
            UsagePeriod.period_start == start,
        )
        return (await session.execute(stmt)).scalar_one_or_none()


async def events(factory, tenant_id: str, meter: str = METER, kind: str | None = None) -> int:
    async with factory() as session:
        stmt = (
            select(func.count())
            .select_from(UsageEvent)
            .where(UsageEvent.tenant_id == tenant_id, UsageEvent.meter == meter)
        )
        if kind is not None:
            stmt = stmt.where(UsageEvent.kind == kind)
        return int((await session.execute(stmt)).scalar_one())


def registry() -> MeterRegistry:
    """The counter and the gauge the tests meter, registered."""
    reg = MeterRegistry()
    reg.define(key=METER, kind="counter")
    reg.define(key=GAUGE, kind="gauge")
    return reg


def gauge_service(factory, clock: Clock | None = None, **kw: Any) -> UsageService:
    return UsageService(factory, clock=clock or Clock(), meters=kw.pop("meters", registry()), **kw)


async def in_use(factory, tenant_id: str, meter: str = GAUGE) -> int | None:
    async with factory() as session:
        stmt = select(UsageGauge.in_use).where(
            UsageGauge.tenant_id == tenant_id, UsageGauge.meter == meter
        )
        return (await session.execute(stmt)).scalar_one_or_none()


async def hold_statuses(factory, tenant_id: str, meter: str = GAUGE) -> list[str]:
    async with factory() as session:
        stmt = (
            select(UsageHold.status)
            .where(UsageHold.tenant_id == tenant_id, UsageHold.meter == meter)
            .order_by(UsageHold.status)
        )
        return list((await session.scalars(stmt)).all())
