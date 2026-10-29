"""``images.download_items(job_id, ids, generation)``'s body: fetch and settle URL items.

Per item, with no transaction open while the network is used:

1. **Claim** it once it holds its :class:`DomainLimiter` slot, just before
   its fetch - never up front for the batch, where an item queued behind the
   per-domain limit could outwait its claim and be fetched again by
   reconcile's re-send. One conditional ``UPDATE`` stamps a fresh claim token
   and an expiry (:data:`CLAIM_SECONDS`) on a ``pending`` item nobody holds
   (or whose claim expired), of a job ``running`` in the message's
   generation. A duplicate message - reconcile's re-send, a redelivery -
   finds it held and skips it, so one item is fetched once; an item this run
   never claims is left untouched for reconcile. Settlement requires the
   token, and the job's generation (``settle``); a claim that expired and was
   taken over loses there and rolls back.
2. **Dedupe** (layer 3, before any byte moves): an image of this collection
   with the item's external id, trashed or not, makes it a duplicate.
3. **Fetch** with ``safe_stream`` (``max_image_bytes``, ``download_timeout``)
   in that slot, under the retry policy of :mod:`.retrying`; a deferred item
   stays ``pending`` (its claim released) for reconcile. The batch heartbeats
   its job meanwhile (:mod:`.beat`).
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

from simple_module_db import finalize_session, tenant_context
from sqlalchemy import select

from sm_images.imports import access, item_claim, settle, terminal
from sm_images.imports.beat import beating
from sm_images.imports.chunk import Stopped
from sm_images.imports.features import url_filename
from sm_images.imports.item_claim import CLAIM_SECONDS
from sm_images.imports.item_claim import claim as _claim  # noqa: F401 - the tests' handle
from sm_images.imports.lookup import live_collection
from sm_images.imports.rate_limit import DomainLimiter
from sm_images.imports.retrying import Defer, Fail, fetch_with_retries
from sm_images.models import ImportItem, ImportJob
from sm_images.models.enums import ItemStatus
from sm_images.pipeline.runtime import Runtime, bind_runtime

__all__ = ["CLAIM_SECONDS", "download_items_async"]

logger = logging.getLogger(__name__)


class _Skip(Exception):  # noqa: N818 - a signal
    """Nothing to fetch: another run holds the item (or it is settled), or it
    was settled as a duplicate."""


async def _one(
    runtime, tenant, job: tuple, coll, pending, limiter, settings, db_lock, *, auto_run: bool
) -> bool:
    """One item; whether this run held it. Its database phases hold
    ``db_lock`` (one transaction at a time per batch - short ones); the fetch
    runs outside it, concurrently."""
    job_id, generation = job
    item_id, url = pending
    held: list[tuple[ImportItem, str]] = []

    async def claim_in_slot() -> int:
        async with db_lock:
            claimed = await item_claim.claim(runtime, tenant, job_id, generation, item_id)
            if claimed is None:
                raise _Skip
            held.append(claimed)
            item, token = claimed
            dup = item_claim.duplicate
            if item.external_id is not None and await dup(runtime, tenant, job, coll, item, token):
                raise _Skip
        return item.attempts

    try:
        data, attempts = await fetch_with_retries(url, limiter, settings, 0, before=claim_in_slot)
    except _Skip:
        return bool(held)
    except Fail as failed:
        ((item, token),) = held
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
        return True
    except Defer as deferred:
        ((item, token),) = held
        async with db_lock:
            args = (deferred.code, deferred.attempts, deferred.delay)
            await item_claim.defer(runtime, tenant, job, item.id, token, *args)
        return True
    ((item, token),) = held
    async with db_lock:
        await settle.settle_bytes(
            runtime,
            tenant,
            job_id,
            generation,
            coll,
            item.id,
            data,
            filename=url_filename(url),
            meta=settle.item_meta(item),
            auto_run=auto_run,
            attempts=attempts,
            token=token,
        )
    return True


async def _pending(runtime, tenant, job_id, ids) -> list[tuple[int, str]]:
    """``(id, url)`` of the batch's items still ``pending`` - read, not claimed."""
    stmt = (
        select(ImportItem.id, ImportItem.url)
        .where(
            ImportItem.id.in_(ids),
            ImportItem.tenant_id == tenant,
            ImportItem.job_id == job_id,
            ImportItem.status == ItemStatus.PENDING,
            ImportItem.url.is_not(None),
        )
        .order_by(ImportItem.id)
    )
    async with runtime.session_factory() as db:
        rows = [(row[0], row[1]) for row in (await db.execute(stmt)).all()]
        await finalize_session(db)
    return rows


async def _run(runtime, tenant, job_id, generation, ids) -> int:
    async with runtime.session_factory() as db:
        stmt = select(ImportJob.collection_id, ImportJob.auto_run_prompts).where(
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
    items = await _pending(runtime, tenant, job_id, ids)
    db_lock = asyncio.Lock()
    job = (job_id, generation)
    auto = bool(job_row[1])
    # A fetch settles nothing for up to ``download_timeout`` per attempt: beat
    # meanwhile, or reconcile would take a healthy job for a dead one.
    async with beating(runtime, tenant, job_id, generation):
        results = await asyncio.gather(
            *(
                _one(runtime, tenant, job, coll, p, limiter, settings, db_lock, auto_run=auto)
                for p in items
            ),
            return_exceptions=True,
        )
    held = 0
    for result in results:
        if isinstance(result, BaseException):
            logger.warning("images.import.download_failed job=%s", job_id, exc_info=result)
        held += result is True
    await terminal.try_complete(runtime, tenant, job_id, generation)
    return held


async def download_items_async(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int, ids: list[int]
) -> int:
    """Download and settle the items ``ids`` of job ``job_id`` for a runner of
    ``generation``; returns how many this call held."""
    with tenant_context(tenant), bind_runtime(runtime):
        return await _run(runtime, tenant, job_id, generation, ids)
