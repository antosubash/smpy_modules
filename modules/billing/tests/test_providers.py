from __future__ import annotations

import pytest
from fake_provider import FakeProvider
from sm_billing import crypto
from sm_billing.contracts.provider import BillingProvider, ProviderError
from sm_billing.providers.factory import build_provider
from sm_billing.providers.manual import ManualProvider
from sm_billing.settings import BillingSettings


def test_providers_satisfy_protocol():
    assert isinstance(ManualProvider(), BillingProvider)
    assert isinstance(FakeProvider(), BillingProvider)


async def test_manual_provider_has_no_checkout():
    manual = ManualProvider()
    assert manual.supports_checkout is False
    assert await manual.ensure_customer("t", "Acme", None) is None
    with pytest.raises(ProviderError):
        await manual.create_checkout(
            customer_id=None,
            price_id="p",
            quantity=1,
            trial_days=0,
            tenant_id="t",
            success_url="/",
            cancel_url="/",
        )
    with pytest.raises(ProviderError):
        await manual.portal_url("c", "/")
    with pytest.raises(ProviderError):
        manual.parse_webhook(b"{}", {})


def test_factory_defaults_to_manual():
    provider, error = build_provider(BillingSettings())
    assert isinstance(provider, ManualProvider)
    assert error == ""


def test_factory_falls_back_without_secrets(caplog):
    with caplog.at_level("ERROR"):
        provider, error = build_provider(BillingSettings(provider="stripe"))
    assert isinstance(provider, ManualProvider)
    assert "stripe_secret_key" in error
    assert any("stripe_secret_key" in r.message for r in caplog.records)


def test_fallback_message_names_both_missing_keys_in_the_plural():
    _, error = build_provider(BillingSettings(provider="stripe"))
    assert error == (
        "provider is 'stripe' but stripe_secret_key and stripe_webhook_secret are not set"
    )


@pytest.mark.parametrize(
    ("present", "missing"),
    [
        ({"stripe_secret_key": "sk_test"}, "stripe_webhook_secret"),
        ({"stripe_webhook_secret": "whsec"}, "stripe_secret_key"),
    ],
)
def test_fallback_message_names_one_missing_key_in_the_singular(present, missing):
    _, error = build_provider(BillingSettings(provider="stripe", **present))
    assert error == f"provider is 'stripe' but {missing} is not set"


def test_factory_falls_back_on_unreadable_secret():
    crypto.set_secret_provider(lambda: "one")
    stored = crypto.encrypt_value("sk_test")
    crypto.set_secret_provider(lambda: "two")
    try:
        provider, error = build_provider(
            BillingSettings(
                provider="stripe", stripe_secret_key=stored, stripe_webhook_secret="whsec"
            )
        )
    finally:
        crypto.set_secret_provider(lambda: "")
    assert isinstance(provider, ManualProvider)
    assert "cannot be decrypted" in error


async def test_startup_installs_manual_provider(app):
    services = app.state.sm_billing
    assert isinstance(services.provider, ManualProvider)
    assert services.provider_error == ""
