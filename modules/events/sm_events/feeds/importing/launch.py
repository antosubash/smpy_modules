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

__all__ = ["celery_eager", "enqueue", "launch"]

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
