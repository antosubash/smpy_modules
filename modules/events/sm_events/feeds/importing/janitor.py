"""The hourly cleanup (Ruling 30): imports that are finished or lost, and revoked feed links.

Per tenant, under ``tenant_scope`` and a session of its own (one tenant's failure is logged by
class and the pass goes on):

* ``staged``, ``done`` and ``failed`` imports whose last change is older than ``IMPORT_TTL`` are
  deleted with their items (staged items hold event text);
* an ``uploaded``/``queued`` import that has sat for a lease, and a ``parsing``/``running`` one
  whose lease ran out, was lost (a dropped message, a dead worker): it is **relaunched** (the
  claim is the guard, so a relaunch of something alive is ``busy``);
* revoked private feed links older than ``FEED_REVOKED_KEPT_DAYS`` are removed;
* reminder ledger rows whose occurrence started more than ``LEDGER_DAYS`` ago are pruned, in
  bounded batches.

The tenants come from one narrow cross-tenant read of ``tenant_id`` values. Only counts reach
the log: never a file name, an id or a tenant.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from simple_module_db import all_tenants as unscoped
from sqlalchemy import delete, distinct, or_, select

from sm_events.core import constants
from sm_events.core.constants import reminders_limits as limits
from sm_events.core.tenancy import all_tenants, tenant_scope, valid_tenant
from sm_events.feeds.tokens.cleanup import sweep_revoked
from sm_events.models import EventImport, EventImportItem, FeedToken, ReminderSent
from sm_events.reminders import cleanup as reminder_cleanup

__all__ = ["janitor_async"]

logger = logging.getLogger(__name__)
_FINISHED = ("staged", "done", "failed", "uploaded", "parsing")
"""Expire after ``IMPORT_TTL`` like the rest: a parse that never finishes does not linger."""


async def _tenants(factory: Any, now: datetime) -> list[str]:
    found: set[str] = set()
    with unscoped():
        async with factory() as db:
            for model in (EventImport, FeedToken):
                stmt = all_tenants(select(distinct(model.tenant_id)))
                found.update((await db.execute(stmt)).scalars())
            old = all_tenants(
                select(distinct(ReminderSent.tenant_id)).where(
                    ReminderSent.starts_at < now - timedelta(days=limits.LEDGER_DAYS)
                )
            )
            found.update((await db.execute(old)).scalars())
    return sorted(t for t in found if valid_tenant(t))


async def _expire(db: Any, now: datetime) -> int:
    table, items = EventImport.__table__, EventImportItem.__table__
    ids = list(
        (
            await db.execute(
                select(table.c.id).where(
                    table.c.status.in_(_FINISHED), table.c.updated_at < now - constants.IMPORT_TTL
                )
            )
        ).scalars()
    )
    if ids:
        await db.execute(delete(items).where(items.c.import_id.in_(ids)))
        await db.execute(delete(table).where(table.c.id.in_(ids)))
    return len(ids)


async def _lost(db: Any, now: datetime) -> list[int]:
    table = EventImport.__table__
    stale = now - constants.IMPORT_LEASE
    stmt = select(table.c.id).where(
        or_(
            table.c.status.in_(("uploaded", "queued")) & (table.c.updated_at < stale),
            table.c.status.in_(("parsing", "running")) & (table.c.lease_until < now),
        )
    )
    return list((await db.execute(stmt)).scalars())


async def _tenant(factory: Any, tenant: str, now: datetime) -> tuple[int, list[int], int, int]:
    from simple_module_db import finalize_session, mark_written

    with tenant_scope(tenant):
        async with factory() as db:
            deleted = await _expire(db, now)
            lost = await _lost(db, now)
            tokens = await sweep_revoked(db, now=now)
            ledger = await reminder_cleanup.prune_ledger(db, now=now)
            mark_written(db)  # Core DML: mark it, whatever the session class listens for
            await finalize_session(db)
    return deleted, lost, tokens, ledger


async def janitor_async(
    factory: Any, *, now: datetime, relaunch: Callable[[str, int], None]
) -> dict[str, int]:
    """One pass; ``{"tenants", "deleted", "relaunched", "tokens"}``."""
    summary = {"tenants": 0, "deleted": 0, "relaunched": 0, "tokens": 0, "ledger": 0}
    for tenant in await _tenants(factory, now):
        summary["tenants"] += 1
        try:
            deleted, lost, tokens, ledger = await _tenant(factory, tenant, now)
        except Exception as exc:  # one tenant's failure never stops the rest
            logger.warning("events.janitor: a tenant failed (%s)", type(exc).__name__)
            continue
        summary["deleted"] += deleted
        summary["tokens"] += tokens
        summary["ledger"] += ledger
        for import_id in lost:
            try:
                relaunch(tenant, import_id)
            except Exception as exc:  # a broker that is down: the next pass tries again
                logger.warning("events.janitor: a relaunch failed (%s)", type(exc).__name__)
            else:
                summary["relaunched"] += 1
    logger.info(
        "events.janitor: %d tenant(s), %d import(s) deleted, %d relaunched, %d link(s) removed, "
        "%d ledger row(s) pruned",
        summary["tenants"],
        summary["deleted"],
        summary["relaunched"],
        summary["tokens"],
        summary["ledger"],
    )
    return summary
