"""``images.download_items(job_id, ids)``'s body: fetch and settle URL items.

Per item, with no transaction open while the network is used:

1. **Load** it: gone (a restart deleted it), settled, or its job not
   ``running`` (paused, finished) - stop, touching nothing. A message that
   says when it was sent (``dispatched_at``) also stops if the item was handed
   out again since, so reconcile's re-dispatch and a late original never both
   download it.
2. **Dedupe** (layer 3, before any byte moves): an image of this collection
   with the item's external id, trashed or not, makes it a duplicate.
3. **Fetch** with ``safe_stream`` (``max_image_bytes``, ``download_timeout``)
   inside a :class:`DomainLimiter` slot. Retryable failures - a transport
   error, the deadline, 408/429/5xx - are retried with :func:`backoff`; a wait
   longer than :data:`INLINE_WAIT_SECONDS`, or ``None`` (the server asked for
   more than we wait), defers the item: it stays ``pending`` for reconcile.
   Permanent ones - an unsafe URL, too large, a content encoding, any other
   4xx, a protocol error - fail it at once. :data:`MAX_ATTEMPTS` caps a
   deferred item's lifetime.
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
from datetime import datetime
from typing import Any, Final

import httpx
from simple_module_db import finalize_session, tenant_context
from sqlalchemy import select, update

from sm_images.imports import jobs, settle, terminal
from sm_images.imports.chunk import SOURCE
from sm_images.imports.errors import FetchError, FetchTimeoutError
from sm_images.imports.features import url_filename
from sm_images.imports.fetch import safe_stream
from sm_images.imports.jobs import live_collection, now
from sm_images.imports.rate_limit import DomainLimiter, backoff, is_retryable_status
from sm_images.imports.url_safety import UnsafeURLError
from sm_images.ingest import dedupe
from sm_images.models import ImportItem, ImportJob
from sm_images.models.enums import ItemStatus, JobStatus
from sm_images.pipeline.runtime import Runtime, bind_runtime

__all__ = ["INLINE_ATTEMPTS", "INLINE_WAIT_SECONDS", "MAX_ATTEMPTS", "download_items_async"]

logger = logging.getLogger(__name__)

INLINE_ATTEMPTS: Final = 3
INLINE_WAIT_SECONDS: Final = 30.0
MAX_ATTEMPTS: Final = 8
_sleep = asyncio.sleep


class _Stop(Exception):  # noqa: N818 - a signal
    def __init__(self, code: str, attempts: int) -> None:
        super().__init__(code)
        self.code = code
        self.attempts = attempts


class _Defer(_Stop):
    """Retry later (reconcile re-dispatches the pending item)."""


class _Fail(_Stop):
    """Permanent: the item fails."""


def _classify(exc: BaseException) -> tuple[bool, str, httpx.Response | None]:
    """``(retryable, code, response)`` for a failed fetch."""
    if isinstance(exc, UnsafeURLError):
        return False, "unsafe_url", None
    if isinstance(exc, FetchTimeoutError):
        return True, "timeout", None
    if isinstance(exc, FetchError):
        return False, exc.code, None
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return is_retryable_status(status), f"http_{status}", exc.response
    if isinstance(exc, httpx.RemoteProtocolError):
        return False, "protocol_error", None  # a broken redirect or framing: one try
    if isinstance(exc, httpx.TransportError):
        return True, "transport_error", None
    # Anything else is a fault nobody can retry away; failing the item keeps
    # reconcile from re-sending it forever.
    logger.warning("images.import.fetch_unexpected", exc_info=exc)
    return False, "fetch_failed", None


async def _fetch(url: str, settings: Any) -> bytes:
    parts = [
        c
        async for c in safe_stream(
            url, max_bytes=settings.max_image_bytes, timeout=settings.download_timeout
        )
    ]
    return b"".join(parts)


async def _download(
    url: str, limiter: DomainLimiter, settings: Any, prior: int
) -> tuple[bytes, int]:
    """The body, and how many attempts it took; raises ``_Fail`` or ``_Defer``."""
    for attempt in range(INLINE_ATTEMPTS):
        try:
            async with limiter.slot(url):
                return await _fetch(url, settings), attempt + 1
        except Exception as exc:
            retryable, code, response = _classify(exc)
            made = attempt + 1
            if not retryable or prior + made >= MAX_ATTEMPTS:
                raise _Fail(code, made) from exc
            wait = backoff(response, prior + attempt)
            if wait is None or wait > INLINE_WAIT_SECONDS or made == INLINE_ATTEMPTS:
                raise _Defer(code, made) from exc
            await _sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover


async def _claim(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, item_id: int, dispatched_at: datetime | None
) -> ImportItem | None:
    """The pending item of a running job, stamped as taken now; ``None`` to skip it."""
    conds = [
        ImportItem.id == item_id,
        ImportItem.tenant_id == tenant,
        ImportItem.job_id == job_id,
        ImportItem.status == ItemStatus.PENDING,
    ]
    if dispatched_at is not None:
        conds.append(ImportItem.updated_at <= dispatched_at)
    running = select(ImportJob.id).where(
        ImportJob.id == job_id, ImportJob.tenant_id == tenant, ImportJob.status == JobStatus.RUNNING
    )
    stmt = (
        update(ImportItem)
        .where(*conds, ImportItem.job_id.in_(running.scalar_subquery()))
        .values(updated_at=now())
        .returning(ImportItem.id)
        .execution_options(synchronize_session=False)
    )
    async with runtime.session_factory() as db:
        taken = (await db.execute(stmt)).first() is not None
        row = None
        if taken:
            stmt2 = select(ImportItem).where(
                ImportItem.id == item_id, ImportItem.tenant_id == tenant
            )
            row = (await db.execute(stmt2)).scalar_one()
        await finalize_session(db)
    return row


async def _defer(runtime: Runtime, tenant: str, item_id: int, code: str, attempts: int) -> None:
    async with runtime.session_factory() as db:
        await db.execute(
            update(ImportItem)
            .where(
                ImportItem.id == item_id,
                ImportItem.tenant_id == tenant,
                ImportItem.status == ItemStatus.PENDING,
            )
            .values(attempts=ImportItem.attempts + attempts, last_error=code, updated_at=now())
            .execution_options(synchronize_session=False)
        )
        await finalize_session(db)


async def _duplicate(runtime: Runtime, tenant: str, job_id: uuid.UUID, coll, item) -> bool:
    """Layer 3, before any byte moves: settle as a duplicate of an existing image."""
    async with runtime.session_factory() as db:
        dup = await dedupe.find_external(db, coll.id, SOURCE, item.external_id)
        if dup is not None and await settle.mark_item(
            db, tenant, item.id, ItemStatus.DUPLICATE, image_id=dup
        ):
            await jobs.bump(db, tenant, job_id, {ItemStatus.DUPLICATE: 1})
        await finalize_session(db)
    return dup is not None


async def _one(runtime, tenant, job_id, coll, item: ImportItem, limiter, settings, db_lock) -> None:
    """One item. Its database phases hold ``db_lock`` (one transaction at a time
    per batch - short ones); the fetch runs outside it, concurrently."""
    if item.external_id is not None:
        async with db_lock:
            if await _duplicate(runtime, tenant, job_id, coll, item):
                return
    assert item.url is not None
    try:
        data, attempts = await _download(item.url, limiter, settings, item.attempts)
    except _Fail as failed:
        async with db_lock:
            await settle.fail_item(
                runtime, tenant, job_id, item.id, failed.code, attempts=failed.attempts
            )
        return
    except _Defer as deferred:
        async with db_lock:
            await _defer(runtime, tenant, item.id, deferred.code, deferred.attempts)
        return
    async with db_lock:
        await settle.settle_bytes(
            runtime,
            tenant,
            job_id,
            coll,
            item.id,
            data,
            filename=url_filename(item.url),
            meta=settle.item_meta(item),
            attempts=attempts,
        )


async def _run(runtime, tenant, job_id, ids, dispatched_at) -> int:
    async with runtime.session_factory() as db:
        job_row = (
            await db.execute(
                select(ImportJob.collection_id).where(
                    ImportJob.id == job_id, ImportJob.tenant_id == tenant
                )
            )
        ).first()
        await finalize_session(db)
    if job_row is None:
        return 0
    coll = await live_collection(runtime, tenant, job_row[0])
    if coll is None:
        return 0
    settings = runtime.settings()
    limiter = DomainLimiter(
        settings.download_concurrency_per_domain, settings.download_concurrency_total
    )
    items = [i for i in [await _claim(runtime, tenant, job_id, x, dispatched_at) for x in ids] if i]
    db_lock = asyncio.Lock()
    results = await asyncio.gather(
        *(_one(runtime, tenant, job_id, coll, item, limiter, settings, db_lock) for item in items),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, BaseException):
            logger.warning("images.import.download_failed job=%s", job_id, exc_info=result)
    await terminal.try_complete(runtime, tenant, job_id)
    return len(items)


async def download_items_async(
    runtime: Runtime,
    tenant: str,
    job_id: uuid.UUID,
    ids: list[int],
    dispatched_at: datetime | None = None,
) -> int:
    """Download and settle the items ``ids`` of job ``job_id``; returns how
    many this call took on."""
    with tenant_context(tenant), bind_runtime(runtime):
        return await _run(runtime, tenant, job_id, ids, dispatched_at)
