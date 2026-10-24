"""Platform-admin operations: plan writes with price checks, the tenant list,
manual assignment, resync, and the Stripe connection settings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from tenants.models import Tenant

from sm_billing import constants as c
from sm_billing import crypto
from sm_billing.contracts.provider import ProviderError
from sm_billing.errors import BillingError
from sm_billing.lifecycle import apply_lifecycle, tenant_service
from sm_billing.models import Plan, Subscription, WebhookEvent
from sm_billing.plans import PlanService
from sm_billing.resolve import subscription_for
from sm_billing.schemas import (
    ConnectionIn,
    ConnectionOut,
    PlanIn,
    SubscriptionRow,
    SyncHealth,
    normalise_return_url,
)
from sm_billing.services import current_provider
from sm_billing.sync import resync as resync_subscription

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

    from sm_billing.schemas import AssignIn

_CLEAR_FLAGS = {
    "clear_secret_key": "stripe_secret_key",
    "clear_webhook_secret": "stripe_webhook_secret",
}


def _services(app: FastAPI):
    return getattr(app.state, c.PACKAGE)


# ── plans ───────────────────────────────────────────────────────────


async def verify_prices(app: FastAPI, data: PlanIn, existing: Plan | None = None) -> None:
    """Under Stripe, each price must exist, be active, and match currency + interval.

    A price the plan already carries is not re-checked: Stripe prices get
    archived over time, and that must not lock the plan against unrelated
    edits (renaming, hiding, limits).
    """
    provider = _services(app).provider
    if provider is None or not provider.supports_checkout:
        return
    for interval, price_id, current in (
        (
            c.Interval.MONTH,
            data.stripe_price_month,
            existing.stripe_price_month if existing else None,
        ),
        (c.Interval.YEAR, data.stripe_price_year, existing.stripe_price_year if existing else None),
    ):
        if not price_id or (
            price_id == current and existing and existing.currency == data.currency
        ):
            continue
        try:
            info = await provider.verify_price(price_id)
        except ProviderError as exc:
            raise BillingError("price_not_found", price=price_id, reason=str(exc)) from exc
        reason = ""
        if not info.active:
            reason = "price is archived in Stripe"
        elif info.currency != data.currency:
            reason = f"currency {info.currency} ≠ plan currency {data.currency}"
        elif info.interval != interval:
            reason = f"interval {info.interval} ≠ {interval}"
        if reason:
            raise BillingError("price_mismatch", price=price_id, reason=reason)


async def save_plan(db: AsyncSession, app: FastAPI, data: PlanIn, plan_id: int | None) -> Plan:
    plans = PlanService(db)
    await verify_prices(app, data, await plans.get(plan_id) if plan_id is not None else None)
    return await plans.create(data) if plan_id is None else await plans.update(plan_id, data)


# ── subscriptions ───────────────────────────────────────────────────


async def subscription_rows(
    db: AsyncSession,
    app: FastAPI,
    *,
    status: str | None = None,
    tenant_id: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[SubscriptionRow]:
    default = await PlanService(db).default()
    stmt = (
        select(Tenant, Subscription, Plan)
        .outerjoin(Subscription, Subscription.tenant_id == Tenant.id)
        .outerjoin(Plan, Plan.id == Subscription.plan_id)
        .order_by(Tenant.name, Tenant.id)
        .limit(limit)
        .offset(offset)
    )
    if status:
        stmt = stmt.where(Subscription.status == status)
    if tenant_id:
        stmt = stmt.where(Tenant.id == tenant_id)
    found = (await db.execute(stmt)).all()
    counts = await tenant_service(db, app).member_counts([t.id for t, _, _ in found])
    rows = []
    for tenant, sub, plan in found:
        # The subscribed plan even when lapsed — the status column says so.
        shown = plan if plan is not None else default
        rows.append(
            SubscriptionRow(
                tenant_id=tenant.id,
                tenant_name=tenant.name,
                tenant_slug=tenant.slug,
                tenant_status=tenant.status,
                members=counts.get(tenant.id, 0),
                plan_id=shown.id,
                plan_key=shown.key,
                plan_name=shown.name,
                status=sub.status if sub else None,
                interval=sub.interval if sub else None,
                quantity=sub.quantity if sub else None,
                current_period_end=sub.current_period_end if sub else None,
                cancel_at_period_end=bool(sub and sub.cancel_at_period_end),
                suspended_by_billing=bool(sub and sub.suspended_by_billing),
                provider_subscription_id=sub.provider_subscription_id if sub else None,
                synced_at=sub.synced_at if sub else None,
            )
        )
    return rows


async def sync_health(db: AsyncSession, app: FastAPI) -> SyncHealth:
    """The numbers that show a missed webhook before a customer does (#122)."""
    held = Subscription.provider_subscription_id.is_not(None)
    oldest, never = (
        await db.execute(
            select(
                func.min(Subscription.synced_at),
                func.count().filter(Subscription.synced_at.is_(None)),
            ).where(held)
        )
    ).one()
    stmt = select(func.count()).where(WebhookEvent.processed_at.is_(None))
    unprocessed = (await db.execute(stmt)).scalar_one()
    services = _services(app)
    return SyncHealth(
        oldest_synced_at=oldest,
        never_synced=never or 0,
        unprocessed_webhooks=unprocessed,
        reconcile_interval_minutes=services.settings.reconcile_interval_minutes,
        reconcile_running=bool(services.scheduler and services.scheduler.running),
    )


async def one_row(db: AsyncSession, app: FastAPI, tenant_id: str) -> SubscriptionRow:
    rows = await subscription_rows(db, app, tenant_id=tenant_id, limit=1)
    if not rows:
        raise BillingError("tenant_not_found", 404)
    return rows[0]


async def assign(db: AsyncSession, app: FastAPI, tenant_id: str, data: AssignIn) -> None:
    """Manual provider only: set the tenant's plan and status directly.

    The provider's period goes with its subscription id: a manual assignment
    has no provider period, so usage counters fall back to the calendar month
    (``metering.periods``) instead of running on a Stripe period that no
    longer bills anyone. ``trial_end`` stays: it is the trial history that
    ``checkout._trial_used`` reads, so a tenant that spent its trial does not
    get a second one after moving back to Stripe.
    """
    if current_provider(app).supports_checkout:
        raise BillingError("provider_managed", 409)
    if await db.get(Tenant, tenant_id) is None:
        raise BillingError("tenant_not_found", 404)
    plan = await PlanService(db).get(data.plan_id)
    if plan is None:
        raise BillingError("plan_not_found", 404)
    sub = await subscription_for(db, tenant_id)
    if sub is None:
        sub = Subscription(tenant_id=tenant_id, plan_id=plan.id)
        db.add(sub)
    sub.plan_id = plan.id
    sub.status = data.status
    sub.interval = data.interval
    sub.provider_subscription_id = None
    sub.current_period_start = None
    sub.current_period_end = None
    sub.cancel_at_period_end = False
    await db.flush()
    await apply_lifecycle(db, app, sub)


async def resync(db: AsyncSession, app: FastAPI, tenant_id: str) -> None:
    provider = current_provider(app)
    if not provider.supports_checkout:
        raise BillingError("checkout_unavailable", 409)
    sub = await subscription_for(db, tenant_id)
    if sub is None or sub.provider_subscription_id is None:
        raise BillingError("no_provider_subscription", 409)
    await resync_subscription(db, app, provider, sub.provider_subscription_id)


# ── connection ──────────────────────────────────────────────────────


def connection_out(app: FastAPI) -> ConnectionOut:
    services = _services(app)
    s = services.settings
    return ConnectionOut(
        provider=s.provider,
        active_provider=services.provider.name if services.provider else "",
        provider_error=services.provider_error,
        has_secret_key=bool(s.stripe_secret_key),
        has_webhook_secret=bool(s.stripe_webhook_secret),
        return_base_url=s.return_base_url,
        webhook_path=c.WEBHOOK_PATH,
    )


def connection_changes(data: ConnectionIn) -> dict[str, Any]:
    """Blank secret = keep; a value is stripped and encrypted; ``clear_*`` wins."""
    try:
        return_base_url = normalise_return_url(data.return_base_url)
    except ValueError as exc:
        raise BillingError("invalid_return_url", message=str(exc)) from exc
    changes: dict[str, Any] = {"return_base_url": return_base_url}
    for field in c.SECRET_FIELDS:
        value = getattr(data, field).strip()
        if value:
            changes[field] = crypto.encrypt_value(value)
    for flag, field in _CLEAR_FLAGS.items():
        if getattr(data, flag):
            changes[field] = ""
    return changes


async def save_connection(db: AsyncSession, app: FastAPI, data: ConnectionIn) -> ConnectionOut:
    from settings.reload import apply_changes_and_reload
    from settings.service import SettingService
    from settings.store import SettingsStore

    store = SettingsStore(SettingService(db))
    await apply_changes_and_reload(
        app, app.state.sm.event_bus, store, package=c.PACKAGE, changes=connection_changes(data)
    )
    # The reload published ``SettingsReloaded``; ``sm_billing.live`` has rebuilt
    # the provider (and the reconcile loop) from the new secrets by now.
    return connection_out(app)
