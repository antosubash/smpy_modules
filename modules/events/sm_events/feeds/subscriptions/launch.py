"""Starting one subscription's refresh: inline when Celery is eager, a message otherwise.

Called by the service after it has made the subscription due (create, a new address, resume,
"refresh now"). Nothing happens before the transaction commits, and never if it rolls back. Eager
(tests, a dev host with no broker) awaits the same claim, fetch and store on the request's own
loop once the commit is durable; otherwise one message goes to the ``events`` queue. A host with
neither a beat nor eager mode refreshes only when asked, and the subscription stays due.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from background_tasks import enqueue_after_commit
from simple_module_db.callbacks import register_on_commit

from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.feeds.importing.launch import celery_eager
from sm_events.feeds.subscriptions import refresh

__all__ = ["celery_eager", "refresh_one"]

logger = logging.getLogger(__name__)


def refresh_one(
    db: Any,
    *,
    tenant_id: str,
    subscription_id: uuid.UUID,
    session_factory: Any = None,
    settings: Any = None,
) -> None:
    """Refresh ``subscription_id`` once ``db`` commits."""
    if not celery_eager():
        enqueue_after_commit(db, constants.REFRESH_SUBSCRIPTION, tenant_id, str(subscription_id))
        return
    if session_factory is None or settings is None:  # nothing to run it with: it stays due
        logger.warning("events: an eager refresh had no session factory")
        return

    async def run() -> None:
        await refresh.refresh_one_async(
            session_factory,
            tenant_id=tenant_id,
            subscription_id=subscription_id,
            now=utcnow(),
            settings=settings,
        )

    register_on_commit(db, run)
