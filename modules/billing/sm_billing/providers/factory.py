"""Build the configured provider from the hydrated settings."""

from __future__ import annotations

from sm_billing.services import BillingServices


def install_provider(services: BillingServices) -> None:
    """Set ``services.provider`` (and ``provider_error`` when it falls back)."""
