"""The admin Subscriptions list: its rows and their count, per subject mode.

Tenant mode is driven from ``tenants_tenant`` here; user mode lives in
``admin_users``. The rows and the count share one FROM clause and one filter
builder per mode, so the pager's total cannot drift from the list.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select
from tenants.models import Tenant

from sm_billing import admin_users, subjects
from sm_billing import constants as c
from sm_billing.errors import BillingError
from sm_billing.lifecycle import tenant_service
from sm_billing.models import Plan, Subscription
from sm_billing.plans import PlanService

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy import ColumnElement
    from sqlalchemy.ext.asyncio import AsyncSession

    from sm_billing.schemas import SubscriptionRow


def _tenant_base(*columns):
    """The tenant list's FROM clause, shared by the rows and their count."""
    return (
        select(*columns)
        .select_from(Tenant)
        .outerjoin(Subscription, Subscription.tenant_id == Tenant.id)
        .outerjoin(Plan, Plan.id == Subscription.plan_id)
    )


def _tenant_filters(status: str | None, q: str | None) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = []
    if status:
        filters.append(Subscription.status == status)
    if q:
        filters.append(admin_users.tenant_search(q))
    return filters


async def subscription_count(
    db: AsyncSession, app: FastAPI, *, status: str | None = None, q: str | None = None
) -> int:
    """How many rows ``subscription_rows`` lists for the same ``status`` and ``q``."""
    q = (q or "").strip() or None
    if subjects.subject_mode(app) == c.SUBJECT_MODE_USER:
        return await admin_users.user_count(db, status=status, q=q)
    stmt = _tenant_base(func.count(Tenant.id)).where(*_tenant_filters(status, q))
    return (await db.execute(stmt)).scalar_one()


async def subscription_rows(
    db: AsyncSession,
    app: FastAPI,
    *,
    status: str | None = None,
    tenant_id: str | None = None,
    limit: int = c.ADMIN_ROW_LIMIT,
    offset: int = 0,
    q: str | None = None,
) -> list[SubscriptionRow]:
    """One page of the list; ``q`` searches it (``admin_users`` says how, per mode)."""
    default = await PlanService(db).default()
    q = (q or "").strip() or None
    if subjects.subject_mode(app) == c.SUBJECT_MODE_USER:
        return await admin_users.user_rows(
            db, default, status=status, subject=tenant_id, limit=limit, offset=offset, q=q
        )
    stmt = (
        _tenant_base(Tenant, Subscription, Plan)
        .where(*_tenant_filters(status, q))
        .order_by(Tenant.name, Tenant.id)
        .limit(limit)
        .offset(offset)
    )
    if tenant_id:
        stmt = stmt.where(Tenant.id == tenant_id)
    found = (await db.execute(stmt)).all()
    counts = await tenant_service(db, app).member_counts([t.id for t, _, _ in found])
    return [
        admin_users.row(
            tenant.id,
            tenant.name,
            tenant.slug,
            tenant.status,
            counts.get(tenant.id, 0),
            sub,
            # The subscribed plan even when lapsed — the status column says so.
            plan if plan is not None else default,
        )
        for tenant, sub, plan in found
    ]


async def one_row(db: AsyncSession, app: FastAPI, tenant_id: str) -> SubscriptionRow:
    rows = await subscription_rows(db, app, tenant_id=tenant_id, limit=1)
    if not rows:
        raise BillingError("tenant_not_found", 404)
    return rows[0]
