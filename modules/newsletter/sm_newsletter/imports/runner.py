"""Running a queued import (R13, R14, D2, D3, D6): one slice of leased, resumable batches.

One session per step, from ``factory``, under ``tenant_scope(tenant_id)``:

1. **Claim** for a fresh owner (:func:`~.fence.claim`): ``gone`` when there is no such job in
   the tenant or it is not ``queued``/``running``, ``busy`` when someone holds a live lease.
2. **Tags, once** (:mod:`.tags_step`), fenced.
3. **Batches** of ``BATCH_SIZE`` rows still to do, in ``seq`` order, while the slice lasts; each
   is :func:`~.apply.apply_batch` plus the fenced counter update (which renews the lease) in
   one transaction. A crash rolls the batch back and the next claim redoes it.
4. **No rows left**: ``done``, the lease cleared and the staged rows deleted, in one fenced
   transaction.
5. **Out of time**: a fenced release (``lease_owner = NULL``, ``lease_until = now``), then
   ``more``; the next slice claims it at once (D2).

Every write after the claim is fenced (D3). A lost lease rolls back and writes nothing more:
``busy``. Any other exception is recorded as ``failed`` / ``import_failed`` (fenced too: when
that matches nothing the job is someone else's, and the answer is ``busy``), logged by class
name only and re-raised as :class:`~sm_newsletter.core.errors_import.ImportFailed` with no
chained exception, because an exception can carry an address (D6).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Literal

from simple_module_db import finalize_session
from sm_records.contracts.newsletter_import import importable_fields
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from sm_newsletter.core.clock import utcnow
from sm_newsletter.core.errors_import import ImportFailed
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.imports import tags_step
from sm_newsletter.imports.apply import BatchResult, apply_batch
from sm_newsletter.imports.constants import (
    BATCH_SIZE,
    DONE,
    FAILED,
    KEEP_ERRORS,
    LEASE,
    SLICE_SECONDS,
)
from sm_newsletter.imports.fence import LeaseLost, claim, fenced
from sm_newsletter.models import ImportEntry, ImportJob

__all__ = ["SliceResult", "run_import_async"]

logger = logging.getLogger(__name__)

SliceResult = Literal["done", "more", "busy", "gone"]
SessionFactory = Callable[[], AsyncSession]


class _Slice:
    """One call's owner, tenant, job and clock."""

    def __init__(
        self, factory: SessionFactory, tenant_id: str, import_id: int, settings: Any, clock: Any
    ) -> None:
        self.factory, self.tenant_id, self.import_id = factory, tenant_id, import_id
        self.settings, self.clock = settings, clock
        self.owner = str(uuid.uuid4())

    async def fence(self, session: AsyncSession, values: dict[str, Any]) -> None:
        await fenced(
            session,
            tenant_id=self.tenant_id,
            import_id=self.import_id,
            owner=self.owner,
            values=values,
        )

    async def job(self, session: AsyncSession) -> ImportJob:
        stmt = (
            select(ImportJob)
            .where(col(ImportJob.id) == self.import_id, col(ImportJob.tenant_id) == self.tenant_id)
            .execution_options(populate_existing=True)
        )
        return (await session.execute(stmt)).scalar_one()

    async def claim(self) -> str:
        async with self.factory() as session:
            answer = await claim(
                session,
                tenant_id=self.tenant_id,
                import_id=self.import_id,
                owner=self.owner,
                now=self.clock(),
            )
            await finalize_session(session)
            return answer

    async def tags(self) -> None:
        async with self.factory() as session:
            job = await self.job(session)
            if tags_step.needs_tags(job):
                await tags_step.tags_once(
                    session,
                    tenant_id=self.tenant_id,
                    job=job,
                    owner=self.owner,
                    records_settings=self.settings,
                )
            await finalize_session(session)

    async def batch(self) -> bool:
        """One batch, or completion when none is left; whether the import is done."""
        async with self.factory() as session:
            stmt = (
                select(ImportEntry)
                .where(
                    col(ImportEntry.tenant_id) == self.tenant_id,
                    col(ImportEntry.import_id) == self.import_id,
                    col(ImportEntry.outcome).is_(None),
                )
                .order_by(col(ImportEntry.seq))
                .limit(BATCH_SIZE)
            )
            rows = list((await session.execute(stmt)).scalars())
            now = self.clock()
            if not rows:
                await self._complete(session, now)
                await finalize_session(session)
                return True
            job = await self.job(session)
            targets = await importable_fields(
                session, tenant_id=self.tenant_id, type_key=job.list_type_key
            )
            if targets is None:
                raise LookupError("the import's list is gone")
            result = await apply_batch(
                session,
                tenant_id=self.tenant_id,
                job=job,
                rows=rows,
                targets=targets,
                records_settings=self.settings,
                now=now,
            )
            await self.fence(session, _counters(job, result, now))
            await finalize_session(session)
            return False

    async def _complete(self, session: AsyncSession, now: datetime) -> None:
        """``done`` and the staged rows' ``DELETE``, the latter only after the guard matched."""
        await self.fence(
            session, {"status": DONE, "finished_at": now, "lease_owner": None, "lease_until": None}
        )
        await session.execute(
            delete(ImportEntry)
            .where(
                col(ImportEntry.tenant_id) == self.tenant_id,
                col(ImportEntry.import_id) == self.import_id,
            )
            .execution_options(synchronize_session=False)
        )

    async def release(self) -> None:
        async with self.factory() as session:
            await self.fence(session, {"lease_owner": None, "lease_until": self.clock()})
            await finalize_session(session)

    async def fail(self) -> bool:
        """The fenced failure write in a fresh session; whether it matched."""
        values = {
            "status": FAILED,
            "error_code": ImportFailed.code,
            "finished_at": self.clock(),
            "lease_owner": None,
            "lease_until": None,
        }
        async with self.factory() as session:
            try:
                await self.fence(session, values)
            except LeaseLost:
                return False
            await finalize_session(session)
            return True


def _counters(job: ImportJob, result: BatchResult, now: datetime) -> dict[str, Any]:
    kept = list(job.errors or [])
    room = max(KEEP_ERRORS - len(kept), 0)
    return {
        "processed": ImportJob.processed + result.processed,
        "created": ImportJob.created + result.created,
        "updated": ImportJob.updated + result.updated,
        "skipped": ImportJob.skipped + result.skipped,
        "suppressed": ImportJob.suppressed + result.suppressed,
        "failed": ImportJob.failed + result.failed,
        "errors": kept + result.errors[:room],
        "errors_total": ImportJob.errors_total + len(result.errors),
        "lease_until": now + LEASE,
    }


async def _work(step: _Slice, slice_seconds: float) -> SliceResult:
    answer = await step.claim()
    if answer != "claimed":
        return answer  # type: ignore[return-value]
    deadline = step.clock() + timedelta(seconds=slice_seconds)
    await step.tags()
    while not await step.batch():
        if step.clock() >= deadline:
            await step.release()
            return "more"
    return "done"


async def run_import_async(
    factory: SessionFactory,
    *,
    tenant_id: str,
    import_id: int,
    records_settings: Any,
    clock: Callable[[], datetime] | None = None,
    slice_seconds: float | None = None,
) -> SliceResult:
    """One slice of the import ``import_id`` of ``tenant_id`` (``clock`` and ``slice_seconds``
    default to ``utcnow`` and ``SLICE_SECONDS``, looked up per call)."""
    clock = clock or utcnow
    if slice_seconds is None:
        slice_seconds = SLICE_SECONDS
    with tenant_scope(tenant_id):
        step = _Slice(factory, tenant_id, import_id, records_settings, clock)
        failure: str | None = None
        try:
            return await _work(step, slice_seconds)
        except LeaseLost:
            logger.info("newsletter import %s lost its lease; nothing written", import_id)
            return "busy"
        except Exception as exc:
            failure = type(exc).__name__
        # Outside the handler: nothing of the original exception is chained from here on.
        try:
            recorded = await step.fail()
        except Exception as exc:
            logger.error(
                "newsletter import %s failed: %s (recording it failed: %s)",
                import_id,
                failure,
                type(exc).__name__,
            )
        else:
            if not recorded:
                logger.info(
                    "newsletter import %s: %s after losing its lease; nothing written",
                    import_id,
                    failure,
                )
                return "busy"
            logger.warning("newsletter import %s failed: %s", import_id, failure)
    raise ImportFailed("import failed") from None
