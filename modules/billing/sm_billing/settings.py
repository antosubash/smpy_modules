"""Billing settings — DB-backed via ``register_module_settings``.

No environment, ``.env`` or secrets-file sources (``DbBackedSettings``): an
``SM_BILLING_*`` variable is dead. Configure on the Settings screen, on
``/admin/billing/connection`` (which encrypts the Stripe secrets), or with
``scripts/set_setting.py``.

``provider`` and ``reconcile_interval_minutes`` are first read in
``on_startup``, which builds the provider object and the reconcile loop; a save
that changes either (or a Stripe secret) rebuilds them through
``sm_billing.live``, so neither needs a restart.
"""

from __future__ import annotations

from pydantic import Field
from simple_module_core.settings_base import DbBackedSettings

from sm_billing import constants as c

_GROUP = {"group": "Billing"}
_PROVIDER = {**_GROUP, "choices": list(c.PROVIDERS)}


class BillingSettings(DbBackedSettings):
    """Configuration for the billing module."""

    provider: str = Field(
        default=c.PROVIDER_MANUAL,
        description=(
            "Payment provider. 'manual': admins assign plans by hand, no payment. "
            "'stripe': Checkout, Customer Portal and webhooks (needs both Stripe secrets)."
        ),
        json_schema_extra=_PROVIDER,
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
    reconcile_interval_minutes: int = Field(
        default=0,
        ge=0,
        description=(
            "Re-read every Stripe subscription not synced within this many minutes, "
            "on a loop inside the app — the safety net for missed webhooks and failed "
            "seat pushes. 0 turns the loop off (run “smpy billing reconcile” from cron "
            "instead). 60 is a sensible value."
        ),
        json_schema_extra=_GROUP,
    )
