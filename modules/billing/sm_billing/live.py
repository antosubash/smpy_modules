"""Follow the live settings: switching provider needs no restart (#85).

The framework hot-swaps ``app.state.sm_billing.settings`` on every save (the
Settings screen, ``/admin/billing/connection``) and then publishes
``SettingsReloaded``. The provider object and the reconcile loop are built
*from* those settings, so on a billing reload this rebuilds whichever of them
the changed fields feed:

- ``provider`` or either Stripe secret → a new provider object, through the
  same ``install_provider`` startup uses (a ``stripe`` with a missing secret
  still falls back to ``manual`` with ``provider_error`` set).
- any of those, or ``reconcile_interval_minutes`` → the loop is started,
  stopped or restarted to match (``startup.sync_reconcile``).

Everything runs on the event loop; the provider is swapped by one attribute
assignment, so a request already holding the old object finishes with it and
the next one reads the new one. The lock keeps two concurrent saves from both
starting a loop.

The hot-swap is per process: another worker of the same app keeps its
settings, provider and loop until it restarts, and a value written with
``scripts/set_setting.py`` is read at the next boot. Both are the framework's
module-settings behaviour, not billing's.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from sm_billing import constants as c

if TYPE_CHECKING:
    from fastapi import FastAPI
    from simple_module_core.events import EventBus

logger = logging.getLogger(__name__)

#: Fields ``build_provider`` reads.
PROVIDER_FIELDS = frozenset({"provider", *c.SECRET_FIELDS})
#: Fields whose change can start, stop or re-time the reconcile loop.
LOOP_FIELDS = PROVIDER_FIELDS | {"reconcile_interval_minutes"}


async def apply_reload(app: FastAPI, changed: Iterable[str]) -> None:
    """Rebuild what the ``changed`` billing fields feed."""
    from sm_billing import startup
    from sm_billing.providers.factory import install_provider

    services = getattr(app.state, c.PACKAGE, None)
    if services is None or services.provider is None:
        return  # not started yet: ``on_startup`` builds both from these settings
    changed = set(changed)
    async with services.reload_lock:
        if changed & PROVIDER_FIELDS:
            previous = services.provider.name
            install_provider(services)
            if services.provider.name != previous:
                logger.info(
                    "billing: provider switched from %s to %s", previous, services.provider.name
                )
        if changed & LOOP_FIELDS:
            await startup.sync_reconcile(app)


def subscribe(bus: EventBus, app: FastAPI) -> None:
    """Rebuild on ``SettingsReloaded`` for billing's own package."""
    settings_reloaded = importlib.import_module("settings.contracts.events").SettingsReloaded

    async def _on_reload(event: Any) -> None:
        if event.package == c.PACKAGE:
            await apply_reload(app, event.changed)

    bus.subscribe(settings_reloaded, _on_reload)
