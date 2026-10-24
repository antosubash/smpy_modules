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
also picks up a value written with ``scripts/set_setting.py``. The
``usage_*`` fields ride along (the hold sweeper re-reads them before every
tick), so a sweep interval or retention saved on one worker reaches the rest. Stored secrets
are compared as their ciphertext and never logged.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from fastapi import Request
from pydantic import ValidationError

from sm_billing import constants as c

if TYPE_CHECKING:
    from fastapi import FastAPI
    from simple_module_core.events import EventBus

logger = logging.getLogger(__name__)

#: Fields ``build_provider`` reads.
PROVIDER_FIELDS = frozenset({"provider", *c.SECRET_FIELDS})
#: Fields whose change can start, stop or re-time the reconcile loop.
LOOP_FIELDS = PROVIDER_FIELDS | {"reconcile_interval_minutes"}
#: Usage-metering fields the sweeper and holds read per use: followed across
#: workers like the rest, but nothing is rebuilt for them.
USAGE_FIELDS = frozenset(
    {"usage_hold_ttl_seconds", "usage_sweep_interval_seconds", "usage_event_retention_days"}
)
#: Every field :func:`ensure_current` re-reads from the database.
FOLLOWED_FIELDS = LOOP_FIELDS | USAGE_FIELDS


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
    """The ``FOLLOWED_FIELDS`` values the database holds now (defaults where unset)."""
    from settings.constants import SYSTEM_SCOPE_ID
    from settings.contracts.schemas import SettingScope
    from settings.hydrate import build_settings
    from settings.models import Setting
    from sqlalchemy import select

    keys = {f"{c.PACKAGE}.{field}": field for field in FOLLOWED_FIELDS}
    stmt = select(Setting.key, Setting.value, Setting.value_type).where(
        Setting.scope == SettingScope.SYSTEM.value,
        Setting.scope_id == SYSTEM_SCOPE_ID,
        Setting.key.in_(keys),
    )
    async with app.state.sm.db.session_factory() as session:
        rows = (await session.execute(stmt)).tuples().all()
    overrides = {keys[key]: (value, value_type) for key, value, value_type in rows}
    settings = build_settings(type(getattr(app.state, c.PACKAGE).settings), overrides)
    return {field: getattr(settings, field) for field in FOLLOWED_FIELDS}


async def ensure_current(app: FastAPI) -> bool:
    """Catch up with a provider change another worker saved (#85).

    Returns ``True`` when something was rebuilt (a provider or loop field
    moved). The ``USAGE_FIELDS`` are followed too, into the loaded settings,
    but rebuild nothing and return ``False``. Cheap when nothing changed: one
    indexed read of the settings table, no lock.

    A field is followed only when the *database* moved since the last read
    (``stored_seen``), never merely because memory and database differ: the
    framework hot-swaps a save's settings before its request commits, so on the
    worker that took the save memory is briefly ahead of the database, and
    reverting to the stored value there would undo the save it just made.
    """
    services = getattr(app.state, c.PACKAGE, None)
    if services is None or services.provider is None:
        return False
    services.read_seq += 1
    ticket = services.read_seq
    try:
        stored = await _stored(app)
    except ValidationError:
        # A value written around the Settings screen that the class rejects:
        # keep running on what is loaded rather than 500 every billing route,
        # the connection screen that could fix it included.
        logger.warning("billing: stored settings do not validate; keeping the loaded ones")
        return False
    async with services.reload_lock:
        if ticket < services.applied_seq:
            return False  # a read taken after this one was already applied
        services.applied_seq = ticket
        current = services.settings
        seen = services.stored_seen
        if seen is None:
            seen = {f: getattr(current, f) for f in stored}
        services.stored_seen = stored
        changed = {f for f, v in stored.items() if v != seen[f] and getattr(current, f) != v}
        if not changed:
            return False  # in step, or a concurrent caller already caught up
        # Field names only: the values include the (encrypted) Stripe secrets.
        logger.info("billing: following settings saved elsewhere: %s", ", ".join(sorted(changed)))
        services.settings = current.model_copy(update={f: stored[f] for f in changed})
        if not changed & LOOP_FIELDS:
            return False  # usage fields only: read per use, nothing to rebuild
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
