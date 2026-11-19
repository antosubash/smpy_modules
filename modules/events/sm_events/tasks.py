"""Celery tasks for events (autodiscovered by ``background_tasks``).

Imported by every process that builds the Celery app, so it stays light: Celery
here, everything else inside the bodies. Routing, queues and beat are in
:mod:`sm_events.task_config`.

* ``events.publish_due()`` - the beat every minute: publishes every event whose
  ``publish_at`` has come (:mod:`sm_events.content.publish_due`).
* ``events.run_import(tenant_id, import_id)`` - one slice of an ``.ics`` import; it enqueues the
  next one itself while the import is not finished.
* ``events.janitor()`` - hourly cleanup of imports and revoked private feed links.
* ``events.reminders()`` - the beat every minute that sends the reminders that have fallen due.
* ``events.refresh_subscriptions()`` - the beat every minute that fetches the external calendars
  that have fallen due; ``events.refresh_subscription(tenant_id, subscription_id)`` - one of them.

Bodies run through :mod:`sm_events.core.worker`: no app, a fresh event loop per
task, and the body binds every tenant itself.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from celery import shared_task
from celery.signals import worker_process_init

from sm_events.task_config import (
    JANITOR,
    PUBLISH_DUE,
    QUEUE_DEFAULT,
    REFRESH_SUBSCRIPTION,
    REFRESH_SUBSCRIPTIONS,
    REMINDERS,
    RUN_IMPORT,
)

logger = logging.getLogger(__name__)


@shared_task(name=PUBLISH_DUE)
def publish_due() -> dict[str, int]:
    """One pass of scheduled publishing; returns (and logs) its summary."""
    from sm_events.content.publish_due import publish_due_async
    from sm_events.core.clock import utcnow
    from sm_events.core.worker import run_platform

    summary = run_platform(lambda factory: publish_due_async(factory, now=utcnow()))
    logger.info(
        "events.publish_due: %d tenant(s), %d published, %d failed",
        summary["tenants"],
        summary["published"],
        summary["failed"],
    )
    return summary


def _content_locales() -> tuple[str, ...]:
    """The stored content locales, as a worker reads settings (``settings_for``, cached for 30 s).
    A database that cannot be read answers the defaults, loudly, as the framework's own worker
    does for its settings."""
    from background_tasks import settings_for

    from sm_events.core import constants
    from sm_events.core.settings import EventsSettings

    try:
        return tuple(settings_for(EventsSettings, constants.PACKAGE).content_locales)
    except Exception as exc:  # the class only
        logger.warning(
            "events: stored settings unreadable (%s); using defaults", type(exc).__name__
        )
        return tuple(EventsSettings().content_locales)


@shared_task(name=RUN_IMPORT)
def run_import(tenant_id: str, import_id: int) -> str:
    """One slice of the import ``import_id`` of ``tenant_id``: ``done``, ``more`` (the next slice
    is enqueued), ``busy`` or ``gone``. The platform runtime unbinds any caller tenant; the slice
    binds the import's own."""
    import asyncio

    from sm_events.core.worker import run_platform
    from sm_events.feeds.importing.runner import run_import_async

    async def body(factory: Any) -> str:
        # The stored settings are a synchronous read: off the loop, and only once the platform
        # runtime has refused a running one.
        locales = await asyncio.to_thread(_content_locales)
        return await run_import_async(
            factory, tenant_id=tenant_id, import_id=import_id, locales=locales
        )

    answer = run_platform(body)
    if answer == "more":
        run_import.s(tenant_id, import_id).apply_async(queue=QUEUE_DEFAULT)  # pyright: ignore[reportCallIssue]
    return answer


@shared_task(name=JANITOR)
def janitor() -> dict[str, int]:
    """One cleanup pass; returns (and logs) its counts, never a name or an id."""
    from sm_events.core.clock import utcnow
    from sm_events.core.worker import run_platform
    from sm_events.feeds.importing.janitor import janitor_async
    from sm_events.feeds.importing.launch import enqueue

    return run_platform(lambda factory: janitor_async(factory, now=utcnow(), relaunch=enqueue))


@shared_task(name=REMINDERS)
def reminders() -> dict[str, int]:
    """One reminder pass: every tenant with followers, in rotating order, inside the tick's
    budgets; returns (and logs) counts, never an address or a name."""
    from sm_events.core.clock import utcnow
    from sm_events.core.worker import run_platform
    from sm_events.reminders import worker_app
    from sm_events.reminders.tick import reminders_async

    return run_platform(
        lambda factory: reminders_async(
            factory, runtime_factory=worker_app.worker_runtime, now=utcnow()
        )
    )


async def _install_secret() -> bool:
    """Make the stored-secret crypto usable in this worker; ``False`` when there is no key (a
    worker never makes one). The lookup is a blocking read, so it runs off the loop."""
    import asyncio

    from sm_events.core import secret

    try:
        secret.install(await asyncio.to_thread(secret.resolve_worker_secret))
    except secret.SecretMissing:
        return False
    return True


@shared_task(name=REFRESH_SUBSCRIPTIONS)
def refresh_subscriptions() -> dict[str, int]:
    """One pass over the due external calendars; counts only. Without a secret key the worker
    cannot open any address: it fetches nothing and records nothing against the feeds."""
    from sm_events.core.clock import utcnow
    from sm_events.core.worker import run_platform
    from sm_events.feeds.subscriptions import refresh

    async def body(factory: Any) -> dict[str, int]:
        if not await _install_secret():
            logger.warning("events.refresh_subscriptions: no secret key; nothing was fetched")
            return {"unavailable": 1, **dict.fromkeys(refresh.COUNTS, 0)}
        settings = await asyncio.to_thread(refresh._stored_settings)
        return await refresh.refresh_async(factory, now=utcnow(), settings=settings)

    return run_platform(body)


@shared_task(name=REFRESH_SUBSCRIPTION)
def refresh_subscription(tenant_id: str, subscription_id: str) -> str:
    """One subscription, on demand: the same claim, guarded fetch and fenced store. ``gone`` for
    a tenant or an id that is nothing."""
    import uuid

    from sm_events.core.clock import utcnow
    from sm_events.core.tenancy import valid_tenant
    from sm_events.core.worker import run_platform
    from sm_events.feeds.subscriptions import refresh

    async def body(factory: Any) -> str:
        try:
            sid = uuid.UUID(subscription_id)
        except ValueError:
            return "gone"
        if not valid_tenant(tenant_id):
            return "gone"
        if not await _install_secret():
            return "unavailable"
        settings = await asyncio.to_thread(refresh._stored_settings)
        return await refresh.refresh_one_async(
            factory, tenant_id=tenant_id, subscription_id=sid, now=utcnow(), settings=settings
        )

    return run_platform(body)


@worker_process_init.connect(weak=False, dispatch_uid="sm_events.forget_parent_runtime")
def forget_parent_runtime(**_: Any) -> None:
    """A prefork child must not reuse its parent's engine."""
    from sm_events.core.worker import reset_worker_runtime
    from sm_events.reminders.worker_app import reset_worker_app

    reset_worker_runtime()
    reset_worker_app()
