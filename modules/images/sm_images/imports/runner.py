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
from sqlalchemy import update

from sm_images.imports import chunk, jobs, launch, settle, staging, terminal
from sm_images.imports.errors import FetchError
from sm_images.imports.features import Parsed, extract
from sm_images.imports.geojson_stream import GeoJSONError, Tick, iter_features
from sm_images.imports.mapping import Mapping
from sm_images.imports.url_safety import UnsafeURLError
from sm_images.intents import clear_intents
from sm_images.models import ImportJob
from sm_images.models.enums import ImportKind, JobStatus
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
        total = await staging.count(source, settings.geojson_max_features)
        key = await staging.put_spool(runtime, tenant, job.id, source)
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
                .execution_options(synchronize_session=False)
            )
            if (await db.execute(stmt)).first() is None:
                await db.rollback()
                raise chunk.Stopped()  # the intent stays: the janitor reaps the object
            await clear_intents(db, [key])
            await finalize_session(db)
    except BaseException:
        source.close()
        raise
    return source, jobs.JobSnap(
        **{**job.__dict__, "source_key": key, "total_count": total, "status": JobStatus.RUNNING}
    )


async def _wait_for_capacity(runtime: Runtime, tenant: str, job: jobs.JobSnap) -> None:
    if runtime.is_eager():
        return
    waited = 0.0
    while await jobs.pending_count(runtime, tenant, job.id) > CEILING:
        if waited >= CAPACITY_WAIT_SECONDS:
            logger.warning("images.import.capacity_wait_timeout job=%s", job.id)
            return
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
        await launch.launch_downloads(runtime, tenant, job.id, [i for i, _ in pending])


async def _stream(
    runtime: Runtime, tenant: str, job: jobs.JobSnap, coll, source: IO[bytes], start: int
) -> None:
    mapping = Mapping.model_validate(job.mapping)
    roles = list(coll.group_roles or [])
    buf: list[Parsed] = []
    size = 0
    for index, feature in iter_features(source, start):
        if isinstance(feature, Tick):
            if not await jobs.heartbeat(runtime, tenant, job.id, job.generation):
                raise chunk.Stopped()
            continue
        parsed = extract(feature, index, kind=job.kind, mapping=mapping, job_id=job.id, roles=roles)
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
    coll = await jobs.live_collection(runtime, tenant, job.collection_id)
    if coll is None or job.kind not in (ImportKind.GEOJSON_URL, ImportKind.GEOJSON_BASE64):
        await terminal.finish(runtime, tenant, job_id, generation, JobStatus.CANCELLED)
        return "cancelled"
    source: IO[bytes] | None = None
    try:
        if job.source_key is None:
            source, job = await _stage(runtime, tenant, job)
        start = await jobs.resume_index(runtime, tenant, job)
        if start < job.total_count:
            assert job.source_key is not None
            source = source or await staging.open_source(runtime, job.source_key)
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
    if await terminal.try_complete(runtime, tenant, job_id):
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
