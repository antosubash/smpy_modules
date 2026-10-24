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

from sm_billing.constants import PROVIDER_CHECKOUT_BLOCKING_STATUSES


class ProviderError(Exception):
    """The provider refused or failed a call (network, auth, unknown object)."""


class ProviderNotFound(ProviderError):  # noqa: N818 - reads as the condition
    """The provider cannot see the object the call named (Stripe
    ``resource_missing``). Not proof it is gone: Stripe answers the same for an
    object of another account or test/live mode, so callers retry it."""


class InvalidWebhookSignature(ProviderError):  # noqa: N818 - reads as the condition
    """The webhook body does not carry a valid signature → HTTP 400."""


@dataclass(frozen=True)
class WebhookEvent:
    """What a verified delivery points at: ids to re-fetch, never state.

    There is deliberately no ``tenant_id``. The tenant is read from the
    re-fetched subscription or, for a completed Checkout, from the re-fetched
    session's ``client_reference_id``; never from the payload.
    """

    id: str
    type: str
    subscription_id: str | None = None
    customer_id: str | None = None
    checkout_id: str | None = None


@dataclass(frozen=True)
class CheckoutSnapshot:
    """The provider's current view of one Checkout session."""

    id: str
    subscription_id: str | None
    #: ``client_reference_id``: the tenant that opened the session.
    tenant_id: str | None
    customer_id: str | None
    #: ``open`` / ``complete`` / ``expired``; only an open one can still be paid.
    status: str | None = None


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
    #: Last, with a default, so a provider that has no period still builds one.
    current_period_start: datetime | None = None


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

    async def live_subscription_ids(
        self,
        customer_id: str,
        statuses: frozenset[str] = PROVIDER_CHECKOUT_BLOCKING_STATUSES,
    ) -> list[str]:
        """Every one of the customer's subscriptions whose status is in ``statuses``.

        The default answers checkout's "already subscribed"; deleting a tenant
        passes ``PROVIDER_CANCELABLE_STATUSES``. All of them, however many pages.
        """
        ...

    async def portal_url(self, customer_id: str, return_url: str) -> str: ...

    async def change_plan(self, subscription_id: str, price_id: str, quantity: int) -> None: ...

    async def set_quantity(self, subscription_id: str, quantity: int) -> None: ...

    async def cancel_at_period_end(self, subscription_id: str) -> None: ...

    async def cancel_now(self, subscription_id: str) -> None:
        """End the subscription immediately; no further invoices."""
        ...

    def parse_webhook(self, body: bytes, headers: Mapping[str, str]) -> WebhookEvent: ...

    async def fetch_subscription(self, subscription_id: str) -> SubscriptionSnapshot: ...

    async def fetch_checkout(self, session_id: str) -> CheckoutSnapshot: ...

    async def verify_price(self, price_id: str) -> PriceInfo: ...
