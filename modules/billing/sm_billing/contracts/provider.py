"""The payment-provider seam.

Billing speaks to Stripe (or nothing, for ``manual``) only through this
protocol, in plain dataclasses — no provider SDK object crosses it, so the
sync, webhook and checkout code is testable with a scripted fake and a second
provider would be a new class, not a refactor.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


class ProviderError(Exception):
    """The provider refused or failed a call (network, auth, unknown object)."""


class InvalidWebhookSignature(ProviderError):  # noqa: N818 - reads as the condition
    """The webhook body does not carry a valid signature → HTTP 400."""


@dataclass(frozen=True)
class WebhookEvent:
    id: str
    type: str
    subscription_id: str | None = None
    tenant_id: str | None = None
    customer_id: str | None = None


@dataclass(frozen=True)
class SubscriptionSnapshot:
    """The provider's current view of one subscription, already normalised.

    ``status`` is the provider's raw status string; ``sync`` maps it.
    """

    id: str
    customer_id: str | None
    tenant_id: str | None
    status: str
    price_id: str | None
    quantity: int
    trial_end: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool


@dataclass(frozen=True)
class CheckoutSession:
    id: str
    url: str


@dataclass(frozen=True)
class PriceInfo:
    id: str
    currency: str
    interval: str | None  # "month" / "year"; None for one-off prices
    active: bool


@runtime_checkable
class BillingProvider(Protocol):
    name: str
    supports_checkout: bool

    async def ensure_customer(self, tenant_id: str, name: str, email: str | None) -> str | None:
        """Create the customer; returns its id (``None`` for providers without one)."""
        ...

    async def create_checkout(
        self,
        *,
        customer_id: str | None,
        price_id: str,
        quantity: int,
        trial_days: int,
        tenant_id: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutSession: ...

    async def expire_checkout(self, session_id: str) -> None:
        """Close an open Checkout session so it can no longer be paid."""
        ...

    async def live_subscription_ids(self, customer_id: str) -> list[str]:
        """The customer's subscriptions that still bill or grant access."""
        ...

    async def portal_url(self, customer_id: str, return_url: str) -> str: ...

    async def change_plan(self, subscription_id: str, price_id: str, quantity: int) -> None: ...

    async def set_quantity(self, subscription_id: str, quantity: int) -> None: ...

    async def cancel_at_period_end(self, subscription_id: str) -> None: ...

    def parse_webhook(self, body: bytes, headers: Mapping[str, str]) -> WebhookEvent: ...

    async def fetch_subscription(self, subscription_id: str) -> SubscriptionSnapshot: ...

    async def verify_price(self, price_id: str) -> PriceInfo: ...
