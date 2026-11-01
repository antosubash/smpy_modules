"""The admin usage screen's per-tenant drawer: ledger, holds and the repairs.

Platform admin spans tenants (like the rest of ``sm_billing.admin``), so the
tenant comes from the path, and every query here still filters on it — the
usage tables carry no ``MultiTenantMixin``. Writes go through
``UsageService`` (its own short transactions, ``finalize_session``), never
through the request session.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from simple_module_db.tenancy import DEFAULT_TENANT_ID
from sqlalchemy import func, select

from sm_billing import constants as c
from sm_billing import subjects
from sm_billing.contracts.metering import LIVE_HOLD_STATUSES, MeterKind
from sm_billing.errors import BillingError
from sm_billing.lifecycle import is_multi_tenant
from sm_billing.metering.periods import as_utc
from sm_billing.metering.report import page_numbers, tenant_summary
from sm_billing.metering.schemas import (
    MeterOut,
    MeterUsageOut,
    UsageEventOut,
    UsageEventPageOut,
    UsageHoldOut,
)
from sm_billing.models import UsageEvent, UsageHold

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

    from sm_billing.metering.registry import MeterRegistry
    from sm_billing.metering.service import UsageService

#: ``status`` filter value for "held or committed" — the holds that count.
LIVE = "live"
#: Ledger kinds the drawer's filter offers (``metering.validate``'s vocabulary).
KINDS = ("consume", "record", "refund", "adjust")


def registry(app: FastAPI) -> MeterRegistry | None:
    return getattr(app.state, c.METERS_STATE_ATTR, None)


def usage(app: FastAPI) -> UsageService:
    meter = getattr(app.state, c.USAGE_STATE_ATTR, None)
    if meter is None:  # pragma: no cover - installed in on_startup, before any request
        raise BillingError("usage_unavailable", 503)
    return meter


async def tenant_usage(db: AsyncSession, app: FastAPI, tenant_id: str) -> list[MeterUsageOut]:
    """The tenant's usage card, read through the request's session.

    Empty while billing has not started (no ``UsageService`` yet): the card
    then hides, as it does on a host that registers no meters.
    """
    service = getattr(app.state, c.USAGE_STATE_ATTR, None)
    if service is None:
        return []
    return await tenant_summary(db, registry(app), tenant_id, service.now())


def meters(app: FastAPI) -> list[MeterOut]:
    reg = registry(app)
    return [
        MeterOut(key=d.key, kind=d.kind.value, unit=d.unit, label_key=d.label_key)
        for d in (reg or [])
    ]


def require_meter(app: FastAPI, meter: str, kind: MeterKind) -> None:
    """400 ``unknown_meter`` unless ``meter`` is a registered ``kind`` meter."""
    reg = registry(app)
    definition = reg.get(meter) if reg is not None else None
    if definition is None or definition.kind is not kind:
        raise BillingError("unknown_meter", 400, meter=meter, kind=kind.value)


async def require_tenant(db: AsyncSession, app: FastAPI, tenant_id: str) -> None:
    """An adjustment names a real subject: an organisation, a user (user mode),
    or, on a single-tenant host only, the one tenant everything is metered as
    (``RequiresQuota``'s ``default``) — on a multi-tenant host it is none."""
    if tenant_id == DEFAULT_TENANT_ID:
        if not is_multi_tenant(app):
            return
        raise BillingError("tenant_not_found", 404)
    if not await subjects.exists(db, tenant_id):
        raise BillingError("tenant_not_found", 404)


async def ledger(
    db: AsyncSession,
    tenant_id: str,
    *,
    meter: str | None = None,
    kind: str | None = None,
    page: int = 1,
    per_page: int = 25,
) -> UsageEventPageOut:
    """The tenant's ledger, newest first."""
    where = [UsageEvent.tenant_id == tenant_id]
    if meter:
        where.append(UsageEvent.meter == meter)
    if kind:
        where.append(UsageEvent.kind == kind)
    total = int(
        (await db.execute(select(func.count()).select_from(UsageEvent).where(*where))).scalar_one()
    )
    served, pages = page_numbers(total, page, per_page)
    stmt = (
        select(UsageEvent)
        .where(*where)
        .order_by(UsageEvent.id.desc())
        .offset((served - 1) * per_page)
        .limit(per_page)
    )
    items = [
        UsageEventOut(
            id=e.id,
            meter=e.meter,
            kind=e.kind,
            quantity=int(e.quantity),
            idempotency_key=e.idempotency_key,
            source=e.source,
            actor=e.actor,
            reason=e.reason,
            period_start=None if e.period_start is None else as_utc(e.period_start),
            occurred_at=as_utc(e.occurred_at),
            recorded_at=as_utc(e.recorded_at),
        )
        for e in (await db.scalars(stmt)).all()
    ]
    return UsageEventPageOut(items=items, total=total, page=served, per_page=per_page, pages=pages)


#: The most holds one drawer lists; a tenant with more has a bug to look at.
HOLDS_MAX = 200


async def holds(
    db: AsyncSession, tenant_id: str, *, meter: str | None = None, status: str = LIVE
) -> list[UsageHoldOut]:
    """The tenant's holds in ``status`` (default: held or committed), newest first."""
    statuses = sorted(LIVE_HOLD_STATUSES) if status == LIVE else [status]
    stmt = select(UsageHold).where(UsageHold.tenant_id == tenant_id, UsageHold.status.in_(statuses))
    if meter:
        stmt = stmt.where(UsageHold.meter == meter)
    stmt = stmt.order_by(UsageHold.created_at.desc(), UsageHold.id).limit(HOLDS_MAX)
    return [
        UsageHoldOut(
            id=h.id,
            meter=h.meter,
            quantity=int(h.quantity),
            status=h.status,
            idempotency_key=h.idempotency_key,
            source=h.source,
            expires_at=None if h.expires_at is None else as_utc(h.expires_at),
            created_at=as_utc(h.created_at),
            settled_at=None if h.settled_at is None else as_utc(h.settled_at),
        )
        for h in (await db.scalars(stmt)).all()
    ]
