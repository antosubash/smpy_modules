"""Write a provider snapshot onto the local mirror.

One function, used by webhooks, reconcile and the admin "Resync" button, so
there is exactly one place that decides how provider state becomes local
state. Failures raise ``SyncError`` rather than guessing: an unknown price or
tenant must never quietly hand a paying customer the default plan.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from simple_module_db import mark_written
from simple_module_db.tenancy import DEFAULT_TENANT_ID
from sqlalchemy import select

from sm_billing import subjects
from sm_billing.constants import ENTITLED_STATUSES, STRIPE_STATUS_MAP, SubscriptionStatus
from sm_billing.lifecycle import apply_lifecycle, is_multi_tenant
from sm_billing.metering.sql import extend_rollups
from sm_billing.models import Customer, Subscription
from sm_billing.plans import PlanService

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

    from sm_billing.contracts.provider import BillingProvider, SubscriptionSnapshot


class SyncError(Exception):
    """The snapshot cannot be mapped onto a tenant and plan."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


async def _tenant_for(db: AsyncSession, app: FastAPI, snap: SubscriptionSnapshot) -> str:
    """The billing subject (a tenant id or ``user:<id>``) the snapshot belongs to:
    its metadata when that subject still exists, else its customer's row.

    ``"default"`` is a subject only on a single-tenant host. On a multi-tenant
    one it is no tenant, so metadata naming it is not trusted: the customer
    row decides, or the snapshot is refused.
    """
    trusted = snap.tenant_id and (snap.tenant_id != DEFAULT_TENANT_ID or not is_multi_tenant(app))
    if trusted and await subjects.exists(db, snap.tenant_id):
        return snap.tenant_id
    if snap.customer_id:
        stmt = select(Customer).where(Customer.provider_customer_id == snap.customer_id)
        customer = (await db.execute(stmt)).scalar_one_or_none()
        if customer is not None:
            return customer.tenant_id
    raise SyncError("unknown_tenant", f"subscription {snap.id}")


async def _link_customer(db: AsyncSession, tenant_id: str, customer_id: str | None, provider: str):
    if not customer_id:
        return
    customer = await db.get(Customer, tenant_id)
    if customer is None:
        db.add(Customer(tenant_id=tenant_id, provider=provider, provider_customer_id=customer_id))
    elif customer.provider_customer_id != customer_id:
        customer.provider_customer_id = customer_id
        customer.provider = provider


async def _follow_period_end(db: AsyncSession, tenant_id: str, sub: Subscription):
    """A provider that moves a period's end (same start) moves its usage
    counters' stored end too, in this transaction: the stored end stays the
    period's real end, which is how the next period's "previous" finds it.
    Lapsed or not; which rows are the period's is ``extend_rollups``' rule."""
    if sub.current_period_start is None or sub.current_period_end is None:
        return
    await db.execute(
        extend_rollups(
            tenant_id=tenant_id,
            start=sub.current_period_start,
            end=sub.current_period_end,
            entitled=sub.status in ENTITLED_STATUSES,
        )
    )
    mark_written(db)


async def apply_snapshot(
    db: AsyncSession, app: FastAPI, snap: SubscriptionSnapshot, *, provider: str
) -> Subscription:
    """Upsert the tenant's subscription from ``snap`` and apply the lifecycle.

    Flushes, never commits (see ``apply_lifecycle`` for why the caller must
    finalize). Returns the tenant's subscription row.
    """
    status = STRIPE_STATUS_MAP.get(snap.status)
    if status is None:
        raise SyncError("unknown_status", snap.status)
    tenant_id = await _tenant_for(db, app, snap)
    stmt = select(Subscription).where(Subscription.tenant_id == tenant_id)
    sub = (await db.execute(stmt)).scalar_one_or_none()

    # A late event for a tenant's *previous* subscription (canceled before
    # they re-subscribed) must not overwrite the live one.
    if (
        sub is not None
        and sub.provider_subscription_id not in (None, snap.id)
        and status == SubscriptionStatus.CANCELED
    ):
        return sub

    match = await PlanService(db).by_price(snap.price_id) if snap.price_id else None
    if match is not None:
        plan_id, interval = match[0].id, match[1]
    elif sub is not None and status not in ENTITLED_STATUSES:
        # A lapse needs no plan: apply the cancel / "unpaid" on the plan they
        # had, so an unmappable price never keeps paid access alive.
        plan_id, interval = sub.plan_id, sub.interval
    elif sub is None and status not in ENTITLED_STATUSES:
        # A lapse of something never mirrored here (e.g. a checkout that was
        # abandoned on a since-deleted price): there is no access to revoke.
        raise SyncError("nothing_to_apply", f"{snap.status} on {snap.price_id or '(none)'}")
    else:
        raise SyncError("unknown_price", snap.price_id or "(none)")

    await _link_customer(db, tenant_id, snap.customer_id, provider)
    if sub is None:
        sub = Subscription(tenant_id=tenant_id, plan_id=plan_id)
        db.add(sub)
    sub.plan_id = plan_id
    sub.status = status
    sub.interval = interval
    sub.provider_subscription_id = snap.id
    sub.quantity = max(1, snap.quantity)
    sub.trial_end = snap.trial_end
    sub.current_period_start = snap.current_period_start
    sub.current_period_end = snap.current_period_end
    sub.cancel_at_period_end = snap.cancel_at_period_end
    sub.synced_at = datetime.now(UTC)
    # Subscription first, rollups second: the same lock order as a consume
    # (its insert reads the subscription row FOR SHARE, then writes the
    # rollup), so the two wait on each other instead of deadlocking, and a
    # consume that has not inserted yet waits for this period end.
    await db.flush()
    await _follow_period_end(db, tenant_id, sub)
    await apply_lifecycle(db, app, sub)
    return sub


async def resync(
    db: AsyncSession, app: FastAPI, provider: BillingProvider, subscription_id: str
) -> Subscription:
    """Re-fetch ``subscription_id`` from the provider and apply it."""
    snapshot = await provider.fetch_subscription(subscription_id)
    return await apply_snapshot(db, app, snapshot, provider=provider.name)
