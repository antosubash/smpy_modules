"""Module-scoped state on ``app.state.sm_billing``.

Not frozen: the host's hydrate step assigns the DB-resolved settings onto
this object at lifespan start, and the Settings screen assigns again on every
save. ``provider`` is built in ``on_startup`` from the hydrated settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sm_billing import constants as c
from sm_billing.errors import BillingError
from sm_billing.settings import BillingSettings

if TYPE_CHECKING:
    from fastapi import FastAPI

    from sm_billing.contracts.provider import BillingProvider


@dataclass
class BillingServices:
    settings: BillingSettings
    provider: BillingProvider | None = None
    #: Why the configured provider could not be used (shown on the admin screens).
    provider_error: str = ""


def current_provider(app: FastAPI) -> BillingProvider:
    """The running provider, for code that cannot proceed without one."""
    provider = getattr(app.state, c.PACKAGE).provider
    if provider is None:
        raise BillingError("provider_unavailable", 503)
    return provider
