"""``StripeProvider`` — the ``BillingProvider`` over the official ``stripe`` SDK.

Every response is turned into a plain dict (``to_dict``) at the boundary and
mapped into the protocol's dataclasses, so nothing Stripe-shaped leaks past
this file. SDK errors become ``ProviderError``; a bad webhook signature or
body becomes ``InvalidWebhookSignature``.

Period end is read from the subscription item when the subscription itself
lacks it — Stripe API versions from 2025 onward moved it there.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import stripe

from sm_billing.constants import PROVIDER_STRIPE
from sm_billing.contracts.provider import (
    CheckoutSession,
    InvalidWebhookSignature,
    PriceInfo,
    ProviderError,
    SubscriptionSnapshot,
    WebhookEvent,
)

_SUBSCRIPTION_EVENTS = ("customer.subscription.",)
_CHECKOUT_COMPLETED = "checkout.session.completed"
# Still billing or granting access — a second checkout would double-charge.
_LIVE_STATUSES = frozenset({"active", "trialing", "past_due", "unpaid"})


def _ts(value: Any) -> datetime | None:
    return datetime.fromtimestamp(int(value), UTC) if value else None


def _id(value: Any) -> str | None:
    """A Stripe reference: an id string, or an expanded object carrying ``id``."""
    if isinstance(value, dict):
        return value.get("id")
    return value or None


def _first_item(sub: dict) -> dict:
    items = (sub.get("items") or {}).get("data") or []
    if not items:
        raise ProviderError(f"subscription {sub.get('id')} has no items")
    return items[0]


def snapshot_from(sub: dict) -> SubscriptionSnapshot:
    item = _first_item(sub)
    return SubscriptionSnapshot(
        id=sub["id"],
        customer_id=_id(sub.get("customer")),
        tenant_id=(sub.get("metadata") or {}).get("tenant_id"),
        status=sub.get("status", ""),
        price_id=_id(item.get("price")),
        quantity=int(item.get("quantity") or 1),
        trial_end=_ts(sub.get("trial_end")),
        current_period_end=_ts(sub.get("current_period_end") or item.get("current_period_end")),
        cancel_at_period_end=bool(sub.get("cancel_at_period_end")),
    )


class StripeProvider:
    name = PROVIDER_STRIPE
    supports_checkout = True

    def __init__(self, *, secret_key: str, webhook_secret: str) -> None:
        self._client = stripe.StripeClient(secret_key, max_network_retries=2)
        self._v1 = self._client.v1
        self._webhook_secret = webhook_secret

    async def _call(
        self, fn, *args: Any, params: dict | None = None, options: dict | None = None
    ) -> dict:
        kwargs = {k: v for k, v in (("params", params), ("options", options)) if v is not None}
        try:
            result = await fn(*args, **kwargs)
        except stripe.StripeError as exc:
            raise ProviderError(exc.user_message or str(exc)) from exc
        return result.to_dict()

    async def ensure_customer(self, tenant_id: str, name: str, email: str | None) -> str | None:
        params: dict[str, Any] = {"name": name, "metadata": {"tenant_id": tenant_id}}
        if email:
            params["email"] = email
        # Keyed on the tenant: the customer row is rolled back with a failed
        # checkout, and the retry must get the same Stripe customer back
        # (Stripe keeps idempotency keys for 24h).
        options = {"idempotency_key": f"sm-billing-customer-{tenant_id}"}
        customer = await self._call(self._v1.customers.create_async, params=params, options=options)
        return customer["id"]

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
    ) -> CheckoutSession:
        subscription_data: dict[str, Any] = {"metadata": {"tenant_id": tenant_id}}
        if trial_days > 0:
            subscription_data["trial_period_days"] = trial_days
        params: dict[str, Any] = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": quantity}],
            "client_reference_id": tenant_id,
            "subscription_data": subscription_data,
            "success_url": success_url,
            "cancel_url": cancel_url,
        }
        if customer_id:
            params["customer"] = customer_id
        session = await self._call(self._v1.checkout.sessions.create_async, params=params)
        return CheckoutSession(id=session["id"], url=session["url"])

    async def expire_checkout(self, session_id: str) -> None:
        await self._call(self._v1.checkout.sessions.expire_async, session_id)

    async def live_subscription_ids(self, customer_id: str) -> list[str]:
        params = {"customer": customer_id, "status": "all", "limit": 100}
        listing = await self._call(self._v1.subscriptions.list_async, params=params)
        return [s["id"] for s in listing.get("data", []) if s.get("status") in _LIVE_STATUSES]

    async def portal_url(self, customer_id: str, return_url: str) -> str:
        params = {"customer": customer_id, "return_url": return_url}
        session = await self._call(self._v1.billing_portal.sessions.create_async, params=params)
        return session["url"]

    async def _item_id(self, subscription_id: str) -> str:
        sub = await self._call(self._v1.subscriptions.retrieve_async, subscription_id)
        return _first_item(sub)["id"]

    async def change_plan(self, subscription_id: str, price_id: str, quantity: int) -> None:
        item = await self._item_id(subscription_id)
        params = {
            "items": [{"id": item, "price": price_id, "quantity": quantity}],
            "proration_behavior": "create_prorations",
            "cancel_at_period_end": False,
        }
        await self._call(self._v1.subscriptions.update_async, subscription_id, params=params)

    async def set_quantity(self, subscription_id: str, quantity: int) -> None:
        item = await self._item_id(subscription_id)
        params = {
            "items": [{"id": item, "quantity": quantity}],
            "proration_behavior": "create_prorations",
        }
        await self._call(self._v1.subscriptions.update_async, subscription_id, params=params)

    async def cancel_at_period_end(self, subscription_id: str) -> None:
        params = {"cancel_at_period_end": True}
        await self._call(self._v1.subscriptions.update_async, subscription_id, params=params)

    def parse_webhook(self, body: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        signature = headers.get("stripe-signature")
        if not signature:
            raise InvalidWebhookSignature("missing Stripe-Signature header")
        try:
            event = self._client.construct_event(body, signature, self._webhook_secret).to_dict()
        except (stripe.SignatureVerificationError, ValueError) as exc:
            raise InvalidWebhookSignature(str(exc)) from exc
        obj = (event.get("data") or {}).get("object") or {}
        etype = event.get("type", "")
        if etype == _CHECKOUT_COMPLETED:
            return WebhookEvent(
                id=event["id"],
                type=etype,
                subscription_id=_id(obj.get("subscription")),
                tenant_id=obj.get("client_reference_id"),
                customer_id=_id(obj.get("customer")),
            )
        if etype.startswith(_SUBSCRIPTION_EVENTS):
            return WebhookEvent(
                id=event["id"],
                type=etype,
                subscription_id=obj.get("id"),
                tenant_id=(obj.get("metadata") or {}).get("tenant_id"),
                customer_id=_id(obj.get("customer")),
            )
        return WebhookEvent(id=event["id"], type=etype)

    async def fetch_subscription(self, subscription_id: str) -> SubscriptionSnapshot:
        sub = await self._call(self._v1.subscriptions.retrieve_async, subscription_id)
        return snapshot_from(sub)

    async def verify_price(self, price_id: str) -> PriceInfo:
        price = await self._call(self._v1.prices.retrieve_async, price_id)
        recurring = price.get("recurring") or {}
        return PriceInfo(
            id=price["id"],
            currency=str(price.get("currency", "")).lower(),
            interval=recurring.get("interval"),
            active=bool(price.get("active")),
        )
