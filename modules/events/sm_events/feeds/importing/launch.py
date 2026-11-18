"""Handing an import to a worker: inline when Celery is eager, a message otherwise.

Eager (tests, a dev host with no broker) awaits the slices on the request's own loop, never
``.delay()``, whose eager mode would start ``asyncio.run`` inside a running loop. Each slice has
released its lease before it answers ``more``, so the next one claims at once. Otherwise one
message goes to the ``events`` queue and the task re-enqueues itself for as long as it answers
``more``.
"""

from __future__ import annotations

import logging
from typing import Any

from sm_events.core import constants
from sm_events.feeds.importing.runner import run_import_async
from sm_events.task_config import QUEUE_DEFAULT

__all__ = ["celery_eager", "enqueue", "importer_check", "launch"]

logger = logging.getLogger(__name__)


def celery_eager() -> bool:
    """Whether the process's Celery app runs tasks inline."""
    try:
        from celery import current_app
    except ImportError:  # pragma: no cover - background_tasks always brings celery
        return True
    return bool(current_app.conf.task_always_eager)  # pyright: ignore[reportAttributeAccessIssue]


def enqueue(tenant_id: str, import_id: int) -> None:
    """Send one slice to the ``events`` queue."""
    from sm_events.tasks import run_import

    run_import.s(tenant_id, import_id).apply_async(queue=QUEUE_DEFAULT)  # pyright: ignore[reportCallIssue]


def importer_check(app: Any):
    """Who the importer is now, through the offline principal (the user directory, tenant
    membership, the permission registry), for the slices that run where an app exists. Called
    inside the slice's own tenant scope."""
    from sm_events.core.access.offline import offline_principal
    from sm_events.core.tenancy import bound_tenant

    async def check(tenant_id: str, user_id: str):
        async with app.state.sm.db.session_factory() as db:
            return await offline_principal(
                app, db, user_id=user_id, tenant_id=tenant_id or bound_tenant(), request=None
            )

    return check


async def launch(app: Any, *, tenant_id: str, import_id: int) -> None:
    """Start (or continue) the import ``import_id`` of ``tenant_id``."""
    if not celery_eager():
        enqueue(tenant_id, import_id)
        return
    factory = app.state.sm.db.session_factory
    locales = tuple(getattr(app.state, constants.PACKAGE).settings.content_locales)
    while (
        await run_import_async(factory, tenant_id=tenant_id, import_id=import_id, locales=locales)
        == "more"
    ):
        pass
