"""Deleting website submissions once their type's retention has run out (#101).

Design §10. An in-process loop (:mod:`.retention_loop`) calls :func:`sweep`
every ``public_submissions_retention_interval_seconds``; each sweep deletes,
in every tenant that has types:

* **contact-form submissions** older than their type's ``retention_days``
  (``0`` keeps them forever) — the trash included, which is where spam sits;
* **newsletter signups never confirmed** within the list's
  ``pending_purge_days`` of when they last *entered* pending — the signup, or
  a return from unsubscribed or the trash, which is when ``sm_consent_at`` is
  written. A repeated signup of a pending address and an admin's *Resend*
  write no consent, so neither extends the window;
* **finished delivery bookkeeping** (:mod:`.retention_deliveries`).

**Eligibility is decided under the deletion lock.** The candidates are read
first, then each is re-read under the type lock and ``FOR UPDATE`` on its row
— the order every record write takes — and deleted only if it is *still* due:
a subscriber who confirmed between the two reads is skipped.

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
an overlapping tick, finds it held and does nothing. It is renewed every
:data:`REFRESH_EVERY` seconds *during* the work — before each record — and the
moment a renewal reports the lease lost, the sweep rolls back its batch and
stops (:class:`LeaseLost`). The deletes are idempotent anyway.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from simple_module_core.leases import lease
from sqlalchemy import select

from sm_records import events
from sm_records._cross_tenant import read_all
from sm_records.contracts.public_submissions import KIND_FORM, KIND_SUBSCRIPTION
from sm_records.index.query import Filter, FilterOp, filtered
from sm_records.models import RecordType, tables_for
from sm_records.public_submissions.retention_deliveries import prune_deliveries
from sm_records.services._common import utcnow
from sm_records.services._lock import lock_type
from sm_records.services.errors import Conflict, NotFound
from sm_records.services.records import hard_delete_record, soft_delete_record
from sm_records.services.types import get_type, list_types
from sm_records.settings import RecordsSettings
from sm_records.tenancy import bound_tenant, tenant_scope

__all__ = ["LEASE_NAME", "LEASE_TTL", "LeaseLost", "Swept", "sweep"]

logger = logging.getLogger(__name__)

LEASE_NAME: Final = "records:public_submissions:retention"
LEASE_TTL: Final = 300
REFRESH_EVERY: float = LEASE_TTL / 5
"""Seconds between renewals while a sweep works (a module attribute, so a
test can make it renew every time)."""

PENDING: Final = "pending"


class LeaseLost(RuntimeError):  # noqa: N818 - reads as the condition it is
    """The sweep's lease expired or moved to another owner mid-sweep."""


@dataclass
class Swept:
    """What one sweep did, for the log line and the tests."""

    purged: int = 0
    skipped: int = 0
    deliveries: int = 0
    tenants: list[str] = field(default_factory=list)


@dataclass
class _Run:
    """What every batch of one sweep shares."""

    factory: Any
    settings: RecordsSettings
    now: datetime
    held: Any
    bus: Any
    renewed: float = field(default_factory=time.monotonic)

    def session(self) -> Any:
        session = self.factory()
        events.attach(session, self.bus)
        return session

    async def keep(self) -> None:
        """Renew the lease when due; :class:`LeaseLost` once it is not ours."""
        if time.monotonic() - self.renewed < REFRESH_EVERY:
            return
        if not await self.held.refresh():
            raise LeaseLost(LEASE_NAME)
        self.renewed = time.monotonic()


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


def _days(config: dict[str, Any]) -> int:
    if config.get("kind") == KIND_FORM:
        return int(config.get("retention_days", 365) or 0)
    return max(1, int(config.get("pending_purge_days", 30) or 30))


def _due(rtype: RecordType, now: datetime, limit: int, skip: set[str]) -> Any:
    """The uuids that *may* be due, trash included, or ``None`` when the type
    keeps everything. A superset for a list — a pending window starts no
    earlier than the record — that :func:`_still_due` narrows under the lock."""
    config = rtype.public_submissions or {}
    cls = tables_for(rtype).record
    days = _days(config)
    if config.get("kind") not in (KIND_FORM, KIND_SUBSCRIPTION) or days <= 0:
        return None
    stmt = select(cls.uuid).where(
        cls.type_id == rtype.id,
        cls.tenant_id == bound_tenant(),
        cls.created_at < now - timedelta(days=days),
    )
    if config.get("kind") == KIND_SUBSCRIPTION:
        pending = [Filter("sm_status", FilterOp.EQ, PENDING)]
        stmt = filtered(stmt, rtype, list(rtype.fields or []), pending)
    if skip:
        stmt = stmt.where(cls.uuid.not_in(sorted(skip)))
    return stmt.order_by(cls.id).limit(limit).execution_options(include_deleted=True)


def _moment(value: Any) -> datetime | None:
    """A stored timestamp as an aware datetime (SQLite hands back naive UTC,
    and the payload holds ISO text)."""
    try:
        moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def _still_due(rtype: RecordType, record: Any, now: datetime) -> bool:
    """Whether the locked ``record`` is due *now*: a form submission past
    retention, or a subscriber still pending past the window that opened when
    they last entered pending."""
    config = rtype.public_submissions or {}
    cutoff = now - timedelta(days=_days(config))
    created = _moment(record.created_at) if record.created_at else None
    if created is None or created >= cutoff:
        return False
    if config.get("kind") == KIND_FORM:
        return True
    data = record.data or {}
    if data.get("sm_status") != PENDING:
        return False
    entered = (_moment(data["sm_consent_at"]) if data.get("sm_consent_at") else None) or created
    return entered < cutoff


async def _purge_one(session: Any, rtype: RecordType, uuid: str, run: _Run) -> bool:
    """Delete ``uuid`` if it is still due under the lock; ``False`` when it
    is not (or has gone)."""
    await lock_type(session, rtype)
    cls = tables_for(rtype).record
    stmt = (
        select(cls)
        .where(cls.uuid == uuid, cls.type_id == rtype.id, cls.tenant_id == bound_tenant())
        .with_for_update()
        .execution_options(include_deleted=True, populate_existing=True)
    )
    record = (await session.execute(stmt)).scalars().first()
    if record is None or not _still_due(rtype, record, run.now):
        return False
    if not record.is_deleted:
        await soft_delete_record(session, rtype, record, settings=run.settings)
    await hard_delete_record(session, rtype, record)
    return True


async def _sweep_type(run: _Run, key: str, swept: Swept) -> None:
    """Batch after batch until nothing of ``key`` is due. A record that
    refuses rolls its batch back and is skipped; the batch is then redone
    without it. One no longer due is skipped without a rollback."""
    batch = max(1, run.settings.reindex_batch_size)
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
            purged = 0
            for current in uuids:
                await run.keep()
                if await _purge_one(session, rtype, current, run):
                    purged += 1
                else:
                    skip.add(current)
            await run.keep()
            await events.commit(session)
            swept.purged += purged
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
        if len(uuids) < batch:
            return


async def _sweep_tenant(run: _Run, swept: Swept) -> None:
    session = run.factory()
    try:
        types = [t for t in await list_types(session) if (t.public_submissions or {}).get("kind")]
    finally:
        await session.close()
    for rtype in types:
        await _sweep_type(run, rtype.key, swept)
    await run.keep()
    days = run.settings.public_submissions_delivery_retention_days
    swept.deliveries += await prune_deliveries(run.session, types, run.now - timedelta(days=days))


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
            except LeaseLost:
                logger.warning("records: retention lost its lease; stopping this sweep")
                break
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
