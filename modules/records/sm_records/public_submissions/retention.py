"""Deleting website submissions once their type's retention has run out (#101).

Design §10. An in-process loop (:mod:`.retention_loop`) calls :func:`sweep`
every ``public_submissions_retention_interval_seconds``; each sweep deletes,
in every tenant that has types:

* **contact-form submissions** older than their type's ``retention_days``
  (``0`` keeps them forever) — the trash included, which is where spam sits;
* **newsletter signups never confirmed** whose last activity (the signup, or
  the latest confirmation sent) is older than the list's
  ``pending_purge_days``, in the trash or not;
* **delivery bookkeeping** (``records_submission_delivery``) older than
  ``public_submissions_delivery_retention_days``: who a submission's mail
  reached, kept only while a retry could still re-send it.

**Through the purge paths everyone else uses**, never a statement of its own:
a live record is trashed with ``soft_delete_record`` (so its ``on_delete``
referrers are honoured and the reduce indexes decremented), then purged with
``hard_delete_record`` — whose ``_purge_ids`` locks the record rows and
deletes their delivery claims *before* the rows go, the order a confirmation
task claiming a recipient serialises against (``delivery._alive``). Each
purged record publishes ``RecordTrashed`` (when it was live) and
``RecordPurged``. A record that cannot be deleted — a ``restrict`` referrer, a
concurrent writer — is skipped for this sweep and logged, never forced.

**Per tenant, in fresh sessions.** The tenants are read across the board
(:func:`sm_records._cross_tenant.read_all`) on a session closed before any
work; each tenant then runs under ``tenant_scope``, one short session per
batch of ``reindex_batch_size`` records, finished through
:func:`sm_records.events.commit` — ``finalize_session``, never a bare
``commit()``, so the purge events publish after the commit. A failing tenant
is logged and the rest go on.

**One sweeper at a time.** The sweep holds the framework lease
``records:public_submissions:retention`` (non-blocking): a second process, or
an overlapping tick, finds it held and does nothing. The deletes are
idempotent anyway — a record already purged is simply not found again.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

from simple_module_core.leases import Lease, lease
from sqlalchemy import and_, func, or_, select
from sqlalchemy import delete as sa_delete

from sm_records import events
from sm_records._cross_tenant import read_all
from sm_records.contracts.public_submissions import KIND_FORM, KIND_SUBSCRIPTION
from sm_records.index.query import Filter, FilterOp, filtered
from sm_records.models import RecordType, SubmissionDelivery, tables_for
from sm_records.services._common import utcnow
from sm_records.services.errors import Conflict, NotFound
from sm_records.services.records import hard_delete_record, soft_delete_record
from sm_records.services.types import get_type, list_types
from sm_records.settings import RecordsSettings
from sm_records.tenancy import bound_tenant, tenant_scope

__all__ = ["LEASE_NAME", "LEASE_TTL", "Swept", "sweep"]

logger = logging.getLogger(__name__)

LEASE_NAME: Final = "records:public_submissions:retention"
LEASE_TTL: Final = 300
"""Seconds; refreshed after every batch, so a long sweep keeps it."""

PENDING: Final = "pending"


@dataclass
class Swept:
    """What one sweep did, for the log line and the tests."""

    purged: int = 0
    skipped: int = 0
    deliveries: int = 0
    tenants: list[str] = field(default_factory=list)


async def _tenants(factory: Any) -> list[str]:
    """Every tenant with a record type — a record cannot be in a tenant its
    type is not in. Read unscoped on a session of its own, closed before any
    tenant's work starts."""
    session = factory()
    try:
        rows = await read_all(session, select(RecordType.tenant_id).distinct())
        return sorted(str(tenant) for tenant in rows.scalars().all())
    finally:
        await session.close()


def _due(rtype: RecordType, now: datetime, limit: int, skip: set[str]) -> Any:
    """The uuids of ``rtype``'s records past retention, trash included, or
    ``None`` when the type keeps everything."""
    config = rtype.public_submissions or {}
    cls = tables_for(rtype).record
    base = select(cls.uuid).where(cls.type_id == rtype.id, cls.tenant_id == bound_tenant())
    if config.get("kind") == KIND_FORM:
        days = int(config.get("retention_days", 365) or 0)
        if days <= 0:
            return None
        stmt = base.where(cls.created_at < now - timedelta(days=days))
    elif config.get("kind") == KIND_SUBSCRIPTION:
        days = max(1, int(config.get("pending_purge_days", 30) or 30))
        # The last activity, not the first signup: an address that comes back
        # (unsubscribed → pending) or is sent a fresh confirmation restarts
        # the clock, and every such write moves ``updated_at``.
        seen = func.coalesce(cls.updated_at, cls.created_at)
        pending = [Filter("sm_status", FilterOp.EQ, PENDING)]
        old = base.where(seen < now - timedelta(days=days))
        stmt = filtered(old, rtype, list(rtype.fields or []), pending)
    else:
        return None
    if skip:
        stmt = stmt.where(cls.uuid.not_in(sorted(skip)))
    return stmt.order_by(cls.id).limit(limit).execution_options(include_deleted=True)


async def _purge_one(session: Any, rtype: RecordType, uuid: str, settings: RecordsSettings) -> None:
    cls = tables_for(rtype).record
    stmt = select(cls).where(
        cls.uuid == uuid, cls.type_id == rtype.id, cls.tenant_id == bound_tenant()
    )
    record = (await session.execute(stmt.execution_options(include_deleted=True))).scalars().first()
    if record is None:
        return  # purged meanwhile: idempotent
    if not record.is_deleted:
        await soft_delete_record(session, rtype, record, settings=settings)
    await hard_delete_record(session, rtype, record)


@dataclass(frozen=True)
class _Run:
    """What every batch of one sweep shares."""

    factory: Any
    settings: RecordsSettings
    now: datetime
    held: Lease
    bus: Any

    def session(self) -> Any:
        session = self.factory()
        events.attach(session, self.bus)
        return session


async def _sweep_type(run: _Run, key: str, swept: Swept) -> None:
    """Batch after batch until nothing of ``key`` is due. A record that
    refuses rolls its batch back and is skipped; the batch is then redone
    without it."""
    settings = run.settings
    batch = max(1, settings.reindex_batch_size)
    skip: set[str] = set()
    while True:
        session = run.session()
        current: str | None = None
        try:
            rtype = await get_type(session, key)
            stmt = _due(rtype, run.now, batch, skip)
            uuids = [] if stmt is None else list((await session.execute(stmt)).scalars().all())
            if not uuids:
                await events.rollback(session)
                return
            for current in uuids:
                await _purge_one(session, rtype, current, settings)
            await events.commit(session)
            swept.purged += len(uuids)
        except (Conflict, NotFound) as exc:
            await events.rollback(session)
            if current is None:
                return  # the type itself went away mid-sweep
            logger.warning("records: retention skipped %s/%s: %s", key, current, exc.detail)
            skip.add(current)
            swept.skipped += 1
            continue
        except BaseException:
            await events.rollback(session)
            raise
        finally:
            await session.close()
        await run.held.refresh()
        if len(uuids) < batch:
            return


async def _prune_deliveries(run: _Run, cutoff: datetime) -> int:
    """Delete the bound tenant's delivery rows nothing can need any more: sent
    before ``cutoff``, a claim that expired before it, or a claim already
    given back. At worst a retry arriving later sends to a recipient the row
    said was reached — which is why the horizon is days, far past any retry."""
    table = SubmissionDelivery
    stale = or_(
        table.sent_at < cutoff,
        and_(table.sent_at.is_(None), or_(table.claimed_at.is_(None), table.claimed_at < cutoff)),
    )
    session = run.session()
    try:
        result = await session.execute(
            sa_delete(table)
            .where(table.tenant_id == bound_tenant(), stale)
            .execution_options(synchronize_session=False)
        )
        await events.commit(session)
        return int(result.rowcount or 0)
    except BaseException:
        await events.rollback(session)
        raise
    finally:
        await session.close()


async def _sweep_tenant(run: _Run, swept: Swept) -> None:
    session = run.factory()
    try:
        types = await list_types(session)
        keys = [t.key for t in types if (t.public_submissions or {}).get("kind")]
    finally:
        await session.close()
    for key in keys:
        await _sweep_type(run, key, swept)
    days = run.settings.public_submissions_delivery_retention_days
    swept.deliveries += await _prune_deliveries(run, run.now - timedelta(days=days))


async def sweep(
    factory: Any, settings: RecordsSettings, *, bus: Any = None, now: datetime | None = None
) -> Swept | None:
    """One pass over every tenant; ``None`` when another sweeper holds the
    lease. ``bus`` is the host's event bus, which the purge events go to."""
    held = lease(LEASE_NAME, ttl=LEASE_TTL, blocking=False)
    if not await held.acquire():
        return None
    swept = Swept()
    run = _Run(factory, settings, now or utcnow(), held, bus)
    try:
        for tenant in await _tenants(factory):
            try:
                with tenant_scope(tenant):
                    await _sweep_tenant(run, swept)
                swept.tenants.append(tenant)
            except Exception:
                logger.exception("records: retention failed for tenant %s", tenant)
    finally:
        await held.release()
    if swept.purged or swept.deliveries or swept.skipped:
        logger.info(
            "records: retention purged %d submission(s), skipped %d, pruned %d delivery row(s)",
            swept.purged,
            swept.skipped,
            swept.deliveries,
        )
    return swept
