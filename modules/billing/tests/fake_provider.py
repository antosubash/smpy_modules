"""A scripted ``BillingProvider`` for tests: records calls, serves snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sm_billing.contracts.provider import (
    CheckoutSession,
    InvalidWebhookSignature,
    PriceInfo,
    ProviderError,
    SubscriptionSnapshot,
    WebhookEvent,
)

SIGNATURE_HEADER = "x-fake-signature"
GOOD_SIGNATURE = "ok"


@dataclass
class FakeProvider:
    name: str = "stripe"
    supports_checkout: bool = True
    snapshots: dict[str, SubscriptionSnapshot] = field(default_factory=dict)
    prices: dict[str, PriceInfo] = field(default_factory=dict)
    events: dict[str, WebhookEvent] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    fail: set[str] = field(default_factory=set)
    live: dict[str, list[str]] = field(default_factory=dict)
    _customers: int = 0
    _sessions: int = 0

    def _record(self, method: str, **kw: Any) -> None:
        self.calls.append((method, kw))
        if method in self.fail:
            raise ProviderError(f"{method} failed")

    def called(self, method: str) -> list[dict[str, Any]]:
        return [kw for name, kw in self.calls if name == method]

    async def ensure_customer(self, tenant_id: str, name: str, email: str | None) -> str | None:
        self._record("ensure_customer", tenant_id=tenant_id, name=name, email=email)
        self._customers += 1
        return f"cus_{self._customers}"

    async def create_checkout(self, **kw: Any) -> CheckoutSession:
        self._record("create_checkout", **kw)
        self._sessions += 1
        return CheckoutSession(f"cs_{self._sessions}", "https://checkout.test/session")

    async def expire_checkout(self, session_id: str) -> None:
        self._record("expire_checkout", session_id=session_id)

    async def live_subscription_ids(self, customer_id: str) -> list[str]:
        self._record("live_subscription_ids", customer_id=customer_id)
        return self.live.get(customer_id, [])

    async def portal_url(self, customer_id: str, return_url: str) -> str:
        self._record("portal_url", customer_id=customer_id, return_url=return_url)
        return "https://portal.test/session"

    async def change_plan(self, subscription_id: str, price_id: str, quantity: int) -> None:
        self._record(
            "change_plan", subscription_id=subscription_id, price_id=price_id, quantity=quantity
        )

    async def set_quantity(self, subscription_id: str, quantity: int) -> None:
        self._record("set_quantity", subscription_id=subscription_id, quantity=quantity)

    async def cancel_at_period_end(self, subscription_id: str) -> None:
        self._record("cancel_at_period_end", subscription_id=subscription_id)

    def parse_webhook(self, body: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        if headers.get(SIGNATURE_HEADER) != GOOD_SIGNATURE:
            raise InvalidWebhookSignature("bad signature")
        return self.events[body.decode()]

    async def fetch_subscription(self, subscription_id: str) -> SubscriptionSnapshot:
        self._record("fetch_subscription", subscription_id=subscription_id)
        return self.snapshots[subscription_id]

    async def verify_price(self, price_id: str) -> PriceInfo:
        self._record("verify_price", price_id=price_id)
        if price_id not in self.prices:
            raise ProviderError(f"No such price: {price_id}")
        return self.prices[price_id]
