"""Read side of the usage screens: the tenant's card and the admin overview.

Both read the same thing the enforcement reads — the plan in force
(``resolve.effective_plan``'s rule) and the period ``periods.current_period``
picks — so the numbers on screen are the ones the next ``consume`` is held
to. The overview does it for many tenants at once, in three queries rather
than three per tenant.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from tenants.models import Tenant

from sm_billing.constants import ENTITLED_STATUSES
from sm_billing.contracts.metering import LIVE_HOLD_STATUSES, MeterKind
from sm_billing.metering.periods import as_utc, current_period, previous_period
from sm_billing.metering.schemas import MeterUsageOut, Period, UsagePageOut, UsageRowOut
from sm_billing.models import Plan, Subscription, UsageGauge, UsageHold, UsagePeriod
from sm_billing.plans import PlanService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from sm_billing.contracts.metering import MeterDefinition
    from sm_billing.metering.registry import MeterRegistry

#: How far back a rollup can start and still be the current or previous period:
#: two annual periods plus margin.
PREVIOUS_LOOKBACK = timedelta(days=800)
#: The "over 80%" filter's threshold.
OVER_PERCENT = 80.0


@dataclass(frozen=True)
class TenantPlan:
    limits: dict[str, int]
    period: tuple[datetime, datetime]
    #: The period immediately before ``period`` (its end is ``period``'s start).
    previous: tuple[datetime, datetime]


async def plan_contexts(
    session: AsyncSession, tenant_ids: Iterable[str], now: datetime
) -> dict[str, TenantPlan]:
    """Each tenant's limits and current period, ``effective_plan``'s rule batched."""
    ids = sorted(set(tenant_ids))
    if not ids:
        return {}
    default = await PlanService(session).default()
    subs = {
        s.tenant_id: s
        for s in (
            await session.scalars(select(Subscription).where(Subscription.tenant_id.in_(ids)))
        ).all()
    }
    wanted = {s.plan_id for s in subs.values() if s.status in ENTITLED_STATUSES}
    plans = (
        {p.id: p for p in (await session.scalars(select(Plan).where(Plan.id.in_(wanted)))).all()}
        if wanted
        else {}
    )
    out: dict[str, TenantPlan] = {}
    for tenant_id in ids:
        sub = subs.get(tenant_id)
        entitled = sub is not None and sub.status in ENTITLED_STATUSES
        plan = (plans.get(sub.plan_id) if entitled and sub else None) or default
        limits = {k: int(v) for k, v in (plan.limits or {}).items()}
        period = current_period(sub, now)
        out[tenant_id] = TenantPlan(limits, period, previous_period(sub, now))
    return out


async def _gauge_levels(session: AsyncSession, tenant_ids: list[str] | None, meter=None):
    stmt = select(UsageGauge.tenant_id, UsageGauge.meter, UsageGauge.in_use)
    if tenant_ids is not None:
        stmt = stmt.where(UsageGauge.tenant_id.in_(tenant_ids))
    if meter:
        stmt = stmt.where(UsageGauge.meter == meter)
    return (await session.execute(stmt)).all()


async def tenant_summary(
    session: AsyncSession, registry: MeterRegistry | None, tenant_id: str, now: datetime
) -> list[MeterUsageOut]:
    """One row per registered meter the plan limits or the tenant has used."""
    if registry is None:
        return []
    ctx = (await plan_contexts(session, [tenant_id], now))[tenant_id]
    start, end = ctx.period
    counted = await session.execute(
        select(UsagePeriod.meter, UsagePeriod.used).where(
            UsagePeriod.tenant_id == tenant_id, UsagePeriod.period_start == start
        )
    )
    counters = {meter: int(used) for meter, used in counted.all()}
    gauges = {m: int(level) for _, m, level in await _gauge_levels(session, [tenant_id])}
    live = await session.execute(
        select(UsageHold.meter, func.count())
        .where(
            UsageHold.tenant_id == tenant_id,
            UsageHold.status.in_(sorted(LIVE_HOLD_STATUSES)),
        )
        .group_by(UsageHold.meter)
    )
    holds = {meter: int(n) for meter, n in live.all()}
    rows: list[MeterUsageOut] = []
    for definition in registry:
        limit = ctx.limits.get(definition.key)
        counter = definition.kind is MeterKind.COUNTER
        used = (counters if counter else gauges).get(definition.key)
        if used is None and limit is None:
            continue
        rows.append(
            MeterUsageOut(
                meter=definition.key,
                kind=definition.kind.value,
                unit=definition.unit,
                label_key=definition.label_key,
                used=used or 0,
                limit=limit,
                period_start=start if counter else None,
                period_end=end if counter else None,
                holds=None if counter else holds.get(definition.key, 0),
            )
        )
    return rows


def percent(used: int, limit: int | None) -> float | None:
    if limit is None:
        return None
    if limit <= 0:
        return 100.0 if used > 0 else 0.0
    return round(used * 100.0 / limit, 1)


async def _counter_rows(session, now: datetime, meter: str | None):
    """Every rollup that can be a tenant's current or previous period."""
    cols = (UsagePeriod.tenant_id, UsagePeriod.meter, UsagePeriod.used)
    stmt = select(*cols, UsagePeriod.period_start, UsagePeriod.period_end).where(
        UsagePeriod.period_start <= now, UsagePeriod.period_start > now - PREVIOUS_LOOKBACK
    )
    if meter:
        stmt = stmt.where(UsagePeriod.meter == meter)
    return (await session.execute(stmt)).all()


def _pick_counters(rows, ctx: dict[str, TenantPlan], period: Period) -> dict[tuple, tuple]:
    """``{(tenant, meter): (used, start, end)}`` for the period asked for.

    Current: the rollup whose ``period_start`` is the tenant's resolved
    current start (the row enforcement counts into), shown with the resolved
    end: a provider that extends a period keeps its start, so the row's
    stored end can be stale. Previous: the rollup of the period immediately
    before, matched on either of its exact boundaries; a tenant that used
    nothing then has no row, never an older one.
    """
    picked: dict[tuple, tuple] = {}
    for row in rows:
        plan = ctx[row.tenant_id]
        row_start, row_end = as_utc(row.period_start), as_utc(row.period_end)
        if period == "current":
            if row_start != plan.period[0]:
                continue
            shown = plan.period
        else:
            prev_start, prev_end = plan.previous
            if row_start >= prev_end or (row_start != prev_start and row_end != prev_end):
                continue
            shown = (row_start, prev_end)
        key = (row.tenant_id, row.meter)
        best = picked.get(key)
        if best is None or best[1] < row_start:
            picked[key] = (int(row.used), *shown)
    return picked


async def _tenant_names(session, ids: list[str]) -> dict[str, tuple[str, str]]:
    if not ids:
        return {}
    stmt = select(Tenant.id, Tenant.name, Tenant.slug).where(Tenant.id.in_(ids))
    return {tid: (name, slug) for tid, name, slug in (await session.execute(stmt)).all()}


def _matches(row: UsageRowOut, query: str) -> bool:
    haystack = (row.tenant_id, row.tenant_name.lower(), row.tenant_slug.lower())
    return any(query in value for value in haystack)


def page_numbers(total: int, page: int, per_page: int) -> tuple[int, int]:
    """``(page actually served, page count)``: a stale link lands on the last page."""
    pages = max(1, math.ceil(total / max(per_page, 1)))
    return min(max(page, 1), pages), pages


async def overview(
    session: AsyncSession,
    registry: MeterRegistry | None,
    now: datetime,
    *,
    meter: str | None = None,
    query: str = "",
    over: bool = False,
    period: Period = "current",
    page: int = 1,
    per_page: int = 25,
) -> UsagePageOut:
    """Every tenant x meter with usage, fullest first, filtered and paged."""
    counters = await _counter_rows(session, now, meter)
    gauges = await _gauge_levels(session, None, meter) if period == "current" else []
    ids = sorted({r.tenant_id for r in counters} | {r.tenant_id for r in gauges})
    ctx = await plan_contexts(session, ids, now)
    names = await _tenant_names(session, ids)
    picked = _pick_counters(counters, ctx, period)
    raw = [
        (tenant_id, key, MeterKind.COUNTER, used, start, end)
        for (tenant_id, key), (used, start, end) in picked.items()
    ]
    raw += [(r.tenant_id, r.meter, MeterKind.GAUGE, int(r.in_use), None, None) for r in gauges]
    rows: list[UsageRowOut] = []
    for tenant_id, key, kind, used, start, end in raw:
        definition: MeterDefinition | None = registry.get(key) if registry else None
        limit = ctx[tenant_id].limits.get(key)
        name, slug = names.get(tenant_id, (tenant_id, ""))
        rows.append(
            UsageRowOut(
                tenant_id=tenant_id,
                tenant_name=name,
                tenant_slug=slug,
                meter=key,
                kind=kind.value,
                unit=definition.unit if definition else "count",
                label_key=definition.label_key if definition else "",
                registered=definition is not None and definition.kind is kind,
                used=used,
                limit=limit,
                percent=percent(used, limit),
                period_start=None if start is None else as_utc(start),
                period_end=None if end is None else as_utc(end),
            )
        )
    needle = query.strip().lower()
    if needle:
        rows = [r for r in rows if _matches(r, needle)]
    if over:
        rows = [r for r in rows if r.percent is not None and r.percent >= OVER_PERCENT]
    rows.sort(key=lambda r: (r.percent is None, -(r.percent or 0), r.tenant_name, r.meter))
    served, pages = page_numbers(len(rows), page, per_page)
    offset = (served - 1) * per_page
    return UsagePageOut(
        items=rows[offset : offset + per_page],
        total=len(rows),
        page=served,
        per_page=per_page,
        pages=pages,
    )
