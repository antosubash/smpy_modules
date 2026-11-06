"""Handing an import to a worker (R13): inline when Celery is eager, a message otherwise.

Eager (tests, e2e, a dev host without a broker) awaits the slices on the request's own
loop, as images' ``ingest/imports/launch.py`` does - never ``.delay()``, whose eager mode
would start ``asyncio.run`` inside a running loop. Each slice has already committed its
lease release before it answers ``more`` (D2), so the next one claims at once.
"""

from __future__ import annotations

import logging
from typing import Any

from sm_newsletter.core.errors_import import ImportFailed
from sm_newsletter.imports.runner import run_import_async
from sm_newsletter.task_config import QUEUE_DEFAULT

__all__ = ["celery_eager", "enqueue", "launch", "records_worker_settings"]

logger = logging.getLogger(__name__)


def celery_eager() -> bool:
    """Whether the process's Celery app runs tasks inline (tests, dev without a broker)."""
    try:
        from celery import current_app
    except ImportError:  # pragma: no cover - background_tasks always brings celery
        return True
    return bool(current_app.conf.task_always_eager)


def records_worker_settings() -> Any:
    """Records' settings as a worker reads them: DB-backed, cached about 30 s."""
    from background_tasks import settings_for
    from sm_records.contracts.newsletter_import import RECORDS_PACKAGE, RecordsSettings

    return settings_for(RecordsSettings, RECORDS_PACKAGE)


def enqueue(tenant_id: str, import_id: int) -> None:
    """Send one slice to the ``newsletter`` queue."""
    from sm_newsletter.tasks import run_import

    run_import.s(tenant_id, import_id).apply_async(queue=QUEUE_DEFAULT)


async def launch(app: Any, *, tenant_id: str, import_id: int) -> None:
    """Start (or continue) the import ``import_id`` of ``tenant_id``."""
    if not celery_eager():
        enqueue(tenant_id, import_id)
        return
    factory = app.state.sm.db.session_factory
    settings = app.state.sm_records.settings
    try:
        while (
            await run_import_async(
                factory, tenant_id=tenant_id, import_id=import_id, records_settings=settings
            )
            == "more"
        ):
            pass
    except ImportFailed:
        # The job says ``failed``; the caller answers with that state.
        logger.info("newsletter import %s failed inline", import_id)
