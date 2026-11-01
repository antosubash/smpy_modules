"""StripeProvider: real signature verification, mapping, and the calls it makes.

No network: payloads are signed locally with the scheme Stripe documents
(``t=<ts>,v1=HMAC-SHA256(secret, "<ts>.<body>")``) and verified by the real
``stripe`` SDK; API calls go to a recording stand-in for ``client.v1``.
Checkout tests are in ``test_stripe_checkout.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import stripe
from sm_billing import crypto
from sm_billing.contracts.provider import InvalidWebhookSignature, ProviderError
from sm_billing.providers.factory import build_provider
from sm_billing.providers.stripe import StripeProvider
from sm_billing.settings import BillingSettings
from stripe_helpers import SECRET, SUBSCRIPTION, _event, _signed


def test_parse_subscription_event(provider):
    body, headers = _signed(_event("customer.subscription.updated", SUBSCRIPTION))
    event = provider.parse_webhook(body, headers)
    assert (event.id, event.type, event.subscription_id) == (
        "evt_1",
        "customer.subscription.updated",
        "sub_1",
    )
    assert event.customer_id == "cus_1"
    # The payload's metadata.tenant_id is not carried: the handler re-fetches.
    assert not hasattr(event, "tenant_id")


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
    assert (event.subscription_id, event.checkout_id, event.customer_id) == (
        "sub_9",
        "cs_1",
        "cus_9",
    )
    assert not hasattr(event, "tenant_id")


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


async def test_cancel_now_deletes_the_subscription_immediately(provider):
    await provider.cancel_now("sub_1")
    assert provider.calls[-1] == ("subscriptions.cancel_async", ("sub_1",), None)


async def test_customer_and_portal(provider):
    assert await provider.ensure_customer("t1", "Acme", "o@x.io") == "cus_new"
    assert provider.calls[-1][2]["metadata"] == {"tenant_id": "t1"}
    # A retry after a failed checkout must reuse the customer, not add one.
    first = provider._v1.customers.options["idempotency_key"]
    assert first.startswith("sm-billing-customer-t1-")
    # Different params must not reuse the key (Stripe rejects that for 24h).
    await provider.ensure_customer("t1", "Acme", "other@x.io")
    assert provider._v1.customers.options["idempotency_key"] != first
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
