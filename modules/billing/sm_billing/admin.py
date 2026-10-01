"""Platform-admin operations: plan writes with price checks, the tenant list,
manual assignment, resync, and the Stripe connection settings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from tenants.models import Tenant

from sm_billing import constants as c
from sm_billing import crypto
from sm_billing.contracts.provider import ProviderError
from sm_billing.errors import BillingError
from sm_billing.lifecycle import apply_lifecycle, tenant_service
from sm_billing.models import Plan, Subscription
from sm_billing.plans import PlanService
from sm_billing.providers.factory import install_provider
from sm_billing.schemas import ConnectionIn, ConnectionOut, PlanIn, SubscriptionRow

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


async def verify_prices(app: FastAPI, data: PlanIn) -> None:
    """Under Stripe, each price must exist, be active, and match currency + interval."""
    provider = _services(app).provider
    if provider is None or not provider.supports_checkout:
        return
    for interval, price_id in (
        (c.Interval.MONTH, data.stripe_price_month),
        (c.Interval.YEAR, data.stripe_price_year),
    ):
        if not price_id:
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
    await verify_prices(app, data)
    plans = PlanService(db)
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


async def one_row(db: AsyncSession, app: FastAPI, tenant_id: str) -> SubscriptionRow:
    rows = await subscription_rows(db, app, tenant_id=tenant_id, limit=1)
    if not rows:
        raise BillingError("tenant_not_found", 404)
    return rows[0]


async def assign(db: AsyncSession, app: FastAPI, tenant_id: str, data: AssignIn) -> None:
    """Manual provider only: set the tenant's plan and status directly."""
    if _services(app).provider.supports_checkout:
        raise BillingError("provider_managed", 409)
    if await db.get(Tenant, tenant_id) is None:
        raise BillingError("tenant_not_found", 404)
    plan = await PlanService(db).get(data.plan_id)
    if plan is None:
        raise BillingError("plan_not_found", 404)
    sub = (
        await db.execute(select(Subscription).where(Subscription.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if sub is None:
        sub = Subscription(tenant_id=tenant_id, plan_id=plan.id)
        db.add(sub)
    sub.plan_id = plan.id
    sub.status = data.status
    sub.interval = data.interval
    sub.provider_subscription_id = None
    sub.cancel_at_period_end = False
    await db.flush()
    await apply_lifecycle(db, app, sub)


async def resync(db: AsyncSession, app: FastAPI, tenant_id: str) -> None:
    provider = _services(app).provider
    if not provider.supports_checkout:
        raise BillingError("checkout_unavailable", 409)
    sub = (
        await db.execute(select(Subscription).where(Subscription.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if sub is None or sub.provider_subscription_id is None:
        raise BillingError("no_provider_subscription", 409)
    from sm_billing.sync import apply_snapshot

    snapshot = await provider.fetch_subscription(sub.provider_subscription_id)
    await apply_snapshot(db, app, snapshot, provider=provider.name)


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
    changes: dict[str, Any] = {"return_base_url": data.return_base_url.strip().rstrip("/")}
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
    # New secrets take effect now; switching provider itself still needs a restart.
    install_provider(_services(app))
    return connection_out(app)
