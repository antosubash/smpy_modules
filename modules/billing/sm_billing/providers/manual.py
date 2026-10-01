"""``manual`` — no payment provider at all.

Admins assign a plan and status on ``/admin/billing/subscriptions``, which
writes the subscription row directly. Everything that would reach a payment
provider refuses with ``ProviderError``; the API layer checks
``supports_checkout`` first so tenants see "not available", not an error.
"""

from __future__ import annotations

from collections.abc import Mapping

from sm_billing.constants import PROVIDER_MANUAL
from sm_billing.contracts.provider import (
    PriceInfo,
    ProviderError,
    SubscriptionSnapshot,
    WebhookEvent,
)

_NO = "The manual billing provider has no payment integration."


class ManualProvider:
    name = PROVIDER_MANUAL
    supports_checkout = False

    async def ensure_customer(self, tenant_id: str, name: str, email: str | None) -> str | None:
        return None

    async def checkout_url(self, **_: object) -> str:
        raise ProviderError(_NO)

    async def portal_url(self, customer_id: str, return_url: str) -> str:
        raise ProviderError(_NO)

    async def change_plan(self, subscription_id: str, price_id: str, quantity: int) -> None:
        raise ProviderError(_NO)

    async def set_quantity(self, subscription_id: str, quantity: int) -> None:
        raise ProviderError(_NO)

    async def cancel_at_period_end(self, subscription_id: str) -> None:
        raise ProviderError(_NO)

    def parse_webhook(self, body: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        raise ProviderError(_NO)

    async def fetch_subscription(self, subscription_id: str) -> SubscriptionSnapshot:
        raise ProviderError(_NO)

    async def verify_price(self, price_id: str) -> PriceInfo:
        raise ProviderError(_NO)
