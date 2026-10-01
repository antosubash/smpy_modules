"""Billing settings — DB-backed via ``register_module_settings``.

No environment, ``.env`` or secrets-file sources (``DbBackedSettings``): an
``SM_BILLING_*`` variable is dead. Configure on the Settings screen, on
``/admin/billing/connection`` (which encrypts the Stripe secrets), or with
``scripts/set_setting.py``.

``provider`` is read once, in ``on_startup`` — the provider object is built
then — so changing it needs a restart.
"""

from __future__ import annotations

from pydantic import Field
from simple_module_core.settings_base import DbBackedSettings

from sm_billing import constants as c

_RESTART = {"requires_restart": True, "group": "Billing", "choices": list(c.PROVIDERS)}


class BillingSettings(DbBackedSettings):
    """Configuration for the billing module."""

    provider: str = Field(
        default=c.PROVIDER_MANUAL,
        description=(
            "Payment provider. 'manual': admins assign plans by hand, no payment. "
            "'stripe': Checkout, Customer Portal and webhooks (needs both Stripe secrets)."
        ),
        json_schema_extra=_RESTART,
    )
    stripe_secret_key: str = Field(
        default="",
        description="Stripe secret API key (sk_live_… / sk_test_…). Stored encrypted.",
    )
    stripe_webhook_secret: str = Field(
        default="",
        description="Signing secret of the Stripe webhook endpoint (whsec_…). Stored encrypted.",
    )
    return_base_url: str = Field(
        default="",
        description=(
            "Origin Stripe returns visitors to after Checkout and the portal, e.g. "
            "https://app.example.com. Empty: the request's own origin."
        ),
    )
