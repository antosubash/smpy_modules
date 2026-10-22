"""Module-scoped state on ``app.state.sm_billing``.

Not frozen: the host's hydrate step assigns the DB-resolved settings onto
this object at lifespan start, and the Settings screen assigns again on every
save. ``provider`` is built in ``on_startup`` from the hydrated settings and
rebuilt by :mod:`sm_billing.live` whenever a save changes what it depends on.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sm_billing import constants as c
from sm_billing.errors import BillingError
from sm_billing.settings import BillingSettings

if TYPE_CHECKING:
    from fastapi import FastAPI

    from sm_billing.contracts.provider import BillingProvider
    from sm_billing.scheduler import ReconcileScheduler


@dataclass
class BillingServices:
    settings: BillingSettings
    provider: BillingProvider | None = None
    #: Why the configured provider could not be used (shown on the admin screens).
    provider_error: str = ""
    #: The periodic reconcile loop, when ``reconcile_interval_minutes`` started one.
    scheduler: ReconcileScheduler | None = None
    #: Serialises live reloads: two saves at once must not both start a loop.
    reload_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    #: The provider/loop fields as ``sm_billing.live`` last read them from the
    #: database (``None`` until its first read). Only a move of the *database*
    #: is followed, so a save not yet committed is not reverted.
    stored_seen: dict[str, Any] | None = None
    #: Ticket counters ordering concurrent database reads in ``live.ensure_current``.
    read_seq: int = 0
    applied_seq: int = 0


def current_provider(app: FastAPI) -> BillingProvider:
    """The running provider, for code that cannot proceed without one."""
    provider = getattr(app.state, c.PACKAGE).provider
    if provider is None:
        raise BillingError("provider_unavailable", 503)
    return provider
