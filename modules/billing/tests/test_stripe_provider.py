"""StripeProvider: real signature verification, mapping, and the calls it makes.

No network: payloads are signed locally with the scheme Stripe documents
(``t=<ts>,v1=HMAC-SHA256(secret, "<ts>.<body>")``) and verified by the real
``stripe`` SDK; API calls go to a recording stand-in for ``client.v1``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
import stripe
from sm_billing import crypto
from sm_billing.contracts.provider import InvalidWebhookSignature, ProviderError
from sm_billing.providers.factory import build_provider
from sm_billing.providers.stripe import StripeProvider
from sm_billing.settings import BillingSettings

SECRET = "whsec_test"
PERIOD_END = 1793491200  # 2026-11-01T00:00:00Z

SUBSCRIPTION = {
    "id": "sub_1",
    "object": "subscription",
    "customer": "cus_1",
    "status": "trialing",
    "cancel_at_period_end": False,
    "trial_end": 1792281600,
    "metadata": {"tenant_id": "t1"},
    "items": {
        "object": "list",
        "data": [
            {
                "id": "si_1",
                "object": "subscription_item",
                "quantity": 4,
                "current_period_end": PERIOD_END,
                "price": {"id": "price_team_m", "object": "price"},
            }
        ],
    },
}


def _signed(payload: dict, secret: str = SECRET) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode()
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{body.decode()}".encode(), hashlib.sha256).hexdigest()
    return body, {"stripe-signature": f"t={ts},v1={sig}"}


def _event(etype: str, obj: dict) -> dict:
    return {"id": "evt_1", "object": "event", "type": etype, "data": {"object": obj}}


class _Recorder:
    """Stands in for one ``client.v1.<resource>`` service."""

    def __init__(self, calls: list, name: str, result: dict) -> None:
        self._calls, self._name, self._result = calls, name, result

    def __getattr__(self, method: str):
        async def call(*args: Any, **kwargs: Any):
            self._calls.append((f"{self._name}.{method}", args, kwargs.get("params")))
            return stripe.StripeObject.construct_from(self._result, "sk_test")

        return call


@pytest.fixture
def provider():
    p = StripeProvider(secret_key="sk_test_x", webhook_secret=SECRET)
    p.calls = []
    p._v1 = SimpleNamespace(
        subscriptions=_Recorder(p.calls, "subscriptions", SUBSCRIPTION),
        customers=_Recorder(p.calls, "customers", {"id": "cus_new", "object": "customer"}),
        checkout=SimpleNamespace(
            sessions=_Recorder(p.calls, "checkout", {"id": "cs_1", "url": "https://co/1"})
        ),
        billing_portal=SimpleNamespace(
            sessions=_Recorder(p.calls, "portal", {"id": "bps_1", "url": "https://bp/1"})
        ),
        prices=_Recorder(
            p.calls,
            "prices",
            {
                "id": "price_team_m",
                "currency": "eur",
                "active": True,
                "recurring": {"interval": "month"},
            },
        ),
    )
    return p


def test_parse_subscription_event(provider):
    body, headers = _signed(_event("customer.subscription.updated", SUBSCRIPTION))
    event = provider.parse_webhook(body, headers)
    assert (event.id, event.type, event.subscription_id) == (
        "evt_1",
        "customer.subscription.updated",
        "sub_1",
    )
    assert (event.tenant_id, event.customer_id) == ("t1", "cus_1")


def test_parse_checkout_completed(provider):
    session = {
        "id": "cs_1",
        "object": "checkout.session",
        "subscription": "sub_9",
        "client_reference_id": "t9",
        "customer": "cus_9",
    }
    body, headers = _signed(_event("checkout.session.completed", session))
    event = provider.parse_webhook(body, headers)
    assert (event.subscription_id, event.tenant_id, event.customer_id) == ("sub_9", "t9", "cus_9")


def test_parse_other_event_has_no_subscription(provider):
    body, headers = _signed(_event("invoice.created", {"id": "in_1", "object": "invoice"}))
    assert provider.parse_webhook(body, headers).subscription_id is None


def test_tampered_body_rejected(provider):
    body, headers = _signed(_event("customer.subscription.updated", SUBSCRIPTION))
    with pytest.raises(InvalidWebhookSignature):
        provider.parse_webhook(body.replace(b"trialing", b"active__"), headers)


def test_wrong_secret_rejected(provider):
    body, headers = _signed(_event("x", {}), secret="whsec_other")
    with pytest.raises(InvalidWebhookSignature):
        provider.parse_webhook(body, headers)


def test_missing_header_rejected(provider):
    with pytest.raises(InvalidWebhookSignature):
        provider.parse_webhook(b"{}", {})


async def test_fetch_subscription_maps_snapshot(provider):
    snap = await provider.fetch_subscription("sub_1")
    assert (snap.id, snap.customer_id, snap.tenant_id) == ("sub_1", "cus_1", "t1")
    assert (snap.status, snap.price_id, snap.quantity) == ("trialing", "price_team_m", 4)
    assert snap.current_period_end == datetime(2026, 11, 1, tzinfo=UTC)
    assert snap.trial_end == datetime.fromtimestamp(1792281600, UTC)


async def test_checkout_params(provider):
    url = await provider.checkout_url(
        customer_id="cus_1",
        price_id="price_team_m",
        quantity=3,
        trial_days=14,
        tenant_id="t1",
        success_url="https://a/ok",
        cancel_url="https://a/no",
    )
    assert url == "https://co/1"
    name, _, params = provider.calls[-1]
    assert name == "checkout.create_async"
    assert params["mode"] == "subscription"
    assert params["client_reference_id"] == "t1"
    assert params["line_items"] == [{"price": "price_team_m", "quantity": 3}]
    assert params["subscription_data"] == {"metadata": {"tenant_id": "t1"}, "trial_period_days": 14}


async def test_checkout_without_trial_omits_trial(provider):
    await provider.checkout_url(
        customer_id="cus_1",
        price_id="p",
        quantity=1,
        trial_days=0,
        tenant_id="t1",
        success_url="s",
        cancel_url="c",
    )
    assert "trial_period_days" not in provider.calls[-1][2]["subscription_data"]


async def test_change_plan_updates_the_item_with_proration(provider):
    await provider.change_plan("sub_1", "price_team_y", 5)
    name, args, params = provider.calls[-1]
    assert (name, args) == ("subscriptions.update_async", ("sub_1",))
    assert params["items"] == [{"id": "si_1", "price": "price_team_y", "quantity": 5}]
    assert params["proration_behavior"] == "create_prorations"


async def test_set_quantity_and_cancel(provider):
    await provider.set_quantity("sub_1", 7)
    assert provider.calls[-1][2]["items"] == [{"id": "si_1", "quantity": 7}]
    await provider.cancel_at_period_end("sub_1")
    assert provider.calls[-1][2] == {"cancel_at_period_end": True}


async def test_customer_and_portal(provider):
    assert await provider.ensure_customer("t1", "Acme", "o@x.io") == "cus_new"
    assert provider.calls[-1][2]["metadata"] == {"tenant_id": "t1"}
    assert await provider.portal_url("cus_1", "https://a/billing") == "https://bp/1"


async def test_verify_price(provider):
    info = await provider.verify_price("price_team_m")
    assert (info.currency, info.interval, info.active) == ("eur", "month", True)


async def test_stripe_errors_become_provider_errors(provider):
    async def boom(*_a, **_k):
        raise stripe.InvalidRequestError("No such price", param="price")

    provider._v1.prices = SimpleNamespace(retrieve_async=boom)
    with pytest.raises(ProviderError, match="No such price"):
        await provider.verify_price("nope")


def test_factory_builds_stripe_with_encrypted_secrets():
    crypto.set_secret_provider(lambda: "app-secret")
    try:
        settings = BillingSettings(
            provider="stripe",
            stripe_secret_key=crypto.encrypt_value("sk_test_1"),
            stripe_webhook_secret=crypto.encrypt_value(SECRET),
        )
        provider, error = build_provider(settings)
    finally:
        crypto.set_secret_provider(lambda: "")
    assert isinstance(provider, StripeProvider)
    assert error == ""
