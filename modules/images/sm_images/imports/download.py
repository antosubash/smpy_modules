"""``images.download_items(job_id, ids, generation)``'s body: fetch and settle URL items.

Per item, with no transaction open while the network is used:

1. **Claim** it: one conditional ``UPDATE`` stamps a fresh claim token and an
   expiry (:data:`CLAIM_SECONDS`) on a ``pending`` item nobody holds (or whose
   claim expired), of a job ``running`` in the message's generation. A
   duplicate message - reconcile's re-send, a redelivery - finds it held and
   skips it, so one item is fetched once. Settlement requires the token, and
   the job's generation (``settle``); a claim that expired and was taken over
   loses there and rolls back.
2. **Dedupe** (layer 3, before any byte moves): an image of this collection
   with the item's external id, trashed or not, makes it a duplicate.
3. **Fetch** with ``safe_stream`` (``max_image_bytes``, ``download_timeout``)
   inside a :class:`DomainLimiter` slot, under the retry policy of
   :mod:`.retrying`; a deferred item stays ``pending`` (its claim released)
   for reconcile. The batch heartbeats its job meanwhile (:mod:`.beat`).
4. **Settle** through ingest (:func:`settle.settle_bytes`) - sniff, decode
   guards and the unique index, so a payload that is not an image fails with
   ingest's code.

The limiter belongs to one task (one event loop): it bounds a batch, not the
fleet (see :mod:`sm_images.imports.rate_limit`).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timedelta
from typing import Final

from simple_module_db import finalize_session, tenant_context
from sqlalchemy import or_, select, update

from sm_images import constants
from sm_images.imports import access, jobs, settle, terminal
from sm_images.imports.beat import beating
from sm_images.imports.chunk import Stopped
from sm_images.imports.features import url_filename
from sm_images.imports.jobs import SYNC, now
from sm_images.imports.lookup import live_collection
from sm_images.imports.rate_limit import DomainLimiter
from sm_images.imports.retrying import Defer, Fail, fetch_with_retries
from sm_images.ingest import dedupe
from sm_images.models import ImportItem, ImportJob
from sm_images.models.enums import ItemStatus, JobStatus
from sm_images.pipeline.runtime import Runtime, bind_runtime

__all__ = ["CLAIM_SECONDS", "download_items_async"]

logger = logging.getLogger(__name__)

CLAIM_SECONDS: Final = 900
"""How long a claim holds an item: longer than one item's worst case
(``retrying.INLINE_ATTEMPTS`` fetches of ``download_timeout`` plus the waits)."""


async def _claim(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int, item_id: int
) -> tuple[ImportItem, str] | None:
    """Hold the item for this message: ``(row, token)``, or ``None`` to skip it."""
    token = uuid.uuid4().hex
    stamp = now()
    running = select(ImportJob.id).where(
        ImportJob.id == job_id,
        ImportJob.tenant_id == tenant,
        ImportJob.status == JobStatus.RUNNING,
        ImportJob.generation == generation,
    )
    stmt = (
        update(ImportItem)
        .where(
            ImportItem.id == item_id,
            ImportItem.tenant_id == tenant,
            ImportItem.job_id == job_id,
            ImportItem.status == ItemStatus.PENDING,
            or_(ImportItem.claim_token.is_(None), ImportItem.claim_expires_at < stamp),
            or_(ImportItem.next_attempt_at.is_(None), ImportItem.next_attempt_at <= stamp),
            ImportItem.job_id.in_(running.scalar_subquery()),
        )
        .values(
            claim_token=token,
            claim_expires_at=stamp + timedelta(seconds=CLAIM_SECONDS),
            claim_generation=generation,
            updated_at=stamp,
        )
        .returning(ImportItem.id)
        .execution_options(**SYNC)
    )
    async with runtime.session_factory() as db:
        row = None
        if (await db.execute(stmt)).first() is not None:
            found = select(ImportItem).where(
                ImportItem.id == item_id, ImportItem.tenant_id == tenant
            )
            row = (await db.execute(found)).scalar_one()
            db.expunge(row)
        await finalize_session(db)
    return None if row is None else (row, token)


async def _defer(
    runtime: Runtime,
    tenant: str,
    job: tuple,
    item_id: int,
    token: str,
    code: str,
    attempts: int,
    delay: float | None = None,
) -> None:
    """Leave the item ``pending`` and release the claim, for reconcile to re-send
    once ``delay`` seconds have passed - only while this claim, of this
    generation, is still the job's current one. A deferral is progress for the
    poison-job breaker (``defer_progress``): the server said when to come back."""
    job_id, generation = job
    current = select(ImportJob.id).where(
        ImportJob.id == job_id,
        ImportJob.tenant_id == tenant,
        ImportJob.generation == generation,
    )
    async with runtime.session_factory() as db:
        deferred = await db.execute(
            update(ImportItem)
            .where(
                ImportItem.id == item_id,
                ImportItem.tenant_id == tenant,
                ImportItem.status == ItemStatus.PENDING,
                ImportItem.claim_token == token,
                ImportItem.claim_generation == generation,
                ImportItem.job_id.in_(current.scalar_subquery()),
            )
            .values(
                attempts=ImportItem.attempts + attempts,
                last_error=code,
                next_attempt_at=None if delay is None else now() + timedelta(seconds=delay),
                claim_token=None,
                claim_expires_at=None,
                claim_generation=None,
                updated_at=now(),
            )
            .returning(ImportItem.id)
            .execution_options(**SYNC)
        )
        if deferred.first() is not None:
            counted = ImportJob.defer_progress + 1
            stmt = update(ImportJob).where(ImportJob.id.in_(current.scalar_subquery()))
            await db.execute(stmt.values(defer_progress=counted).execution_options(**SYNC))
        await finalize_session(db)


async def _duplicate(runtime: Runtime, tenant: str, job: tuple, coll, item, token: str) -> bool:
    """Layer 3, before any byte moves: settle as a duplicate of an existing image."""
    job_id, generation = job
    async with runtime.session_factory() as db:
        dup = await dedupe.find_external(db, coll.id, constants.SOURCE_IMPORT, item.external_id)
        if dup is not None:
            kept = await settle.mark_item(
                db, tenant, item.id, ItemStatus.DUPLICATE, image_id=dup, token=token
            )
            deltas = {ItemStatus.DUPLICATE: 1}
            if kept and not await jobs.bump(db, tenant, job_id, deltas, generation):
                await db.rollback()
                return True
        await finalize_session(db)
    return dup is not None


async def _one(runtime, tenant, job: tuple, coll, claimed, limiter, settings, db_lock) -> None:
    """One item. Its database phases hold ``db_lock`` (one transaction at a time
    per batch - short ones); the fetch runs outside it, concurrently."""
    job_id, generation = job
    item, token = claimed
    if item.external_id is not None:
        async with db_lock:
            if await _duplicate(runtime, tenant, job, coll, item, token):
                return
    assert item.url is not None
    try:
        data, attempts = await fetch_with_retries(item.url, limiter, settings, item.attempts)
    except Fail as failed:
        async with db_lock:
            await settle.fail_item(
                runtime,
                tenant,
                job_id,
                generation,
                item.id,
                failed.code,
                attempts=failed.attempts,
                token=token,
            )
        return
    except Defer as deferred:
        async with db_lock:
            args = (deferred.code, deferred.attempts, deferred.delay)
            await _defer(runtime, tenant, job, item.id, token, *args)
        return
    async with db_lock:
        await settle.settle_bytes(
            runtime,
            tenant,
            job_id,
            generation,
            coll,
            item.id,
            data,
            filename=url_filename(item.url),
            meta=settle.item_meta(item),
            attempts=attempts,
            token=token,
        )


async def _run(runtime, tenant, job_id, generation, ids) -> int:
    async with runtime.session_factory() as db:
        stmt = select(ImportJob.collection_id).where(
            ImportJob.id == job_id, ImportJob.tenant_id == tenant
        )
        job_row = (await db.execute(stmt)).first()
        await finalize_session(db)
    if job_row is None:
        return 0
    coll = await live_collection(runtime, tenant, job_row[0])
    if coll is None:
        return 0
    try:
        await access.guard(runtime, tenant, job_id, generation)
    except Stopped:
        return 0
    settings = runtime.settings()
    limiter = DomainLimiter(
        settings.download_concurrency_per_domain, settings.download_concurrency_total
    )
    claims = [await _claim(runtime, tenant, job_id, generation, x) for x in ids]
    held = [c for c in claims if c is not None]
    db_lock = asyncio.Lock()
    job = (job_id, generation)
    # A fetch settles nothing for up to ``download_timeout`` per attempt: beat
    # meanwhile, or reconcile would take a healthy job for a dead one.
    async with beating(runtime, tenant, job_id, generation):
        results = await asyncio.gather(
            *(_one(runtime, tenant, job, coll, c, limiter, settings, db_lock) for c in held),
            return_exceptions=True,
        )
    for result in results:
        if isinstance(result, BaseException):
            logger.warning("images.import.download_failed job=%s", job_id, exc_info=result)
    await terminal.try_complete(runtime, tenant, job_id, generation)
    return len(held)


async def download_items_async(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int, ids: list[int]
) -> int:
    """Download and settle the items ``ids`` of job ``job_id`` for a runner of
    ``generation``; returns how many this call held."""
    with tenant_context(tenant), bind_runtime(runtime):
        return await _run(runtime, tenant, job_id, generation, ids)
