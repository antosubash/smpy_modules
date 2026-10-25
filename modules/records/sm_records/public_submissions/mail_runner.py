"""Getting a submission's notification sent, and marked sent (#101).

Never inside the request: SMTP latency (and its timing) would be on the
visitor's reply, and a mail failure would roll back a submission that is
perfectly good. Two paths, chosen per write:

* **The outbox, when the host has one** (``background_tasks`` installs
  ``bus.durable_transport``). :func:`queue_notification` publishes a
  :class:`NotificationDue` durably in the request's own transaction, so it
  exists exactly when the submission does, and the worker runs
  :func:`durable_handler`'s handler — retried with backoff, and raising while
  no mail transport is installed so the mail is retried rather than dropped.
  It writes only through ``ctx.db`` and never commits it (the transport
  does).
* **Otherwise after the commit.** An ``on_commit`` callback spawns a task
  (held by a strong reference) that opens its own session, binds the tenant,
  sends, writes the mark and finishes through :func:`sm_records.events.commit`
  — never a bare ``commit()``. That makes this module the **fourth documented
  committer**, beside ``cli_io``, ``reindex_runner`` and ``preview_runner``:
  it runs after the request's session is gone, so there is nobody else to
  commit. A crash can lose the mail; the mark then stays null, the record
  shows "not sent", and *Resend* recovers it.

Either way mail goes out only when the sender really delivers
(``delivers_email``) and ``public_base_url`` is set — the link has to be
absolute. Otherwise the record stands, a warning is logged and the mark stays
null. The event carries identifiers, the base URL, a locale and an attempt
id: never a field value and never a token. A retry of an attempt mails only
the recipients it has not reached (:mod:`.delivery`).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from typing import Any, Final

from simple_module_core.events import Event
from simple_module_core.mail import (
    MailSender,
    mail_transport_installed,
    resolve_mail_sender,
)
from simple_module_db import RequestSession
from simple_module_db.callbacks import register_on_commit
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from sm_records import constants, events
from sm_records.models import Record, RecordType
from sm_records.public_submissions.delivery import SessionFactory, load
from sm_records.public_submissions.mail import deliver
from sm_records.public_submissions.tokens import public_base_url
from sm_records.services._common import mark_written
from sm_records.settings import RecordsSettings
from sm_records.tenancy import tenant_scope

__all__ = [
    "HANDLER_NAME",
    "MailUnavailable",
    "NotificationDue",
    "Work",
    "drain",
    "durable_handler",
    "queue",
    "queue_notification",
    "ui_locale",
]

logger = logging.getLogger(__name__)

HANDLER_NAME: Final = "records.public_submissions.send_notification"
"""The durable subscription's name. Delivery state is keyed by it, so it
must never change: an outbox row naming a handler that no longer exists is
retried as unknown and then dropped."""

_TASKS: set[asyncio.Task[None]] = set()

Work = Callable[[AsyncSession, MailSender, Any, RecordsSettings, SessionFactory], Awaitable[None]]
"""What one queued mail does once a sender is resolved, in its tenant: the
notification here, the newsletter's confirmation in ``.confirmation``."""


class MailUnavailable(RuntimeError):  # noqa: N818 - reads as the condition it is
    """No mail transport in this process: raised so the outbox retries."""


@dataclass
class NotificationDue(Event):
    """Internal: the outbox's unit of work. Not a published contract —
    subscribers want :class:`~sm_records.contracts.events.FormSubmitted`."""

    tenant_id: str
    type_key: str
    uuid: str
    base_url: str
    locale: str
    attempt: str = ""
    """One delivery attempt: a retry of it skips the recipients it reached
    (``public_submissions.delivery``); a *Resend* is a new one."""


def ui_locale(app: Any) -> str:
    """The host's default console language: the notification goes to staff."""
    host = getattr(getattr(app.state, "host", None), "settings", None)
    return str(getattr(host, "i18n_default_locale", "") or "en")


def _durable(bus: Any, event_type: type) -> bool:
    return (
        bus is not None
        and getattr(bus, "durable_transport", None) is not None
        and bool(bus.durable.handler_names(event_type))
    )


async def queue(db: AsyncSession, app: Any, due: Any, work: Work, *, durable: bool = True) -> None:
    """Arrange for ``due`` to be worked once ``db`` commits: durably when the
    host has an outbox with a handler for it (and ``durable``), else after the
    commit."""
    bus = db.info.get(events.BUS_KEY)
    if durable and _durable(bus, type(due)):
        await bus.publish_durable(due, db)
    else:
        register_on_commit(db, partial(_spawn, app, due, work))
    # A *Resend* writes nothing else, and ``get_db`` commits — and runs
    # ``on_commit`` — only for a session that wrote; an outbox row the
    # transport has not flushed yet would be dropped the same way.
    mark_written(db)


async def _notify(
    db: AsyncSession, sender: MailSender, due: Any, settings: RecordsSettings, factory: Any
) -> None:
    loaded = await load(db, due)
    if loaded is not None:
        await deliver(db, *loaded, sender, due, settings, factory)


async def queue_notification(db: AsyncSession, app: Any, rtype: RecordType, record: Record) -> bool:
    """Arrange for ``record``'s notification to be sent once ``db`` commits.
    ``False`` when the type notifies nobody, which stores and sends nothing."""
    if not (rtype.public_submissions or {}).get("notify_to"):
        return False
    due = NotificationDue(
        tenant_id=rtype.tenant_id,
        type_key=rtype.key,
        uuid=record.uuid,
        base_url=public_base_url(app),
        locale=ui_locale(app),
        attempt=uuid.uuid4().hex,
    )
    await queue(db, app, due, _notify)
    return True


def _can_send(sender: MailSender, due: Any) -> bool:
    if not getattr(sender, "delivers_email", False):
        logger.warning(
            "records: %s submission %s stored but not mailed: no mail transport delivers email",
            due.type_key,
            due.uuid,
        )
        return False
    if not due.base_url:
        logger.warning(
            "records: %s submission %s stored but not mailed: set the host's public_base_url",
            due.type_key,
            due.uuid,
        )
        return False
    return True


def _independent(db: AsyncSession) -> Any:
    """Sessions on ``db``'s engine, outside its transaction — for the delivery
    progress a rollback of ``db`` must not take with it."""
    bind = db.get_bind()  # the sync Engine, or a Connection the transport opened
    engine = AsyncEngine(getattr(bind, "engine", bind))
    sync_class = type(db.sync_session)
    return lambda: RequestSession(
        bind=engine, sync_session_class=sync_class, expire_on_commit=False
    )


async def _run(app: Any, due: Any, work: Work) -> None:
    services = getattr(app.state, constants.PACKAGE, None)
    settings = getattr(services, "settings", None) or RecordsSettings()
    with tenant_scope(due.tenant_id):
        session = app.state.sm.db.session_factory()
        try:
            # Resolved from the session, like the outbox path: a host whose
            # sender is built from database settings installs a resolver, not
            # a sender, and ``current_mail_sender`` alone would answer the
            # console fallback (``delivers_email`` false) and never mail.
            sender = await resolve_mail_sender(session)
            if not _can_send(sender, due):
                return
            await work(session, sender, due, settings, app.state.sm.db.session_factory)
            await events.commit(session)
        except Exception:
            logger.exception(
                "records: mailing %s submission %s failed; it stays 'not sent'",
                due.type_key,
                due.uuid,
            )
            await events.rollback(session)
        finally:
            await session.close()


async def _spawn(app: Any, due: Any, work: Work) -> None:
    """The ``on_commit`` callback: start the send, do not wait for it."""
    task = asyncio.get_running_loop().create_task(_run(app, due, work))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


async def drain() -> None:
    """Wait for every send this process has started (tests; shutdown)."""
    while _TASKS:
        await asyncio.gather(*list(_TASKS), return_exceptions=True)


def durable_handler(module: Any, work: Work = _notify) -> Any:
    """The outbox handler, closed over the module for its settings (the worker
    builds the module without an app, so there is no ``app.state`` to read)."""

    async def send(event: Any, ctx: Any) -> None:
        if not mail_transport_installed():
            raise MailUnavailable("no mail transport is installed in this process")
        sender = await resolve_mail_sender(ctx.db)
        if not _can_send(sender, event):
            return
        settings = getattr(module, "settings", None) or RecordsSettings()
        with tenant_scope(event.tenant_id):
            await work(ctx.db, sender, event, settings, _independent(ctx.db))

    return send
