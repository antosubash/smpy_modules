"""``images.import_geojson(job_id, generation)``'s body: stage, stream, record, work.

1. **Fence.** :func:`jobs.start` takes the job only for the runner holding its
   current ``generation``; a message from before a restart, resume or reclaim
   answers ``stale`` and writes nothing.
2. **Stage** (source URL only): fetch through ``safe_stream`` into a spool,
   validate and count it, store it, record key and count.
3. **Stream** from the resume index, one feature at a time, buffering at most
   :data:`CHUNK` features (or :data:`CHUNK_BYTES` of base64) - each buffer is
   recorded and checkpointed in one transaction (:mod:`.chunk`), then worked:
   base64 items are ingested inline, an item that already has an image
   skipped; URL items are handed to ``images.download_items`` once fewer than
   :data:`CEILING` items of the job are pending (backpressure, heartbeating
   while it waits, bounded by :data:`CAPACITY_WAIT_SECONDS`).
4. **Complete** when everything is recorded and settled (:mod:`.terminal`).

Permanent problems with the source (bad JSON, too many features, an unsafe or
failing URL) fail the job with a code; anything else (storage or database
trouble) propagates, leaving the job for reconcile to reclaim once its
heartbeat is stale. ``auto_run_prompts`` is stored on the job for the prompts
that arrive with Task 22; the collection's pipeline runs for every imported
image through ingest's own dispatch.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import IO, Final

import httpx
from simple_module_db import finalize_session, tenant_context
from sqlalchemy import or_, update

from sm_images.imports import chunk, jobs, launch, lookup, settle, staging, terminal
from sm_images.imports.beat import beating
from sm_images.imports.errors import FetchError
from sm_images.imports.features import Parsed, extract
from sm_images.imports.geojson_stream import GeoJSONError, Oversize, Tick, iter_features
from sm_images.imports.mapping import Mapping
from sm_images.imports.url_safety import UnsafeURLError
from sm_images.intents import clear_intents
from sm_images.models import ImportItem, ImportJob
from sm_images.models.enums import ImportKind, ItemStatus, JobStatus
from sm_images.pipeline.runtime import Runtime, bind_runtime

__all__ = ["CAPACITY_WAIT_SECONDS", "CEILING", "CHUNK", "CHUNK_BYTES", "import_geojson_async"]

logger = logging.getLogger(__name__)

CHUNK: Final = 1000
CHUNK_BYTES: Final = 64 * 1024 * 1024
CEILING: Final = 5000
"""Most pending items one job may have queued before the runner waits."""
POLL_SECONDS: Final = 5.0
CAPACITY_WAIT_SECONDS: Final = 1800.0
"""Longest one capacity wait lasts before the runner proceeds anyway."""

HAND_OUT: Final = 1000
"""Pending items handed out per page when a run starts."""

_sleep = asyncio.sleep


def _permanent(exc: BaseException) -> str | None:
    if isinstance(exc, GeoJSONError | FetchError):
        return exc.code
    if isinstance(exc, UnsafeURLError):
        return "unsafe_source_url"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"source_http_{exc.response.status_code}"
    if isinstance(exc, httpx.TransportError):
        return "source_unreachable"
    return None


async def _stage(
    runtime: Runtime, tenant: str, job: jobs.JobSnap
) -> tuple[IO[bytes], jobs.JobSnap]:
    """Fetch, count and store a URL source; the job moves to ``running``."""
    settings = runtime.settings()

    async def beat() -> None:
        if not await jobs.heartbeat(runtime, tenant, job.id, job.generation):
            raise chunk.Stopped()

    assert job.source_url is not None
    source = await staging.fetch_source(
        job.source_url, max_bytes=settings.geojson_max_bytes, beat=beat
    )
    try:

        def beat_now():
            return beating(runtime, tenant, job.id, job.generation)

        async with beat_now():  # counting makes no database call
            total = await staging.count(source, settings.geojson_max_features)
        key = await staging.put_spool(
            runtime, tenant, job.id, source, job.generation, during=beat_now
        )
        async with runtime.session_factory() as db:
            stmt = (
                update(ImportJob)
                .where(
                    *jobs.where(tenant, job.id),
                    ImportJob.generation == job.generation,
                    ImportJob.status == JobStatus.STAGING,
                )
                .values(
                    source_key=key,
                    staged_keys=[key],
                    total_count=total,
                    checkpoint_index=0,
                    status=JobStatus.RUNNING,
                    heartbeat_at=jobs.now(),
                    updated_at=jobs.now(),
                )
                .returning(ImportJob.id)
                .execution_options(**jobs.SYNC)
            )
            if (await db.execute(stmt)).first() is None:
                await db.rollback()
                # A newer generation staged (or will stage) its own key; this
                # attempt's object stays behind its intent for the janitor.
                raise chunk.Stopped()
            await clear_intents(db, [key])
            await finalize_session(db)
    except BaseException:
        source.close()
        raise
    return source, jobs.JobSnap(
        **{**job.__dict__, "source_key": key, "total_count": total, "status": JobStatus.RUNNING}
    )


async def _hand_out_pending(runtime: Runtime, tenant: str, job: jobs.JobSnap, below: int) -> None:
    """A URL run hands out the items already recorded and still pending - a
    resume, a retry, a reclaim after a crash - for its own generation. Claims
    taken under an *older* generation are released first - whoever holds them
    can no longer settle (the generation fence) - in a transaction fenced on
    this run's generation still being current, so a delayed old run never
    releases the claims of the run that replaced it."""
    async with runtime.session_factory() as db:
        if not await jobs.bump(db, tenant, job.id, {}, job.generation):
            await db.rollback()  # a newer generation owns the job: touch nothing
            raise chunk.Stopped()
        release = (
            update(ImportItem)
            .where(
                ImportItem.job_id == job.id,
                ImportItem.tenant_id == tenant,
                ImportItem.status == ItemStatus.PENDING,
                ImportItem.claim_token.is_not(None),
                or_(
                    ImportItem.claim_generation.is_(None),
                    ImportItem.claim_generation < job.generation,
                ),
            )
            .values(claim_token=None, claim_expires_at=None, claim_generation=None)
            .execution_options(**jobs.SYNC)
        )
        await db.execute(release)
        await finalize_session(db)
    after = -1
    while True:
        page = await chunk.pending_items(runtime, tenant, job.id, after + 1, below - 1, HAND_OUT)
        if not page:
            return
        await _wait_for_capacity(runtime, tenant, job)
        await launch.launch_downloads(runtime, tenant, job.id, job.generation, [i for i, _ in page])
        after = page[-1][1]


async def _wait_for_capacity(runtime: Runtime, tenant: str, job: jobs.JobSnap) -> None:
    if runtime.is_eager():
        return
    waited = 0.0
    while await jobs.pending_count(runtime, tenant, job.id) > CEILING:
        if waited >= CAPACITY_WAIT_SECONDS:
            logger.warning("images.import.capacity_wait_timeout job=%s", job.id)
            return  # deliberate: CEILING is soft backpressure, never a stall
        if not await jobs.heartbeat(runtime, tenant, job.id, job.generation):
            raise chunk.Stopped()
        await _sleep(POLL_SECONDS)
        waited += POLL_SECONDS


async def _work(runtime: Runtime, tenant: str, job: jobs.JobSnap, coll, buf: list[Parsed]) -> None:
    await chunk.record_chunk(runtime, tenant, job, buf)
    if job.kind is ImportKind.GEOJSON_BASE64:
        await settle.ingest_chunk(runtime, tenant, job, coll, buf)
        return
    pending = await chunk.pending_items(runtime, tenant, job.id, buf[0].index, buf[-1].index)
    if pending:
        await _wait_for_capacity(runtime, tenant, job)
        ids = [i for i, _ in pending]
        await launch.launch_downloads(runtime, tenant, job.id, job.generation, ids)


async def _stream(
    runtime: Runtime, tenant: str, job: jobs.JobSnap, coll, source: IO[bytes], start: int
) -> None:
    mapping = Mapping.model_validate(job.mapping)
    roles = list(coll.group_roles or [])
    buf: list[Parsed] = []
    size = 0
    limit = runtime.settings().geojson_max_feature_bytes
    for index, feature in iter_features(source, start, limit):
        if isinstance(feature, Tick):
            if not await jobs.heartbeat(runtime, tenant, job.id, job.generation):
                raise chunk.Stopped()
            continue
        if isinstance(feature, Oversize):
            parsed = Parsed(index, error="feature_too_large")
        else:
            parsed = extract(
                feature, index, kind=job.kind, mapping=mapping, job_id=job.id, roles=roles
            )
        buf.append(parsed)
        size += parsed.size
        if len(buf) >= CHUNK or size >= CHUNK_BYTES:
            await _work(runtime, tenant, job, coll, buf)
            buf, size = [], 0
    if buf:
        await _work(runtime, tenant, job, coll, buf)


async def _run(runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int) -> str:
    job = await jobs.start(runtime, tenant, job_id, generation)
    if job is None:
        return "stale"
    coll = await lookup.live_collection(runtime, tenant, job.collection_id)
    if coll is None or job.kind not in (ImportKind.GEOJSON_URL, ImportKind.GEOJSON_BASE64):
        await terminal.finish(runtime, tenant, job_id, generation, JobStatus.CANCELLED)
        return "cancelled"
    source: IO[bytes] | None = None
    try:
        if job.status is JobStatus.STAGING:
            source, job = await _stage(runtime, tenant, job)
        start = await lookup.resume_index(runtime, tenant, job)
        if job.kind is ImportKind.GEOJSON_URL:
            await _hand_out_pending(runtime, tenant, job, start)
        if start < job.total_count:
            assert job.source_key is not None
            if source is None:
                async with beating(runtime, tenant, job.id, job.generation) as beat:
                    source = await staging.open_source(runtime, job.source_key)
                if beat.lost:
                    raise chunk.Stopped()
            await _stream(runtime, tenant, job, coll, source, start)
    except chunk.Stopped:
        return "stopped"
    except Exception as exc:
        code = _permanent(exc)
        if code is None:
            raise
        logger.info("images.import.failed job=%s code=%s", job_id, code)
        await terminal.fail(runtime, tenant, job_id, generation, code)
        return "failed"
    finally:
        if source is not None:
            source.close()
    if await terminal.try_complete(runtime, tenant, job_id, generation):
        return "completed"
    # A download may have completed it already (eager mode settles them inline).
    async with runtime.session_factory() as db:
        row = await jobs.load(db, tenant, job_id)
        status = None if row is None else row.status
        await finalize_session(db)
    return "completed" if status is JobStatus.COMPLETED else "running"


async def import_geojson_async(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int
) -> str:
    """Run (or resume) the job; returns ``completed``, ``running`` (downloads
    still pending), ``stopped``, ``stale``, ``failed`` or ``cancelled``."""
    with tenant_context(tenant), bind_runtime(runtime):
        return await _run(runtime, tenant, job_id, generation)
