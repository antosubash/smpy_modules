"""SQLModel tables for the Billing module.

None use ``MultiTenantMixin``: webhooks, reconcile and the admin list span
tenants by nature — the same reasoning as ``tenants``' own tables. Each row
that belongs to a tenant carries an explicit ``tenant_id`` and every query
filters on it. Nothing billing-specific is added to ``tenants_tenant``.

``tenant_id`` is a plain string, not a foreign key: each module owns its own
``MetaData``, so a cross-module FK cannot resolve (``tenants`` stores
``user_id`` the same way). Deleting a tenant therefore leaves its billing rows
behind — see the README's tenant-deletion note.
"""

from __future__ import annotations

from datetime import UTC, datetime

from simple_module_db.base import create_module_base
from simple_module_db.mixins import AuditMixin
from sqlalchemy import JSON, Column, DateTime, Text
from sqlmodel import Field

from sm_billing.constants import SubscriptionStatus

Base = create_module_base("billing")

_TENANT_ID_LEN = 32  # tenants: uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _tz_column(*, nullable: bool = True) -> Column:
    return Column(DateTime(timezone=True), nullable=nullable)


class Plan(Base, AuditMixin, table=True):  # ty: ignore[unsupported-base]
    """A sellable plan. Archived, never deleted, so subscriptions keep a valid plan."""

    __tablename__ = "billing_plan"

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(max_length=64, unique=True, index=True)
    name: str = Field(max_length=120)
    description: str = Field(default="", max_length=500)
    pricing_model: str = Field(max_length=20)
    currency: str = Field(default="eur", max_length=3)
    # Minor units, display only — Stripe charges what the price says.
    amount_month: int | None = Field(default=None)
    amount_year: int | None = Field(default=None)
    stripe_price_month: str | None = Field(default=None, max_length=255, unique=True)
    stripe_price_year: str | None = Field(default=None, max_length=255, unique=True)
    trial_days: int = Field(default=0)
    # {entitlement key: int}; an absent key is unlimited, 0 forbids.
    limits: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    features: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    is_default: bool = Field(default=False)
    is_public: bool = Field(default=True)
    sort_order: int = Field(default=0)
    archived_at: datetime | None = Field(default=None, sa_column=_tz_column())


class Customer(Base, AuditMixin, table=True):  # ty: ignore[unsupported-base]
    """The tenant's identity at the payment provider. Created at first checkout."""

    __tablename__ = "billing_customer"

    tenant_id: str = Field(primary_key=True, max_length=_TENANT_ID_LEN)
    provider: str = Field(max_length=20)
    provider_customer_id: str | None = Field(default=None, max_length=255, unique=True, index=True)
    email: str | None = Field(default=None, max_length=320)


class Subscription(Base, AuditMixin, table=True):  # ty: ignore[unsupported-base]
    """A tenant's one current subscription — the local mirror of the provider's."""

    __tablename__ = "billing_subscription"

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: str = Field(max_length=_TENANT_ID_LEN, unique=True, index=True)
    plan_id: int = Field(foreign_key="billing_plan.id")
    status: str = Field(default=SubscriptionStatus.ACTIVE, max_length=20, index=True)
    interval: str | None = Field(default=None, max_length=10)
    provider_subscription_id: str | None = Field(
        default=None, max_length=255, unique=True, index=True
    )
    quantity: int = Field(default=1)
    trial_end: datetime | None = Field(default=None, sa_column=_tz_column())
    current_period_end: datetime | None = Field(default=None, sa_column=_tz_column())
    cancel_at_period_end: bool = Field(default=False)
    # Billing only ever reactivates a tenant it suspended itself.
    suspended_by_billing: bool = Field(default=False)
    synced_at: datetime | None = Field(default=None, sa_column=_tz_column())


class WebhookEvent(Base, table=True):  # ty: ignore[unsupported-base]
    """One row per provider event id: idempotency and an audit trail."""

    __tablename__ = "billing_webhook_event"

    id: str = Field(primary_key=True, max_length=255)
    provider: str = Field(max_length=20)
    type: str = Field(max_length=100)
    received_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    processed_at: datetime | None = Field(default=None, sa_column=_tz_column())
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
