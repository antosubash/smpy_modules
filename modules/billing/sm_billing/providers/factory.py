"""Build the configured provider from the hydrated settings.

A misconfigured ``stripe`` (missing or undecryptable secrets) falls back to
``manual`` with the reason kept on ``BillingServices.provider_error``: the app
still boots, paid checkout stays off, and the admin screens say why.
"""

from __future__ import annotations

import logging

from sm_billing import constants as c
from sm_billing import crypto
from sm_billing.contracts.provider import BillingProvider
from sm_billing.providers.manual import ManualProvider
from sm_billing.services import BillingServices
from sm_billing.settings import BillingSettings

logger = logging.getLogger(__name__)


def _missing_message(missing: list[str]) -> str:
    """English, like every other reason here: it goes to the log as well as the screen."""
    if len(missing) == 1:
        return f"provider is 'stripe' but {missing[0]} is not set"
    return f"provider is 'stripe' but {' and '.join(missing)} are not set"


def build_provider(settings: BillingSettings) -> tuple[BillingProvider, str]:
    if settings.provider != c.PROVIDER_STRIPE:
        return ManualProvider(), ""
    try:
        secret = crypto.decrypt_value(settings.stripe_secret_key, "stripe_secret_key")
        webhook = crypto.decrypt_value(settings.stripe_webhook_secret, "stripe_webhook_secret")
    except crypto.BillingKeyUnreadableError as exc:
        # The locale templates append their own full stop after ``{error}``.
        error = str(exc).rstrip(". ")
    else:
        missing = [
            name
            for name, value in (("stripe_secret_key", secret), ("stripe_webhook_secret", webhook))
            if not value
        ]
        if not missing:
            from sm_billing.providers.stripe import StripeProvider

            return StripeProvider(secret_key=secret, webhook_secret=webhook), ""
        error = _missing_message(missing)
    logger.error("billing: %s — falling back to the manual provider", error)
    return ManualProvider(), error


def install_provider(services: BillingServices) -> None:
    """Set ``services.provider`` (and ``provider_error`` when it falls back)."""
    services.provider, services.provider_error = build_provider(services.settings)
