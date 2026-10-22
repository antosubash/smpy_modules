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

The hot-swap is per process: the framework reloads only the worker that took
the save. So a worker never acts on a provider the database no longer names,
:func:`ensure_current` re-reads the stored provider fields (one query) before
every billing request, membership seat push and reconcile tenant, and rebuilds
the same way when they differ — another worker's switch to ``manual`` stops
this one's Stripe writes at its next operation, not at its next restart. That
also picks up a value written with ``scripts/set_setting.py``. Stored secrets
are compared as their ciphertext and never logged.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from fastapi import Request

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
    services = getattr(app.state, c.PACKAGE, None)
    if services is None or services.provider is None:
        return  # not started yet: ``on_startup`` builds both from these settings
    async with services.reload_lock:
        await _rebuild(app, services, set(changed))


async def _rebuild(app: FastAPI, services: Any, changed: set[str]) -> None:
    """Rebuild under ``reload_lock`` (held by the caller)."""
    from sm_billing import startup
    from sm_billing.providers.factory import install_provider

    if changed & PROVIDER_FIELDS:
        previous = services.provider.name
        install_provider(services)
        if services.provider.name != previous:
            logger.info(
                "billing: provider switched from %s to %s", previous, services.provider.name
            )
    if changed & LOOP_FIELDS:
        await startup.sync_reconcile(app)


async def _stored(app: FastAPI) -> dict[str, Any]:
    """The ``LOOP_FIELDS`` values the database holds now (defaults where unset)."""
    from settings.constants import SYSTEM_SCOPE_ID
    from settings.contracts.schemas import SettingScope
    from settings.hydrate import build_settings
    from settings.models import Setting
    from sqlalchemy import select

    keys = {f"{c.PACKAGE}.{field}": field for field in LOOP_FIELDS}
    stmt = select(Setting.key, Setting.value, Setting.value_type).where(
        Setting.scope == SettingScope.SYSTEM.value,
        Setting.scope_id == SYSTEM_SCOPE_ID,
        Setting.key.in_(keys),
    )
    async with app.state.sm.db.session_factory() as session:
        rows = (await session.execute(stmt)).tuples().all()
    overrides = {keys[key]: (value, value_type) for key, value, value_type in rows}
    settings = build_settings(type(getattr(app.state, c.PACKAGE).settings), overrides)
    return {field: getattr(settings, field) for field in LOOP_FIELDS}


async def ensure_current(app: FastAPI) -> bool:
    """Catch up with a provider change another worker saved (#85).

    Returns ``True`` when something was rebuilt. Cheap when nothing changed:
    one indexed read of the settings table, no lock.
    """
    services = getattr(app.state, c.PACKAGE, None)
    if services is None or services.provider is None:
        return False
    stored = await _stored(app)
    async with services.reload_lock:
        current = services.settings
        changed = {f for f, value in stored.items() if getattr(current, f) != value}
        if not changed:
            return False  # in step, or a concurrent caller already caught up
        # Field names only: the values include the (encrypted) Stripe secrets.
        logger.info("billing: following settings saved elsewhere: %s", ", ".join(sorted(changed)))
        services.settings = current.model_copy(update={f: stored[f] for f in changed})
        await _rebuild(app, services, changed)
    return True


async def follow_live_settings(request: Request) -> None:
    """Router dependency: every billing endpoint acts on the stored provider."""
    await ensure_current(request.app)


def subscribe(bus: EventBus, app: FastAPI) -> None:
    """Rebuild on ``SettingsReloaded`` for billing's own package."""
    settings_reloaded = importlib.import_module("settings.contracts.events").SettingsReloaded

    async def _on_reload(event: Any) -> None:
        if event.package == c.PACKAGE:
            await apply_reload(app, event.changed)

    bus.subscribe(settings_reloaded, _on_reload)
