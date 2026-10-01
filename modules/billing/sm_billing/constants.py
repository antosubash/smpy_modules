"""Billing module constants.

Kept out of the call sites so no module name, route, permission or page
appears as a bare literal — see scripts/check_hardcoded_strings.py.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

PACKAGE: Final = "sm_billing"
MODULE_NAME: Final = "Billing"

ROUTE_PREFIX_API: Final = "/api/billing"
VIEW_PREFIX: Final = "/billing"
ADMIN_VIEW_PREFIX: Final = "/admin/billing"
WEBHOOK_PATH: Final = "/billing/webhooks/stripe"

# Modules this one depends on (value = that module's ModuleMeta.name).
_MODULE_TENANTS: Final = "Tenants"
_MODULE_SETTINGS: Final = "Settings"

# ── Permissions ──────────────────────────────────────────────────────
PERM_VIEW: Final = "billing.view"
PERM_MANAGE: Final = "billing.manage"
PERM_PLATFORM_VIEW: Final = "billing.platform.view"
PERM_PLATFORM_MANAGE: Final = "billing.platform.manage"

# Tenant roles as the tenants resolver appends them to the principal
# (``tenants.constants.TENANT_ROLE_PREFIX`` + role) for the active tenant only.
ROLE_TENANT_OWNER: Final = "tenant:owner"
ROLE_TENANT_ADMIN: Final = "tenant:admin"
TENANT_ROLE_OWNER: Final = "owner"

# ── Inertia pages (pinned to files under pages/ by a test) ───────────
_PAGE_BILLING: Final = f"{MODULE_NAME}/Billing"
_PAGE_PLANS: Final = f"{MODULE_NAME}/Plans"
_PAGE_SUBSCRIPTIONS: Final = f"{MODULE_NAME}/Subscriptions"
_PAGE_CONNECTION: Final = f"{MODULE_NAME}/Connection"

# ── Menu ─────────────────────────────────────────────────────────────
MENU_LABEL: Final = "Billing"
MENU_URL: Final = f"{VIEW_PREFIX}/"
MENU_ICON: Final = "credit-card"
MENU_ORDER: Final = 95  # just after Organisations (90)
ADMIN_MENU_LABEL: Final = "Billing"
ADMIN_MENU_URL: Final = f"{ADMIN_VIEW_PREFIX}/subscriptions"
ADMIN_MENU_GROUP: Final = "Access"
ADMIN_MENU_GROUP_KEY: Final = "ui.nav_groups.access"

# ── Providers (stored values) ────────────────────────────────────────
PROVIDER_MANUAL: Final = "manual"
PROVIDER_STRIPE: Final = "stripe"
PROVIDERS: Final = (PROVIDER_MANUAL, PROVIDER_STRIPE)

# ── Entitlement keys this module knows about (suggestions in the editor)
ENTITLEMENT_SEATS: Final = "tenants.seats"
KNOWN_LIMIT_KEYS: Final = (ENTITLEMENT_SEATS,)

DEFAULT_PLAN_KEY: Final = "free"
DEFAULT_PLAN_NAME: Final = "Free"

SECRET_FIELDS: Final = frozenset({"stripe_secret_key", "stripe_webhook_secret"})


class PricingModel(StrEnum):
    FREE = "free"
    FLAT = "flat"
    PER_SEAT = "per_seat"


class Interval(StrEnum):
    MONTH = "month"
    YEAR = "year"


class SubscriptionStatus(StrEnum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    UNPAID = "unpaid"
    CANCELED = "canceled"
    INCOMPLETE = "incomplete"


#: Statuses whose plan is in force; everything else resolves to the default plan.
ENTITLED_STATUSES: Final = frozenset(
    {SubscriptionStatus.TRIALING, SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE}
)

#: Stripe statuses we fold onto ours (``incomplete_expired`` never paid).
STRIPE_STATUS_MAP: Final = {
    "trialing": SubscriptionStatus.TRIALING,
    "active": SubscriptionStatus.ACTIVE,
    "past_due": SubscriptionStatus.PAST_DUE,
    "unpaid": SubscriptionStatus.UNPAID,
    "canceled": SubscriptionStatus.CANCELED,
    "incomplete": SubscriptionStatus.INCOMPLETE,
    "incomplete_expired": SubscriptionStatus.CANCELED,
    "paused": SubscriptionStatus.UNPAID,
}

#: Webhook event types that trigger a subscription re-fetch.
HANDLED_EVENTS: Final = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }
)
