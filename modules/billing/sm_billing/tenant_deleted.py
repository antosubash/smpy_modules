"""The ``TenantDeleted`` subscriber: tear down a deleted tenant's billing.

The teardown itself is :mod:`sm_billing.teardown`, run through
:func:`sm_billing.sweep.run_teardown` for its claim and backoff. Only tenant
subjects come through here: a ``user:<id>`` subject (#274) is no tenant, and
its teardown runs on ``UserDeleted`` instead.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sm_billing import constants as c
from sm_billing.subjects import kind

if TYPE_CHECKING:
    from fastapi import FastAPI
    from simple_module_core.events import EventBus

logger = logging.getLogger(__name__)


def subscribe(bus: EventBus, app: FastAPI) -> None:
    """Subscribe to ``TenantDeleted`` where the installed ``tenants`` has it.

    Imported defensively rather than raising billing's floor: the event and
    ``delete_tenant`` arrived together in ``simple_module_tenants`` 0.0.38, so
    an older host cannot delete a tenant and has nothing to subscribe to.
    """
    try:
        from tenants.contracts.events import TenantDeleted
    except ImportError:
        return

    async def _on_deleted(event: TenantDeleted) -> None:
        from sm_billing.live import ensure_current
        from sm_billing.sweep import run_teardown

        if kind(event.tenant_id) == c.SUBJECT_MODE_USER:
            logger.warning("billing: TenantDeleted for user subject %s ignored", event.tenant_id)
            return
        try:
            await ensure_current(app)  # not through a provider another worker replaced
            await run_teardown(app, event.tenant_id)  # a failure is recorded for backoff
        except Exception:
            logger.warning(
                "billing: could not cancel the subscription of deleted tenant %s; the next "
                "reconcile retries it (scheduled only if reconcile_interval_minutes is set)",
                event.tenant_id,
                exc_info=True,
            )

    bus.subscribe(TenantDeleted, _on_deleted)
