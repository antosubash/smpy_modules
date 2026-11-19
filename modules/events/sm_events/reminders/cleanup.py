"""Remove reminders when what they stand for is gone, and prune the ledger.

**Correctness never depends on this.** A follow whose user, membership or tenant is gone sends
nothing already: every tick re-reads the account, the membership and the access
(:mod:`~sm_events.reminders.recipients`). These handlers only remove the rows (a follow, and the
ledger rows that name the recipient), so a deleted account does not leave its follows behind. They
run in the web process (the framework's in-process bus); an event missed (a restart, another
process) leaves rows that still send nothing.

* ``UserDeleted``: that user's follows and ledger rows in every tenant: the one handler that reads
  across tenants, with its own user predicate and nothing else. The id is matched in every
  spelling (:func:`~sm_events.core.user_ids.spellings`), whatever the event carries and however the
  row was written;
* ``MembershipRemoved``: that user's rows in that tenant;
* ``TenantDeleted``: every row of that tenant.

A hard-deleted event or calendar takes its follows and ledger rows through the foreign keys; a
trashed one keeps them (restoring resumes reminders). A disabled user keeps theirs too: the next
tick refuses them, and a re-enable resumes. Each handler opens a session of its own, finishes it
with ``finalize_session`` and, on failure, logs the exception class (its message can quote an id)
and swallows it: a cleanup must never break the event that triggered it.

:func:`prune_ledger` is the janitor's: ledger rows whose occurrence started more than
``LEDGER_DAYS`` ago, in bounded batches. Only started occurrences are ever deleted, and nothing is
sent for one that has started, so a deleted row can never re-enable a send.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from typing import Any

from simple_module_db import all_tenants as unscoped
from simple_module_db import finalize_session, mark_written
from sqlalchemy import delete, select

from sm_events.core.constants import reminders_limits as limits
from sm_events.core.tenancy import bound_tenant, tenant_scope, valid_tenant
from sm_events.core.user_ids import user_match
from sm_events.models import EventFollow, ReminderSent

__all__ = [
    "delete_member_data",
    "delete_tenant_data",
    "delete_user_data",
    "prune_ledger",
    "subscribe",
]

logger = logging.getLogger(__name__)

_F, _L = EventFollow.__table__, ReminderSent.__table__


async def _run(
    factory: Callable[[], Any], statements: list[Any], scope: AbstractContextManager[Any]
) -> int:
    removed = 0
    with scope:
        async with factory() as session:
            for statement in statements:
                removed += int((await session.execute(statement)).rowcount or 0)
            mark_written(session)  # Core DML: mark it, whatever the session class listens for
            await finalize_session(session)
    return removed


def _by_user(user_id: Any, *, tenant: str | None = None) -> list[Any]:
    out = []
    for table, column in ((_F, _F.c.user_id), (_L, _L.c.recipient_id)):
        stmt = delete(table).where(user_match(column, user_id))
        out.append(stmt if tenant is None else stmt.where(table.c.tenant_id == tenant))
    return out


async def delete_user_data(factory: Callable[[], Any], user_id: Any) -> int:
    """Every follow and ledger row of ``user_id`` in every tenant (one narrow cross-tenant
    delete, whose only predicate is the user)."""
    return await _run(factory, _by_user(user_id), unscoped())


async def delete_member_data(factory: Callable[[], Any], tenant_id: str, user_id: Any) -> int:
    if not valid_tenant(tenant_id):
        return 0
    return await _run(factory, _by_user(user_id, tenant=tenant_id), tenant_scope(tenant_id))


async def delete_tenant_data(factory: Callable[[], Any], tenant_id: str) -> int:
    if not valid_tenant(tenant_id):
        return 0
    statements = [delete(t).where(t.c.tenant_id == tenant_id) for t in (_F, _L)]
    return await _run(factory, statements, tenant_scope(tenant_id))


async def prune_ledger(db: Any, *, now: datetime) -> int:
    """Delete ledger rows whose occurrence started more than ``LEDGER_DAYS`` ago, in the bound
    tenant, at most ``LEDGER_PRUNE_MAX_BATCHES`` batches of ``LEDGER_PRUNE_BATCH`` per call."""
    cutoff = now - timedelta(days=limits.LEDGER_DAYS)
    tenant = bound_tenant()
    removed = 0
    for _ in range(limits.LEDGER_PRUNE_MAX_BATCHES):
        batch = (
            select(_L.c.id)
            .where(_L.c.tenant_id == tenant, _L.c.starts_at < cutoff)
            .limit(limits.LEDGER_PRUNE_BATCH)
        )
        done = int(
            (
                await db.execute(delete(_L).where(_L.c.tenant_id == tenant, _L.c.id.in_(batch)))
            ).rowcount
            or 0
        )
        removed += done
        if done < limits.LEDGER_PRUNE_BATCH:
            break
    return removed


def _guarded(
    app: Any, label: str, work: Callable[[Any, Any], Awaitable[int]]
) -> Callable[[Any], Awaitable[None]]:
    async def handler(event: Any) -> None:
        try:
            removed = await work(app.state.sm.db.session_factory, event)
        except Exception as exc:  # the class only; the message can quote an id
            logger.warning("events: ReminderCleanup failed (%s)", type(exc).__name__)
            return
        if removed:
            logger.info("events: removed %d reminder row(s) (%s)", removed, label)

    return handler


def subscribe(bus: Any, app: Any) -> None:
    """Subscribe the three handlers; an event class the installed framework lacks is skipped
    with a log line (the others still apply)."""
    try:
        from simple_module_core.user_events import UserDeleted

        bus.subscribe(
            UserDeleted,
            _guarded(app, "user deleted", lambda f, e: delete_user_data(f, e.user_id)),
        )
    except ImportError:
        logger.info("events: this framework has no UserDeleted; reminders go with the janitor only")
    try:
        from tenants.contracts.events import MembershipRemoved

        bus.subscribe(
            MembershipRemoved,
            _guarded(
                app,
                "membership removed",
                lambda f, e: delete_member_data(f, e.tenant_id, e.user_id),
            ),
        )
    except ImportError:
        logger.info("events: no MembershipRemoved here; a removed member is refused at send time")
    try:
        from simple_module_core.tenant_events import TenantDeleted

        bus.subscribe(
            TenantDeleted,
            _guarded(app, "tenant deleted", lambda f, e: delete_tenant_data(f, e.tenant_id)),
        )
    except ImportError:
        logger.info(
            "events: this framework has no TenantDeleted; its reminders send nothing anyway"
        )
