"""The ``UserDeleted`` subscriber: tear down a deleted user's billing (#274).

Only in ``subject_mode = "user"``. The teardown is the one a deleted tenant
gets: :func:`sm_billing.sweep.run_teardown` (claim, backoff) over
:func:`sm_billing.teardown.cancel_for_deleted_tenant`, keyed by the user's
``user:<id>`` subject. A user with no billing is a no-op; a failure is logged
and retried like a tenant's: ``reconcile_one`` (``lifecycle.tenant_gone`` reads
a user subject whose user row is gone as deleted) for a mirrored subscription,
and the user-mode sweep (:mod:`sm_billing.user_sweep`) for the rest.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sm_billing.subjects import subject_for_user

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


def subscribe_user_teardown(app: FastAPI) -> None:
    from simple_module_core.user_events import UserDeleted

    async def _on_deleted(event: UserDeleted) -> None:
        from sm_billing.live import ensure_current
        from sm_billing.sweep import run_teardown

        subject = subject_for_user(event.user_id)
        try:
            await ensure_current(app)
            await run_teardown(app, subject)  # a failure is recorded for backoff
        except Exception:
            logger.warning(
                "billing: could not cancel the subscription of deleted user %s; the next "
                "reconcile retries it",
                subject,
                exc_info=True,
            )

    app.state.sm.event_bus.subscribe(UserDeleted, _on_deleted)
