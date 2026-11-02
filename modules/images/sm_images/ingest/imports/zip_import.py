"""Running a sealed ZIP import: :func:`import_zip_async` (and :func:`run_import`,
which picks the runner for a job's kind).

1. **Fence.** :func:`jobs.start` takes the job only for the runner holding its
   current ``generation``; a stale message writes nothing.
2. **Fetch, verified** (``zip_source``) into a temporary directory - the
   sealed size and fingerprint must still hold - and **inspect**
   (``zip_safety``) off the event loop, both under a background heartbeat. A
   refusal fails the job with its code before any item exists.
3. **Record and settle** in chunks of :data:`ENTRY_BATCH` entries, from the resume
   index (the first item still waiting for an image): each chunk's items are
   recorded and checkpointed in one transaction (``chunk.record_chunk``),
   then each pending one is read (at most ``max_image_bytes``) and settled
   through ingest - its image, its item and the fenced counter in one
   transaction (``settle.settle_bytes``). A settlement that loses makes the
   runner check it still owns the job, so a pause or restart stops it at the
   next entry, not after the archive.
4. **Complete** when every entry is settled (``terminal.try_complete``).
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
import zipfile
import zlib
from pathlib import Path
from typing import Any, Final

from simple_module_db import finalize_session, tenant_context
from sqlalchemy import select, update

from sm_images.core import constants
from sm_images.core.errors import ServiceUnavailable
from sm_images.ingest.imports import (
    access,
    chunk,
    jobs,
    launch,
    lookup,
    settle,
    terminal,
    zip_source,
)
from sm_images.ingest.imports.beat import beating
from sm_images.ingest.imports.features import Parsed
from sm_images.ingest.imports.mapping import Mapping
from sm_images.ingest.imports.runner import import_geojson_async
from sm_images.ingest.imports.zip_entries import entry_item, parse_metadata
from sm_images.ingest.imports.zip_safety import Entry, Limits, ZipRejected, inspect, read_entry
from sm_images.models import Collection, ImportJob
from sm_images.models.enums import ImportKind, JobStatus, LocationSource
from sm_images.pipeline.runtime import Runtime, bind_runtime, first_row

__all__ = ["ENTRY_BATCH", "import_zip_async", "launch_sealed", "run_import"]

logger = logging.getLogger(__name__)

ENTRY_BATCH: Final = 500
"""Entries recorded per transaction (each then settled on its own)."""


async def run_import(runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int) -> str:
    """The runner for the job's kind (``images.import_geojson`` runs every kind)."""
    with tenant_context(tenant):
        async with runtime.session_factory() as db:
            stmt = select(ImportJob.kind).where(*jobs.where(tenant, job_id))
            kind = (await db.execute(stmt)).scalar_one_or_none()
            await finalize_session(db)
    if kind is ImportKind.ZIP:
        return await import_zip_async(runtime, tenant, job_id, generation)
    return await import_geojson_async(runtime, tenant, job_id, generation)


async def launch_sealed(runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int) -> None:
    """Hand a sealed job to its runner; a refused broker fails it (503)."""
    try:
        await launch.launch_runner(runtime, tenant, job_id, generation)
    except Exception as exc:
        if runtime.is_eager():  # the work itself failed: reconcile retries it
            logger.exception("images.import.eager_zip_failed job=%s", job_id)
            return
        await terminal.fail(runtime, tenant, job_id, generation, "dispatch_failed")
        raise ServiceUnavailable("The import could not be queued") from exc


async def _sealed(runtime: Runtime, tenant: str, job_id: uuid.UUID) -> tuple[str, int]:
    stmt = select(ImportJob.source_etag, ImportJob.source_size).where(*jobs.where(tenant, job_id))
    found = await first_row(runtime, stmt)
    if found is None or found[0] is None or found[1] is None:
        raise ZipRejected("source_missing")
    return str(found[0]), int(found[1])


async def _record_total(runtime: Runtime, tenant: str, job: jobs.JobSnap, total: int) -> None:
    stmt = (
        update(ImportJob)
        .where(
            *jobs.where(tenant, job.id),
            ImportJob.generation == job.generation,
            ImportJob.status == JobStatus.RUNNING,
        )
        .values(total_count=total, heartbeat_at=jobs.now(), updated_at=jobs.now())
        .returning(ImportJob.id)
    )
    if await jobs.returning_one(runtime, stmt) is None:
        raise chunk.Stopped()


def _untrusted(parse: Any, *args: Any) -> Any:
    """Parse archive content; any failure but a refusal is still the archive's
    fault, so it fails the job (``invalid_archive``) rather than leave it
    running for reconcile to retry forever. Local I/O errors stay transient."""
    try:
        return parse(*args)
    except (ZipRejected, OSError):
        raise
    except Exception as exc:
        logger.warning("images.import.zip_unparseable", exc_info=True)
        raise ZipRejected("invalid_archive") from exc


def _item(entry: Entry, *args: Any) -> Parsed:
    """The entry's item; any failure converting its untrusted values fails that
    item alone (``invalid_metadata``) - never the run, never a retry loop."""
    try:
        return entry_item(entry, *args)
    except Exception:
        logger.warning("images.import.zip_entry_unparseable index=%s", entry.index, exc_info=True)
        return Parsed(entry.index, error="invalid_metadata", filename=entry.filename)


def _inspect(path: Path, limits: Limits) -> Any:
    return _untrusted(inspect, path, limits)


def _read(zf: zipfile.ZipFile, info: zipfile.ZipInfo, cap: int) -> bytes | str | None:
    try:
        return read_entry(zf, info, cap)
    except (zipfile.BadZipFile, zlib.error, EOFError):
        return "corrupt_entry"


async def _settle_chunk(
    runtime: Runtime,
    tenant: str,
    job: jobs.JobSnap,
    coll: Collection,
    zf: zipfile.ZipFile,
    entries: list[Entry],
    parsed: list[Parsed],
) -> None:
    infos = zf.infolist()
    cap = runtime.settings().max_image_bytes
    first = parsed[0].index
    pending = await chunk.pending_items(runtime, tenant, job.id, first, parsed[-1].index)
    for item_id, index in pending:
        p = parsed[index - first]
        data = await asyncio.to_thread(_read, zf, infos[entries[index].position], cap)
        outcome: Any
        if data is None or isinstance(data, str):
            code = data or constants.CODE_FILE_TOO_LARGE
            args = (runtime, tenant, job.id, job.generation, item_id, code)
            outcome = await settle.fail_item(*args) or None
        else:
            outcome = await settle.settle_bytes(
                runtime,
                tenant,
                job.id,
                job.generation,
                coll,
                item_id,
                data,
                filename=p.filename,
                meta=settle.item_meta(p, located_by=LocationSource.MANUAL),
                auto_run=job.auto_run_prompts,
            )
        if outcome is None and not await jobs.heartbeat(runtime, tenant, job.id, job.generation):
            raise chunk.Stopped()  # paused, restarted, reclaimed or deleted meanwhile


async def _import(
    runtime: Runtime, tenant: str, job: jobs.JobSnap, coll: Collection, tmp: Path
) -> None:
    if job.source_key is None:
        raise ZipRejected("source_missing")
    fingerprint, size = await _sealed(runtime, tenant, job.id)
    path = tmp / "archive.zip"
    limits = Limits.from_settings(runtime.settings())
    async with beating(runtime, tenant, job.id, job.generation) as beat:  # no DB calls inside
        await zip_source.fetch_verified(
            runtime.store(), job.source_key, fingerprint=fingerprint, size=size, dest=path
        )
        plan = await asyncio.to_thread(_inspect, path, limits)
    if beat.lost:
        raise chunk.Stopped()
    metadata = _untrusted(parse_metadata, plan.metadata)
    await _record_total(runtime, tenant, job, len(plan.entries))
    start = await lookup.resume_index(runtime, tenant, job)
    mapping = Mapping.model_validate(job.mapping)
    roles = list(coll.group_roles or [])
    with zipfile.ZipFile(path) as zf:
        for lo in range(start, len(plan.entries), ENTRY_BATCH):
            batch = plan.entries[lo : lo + ENTRY_BATCH]
            parsed = [_item(e, metadata, mapping, job.id, roles) for e in batch]
            await access.guard(runtime, tenant, job.id, job.generation)
            await chunk.record_chunk(runtime, tenant, job, parsed)
            await _settle_chunk(runtime, tenant, job, coll, zf, plan.entries, parsed)


async def _run(runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int) -> str:
    job = await jobs.start(runtime, tenant, job_id, generation)
    if job is None:
        return "stale"
    coll = await lookup.live_collection(runtime, tenant, job.collection_id)
    if coll is None or job.kind is not ImportKind.ZIP:
        await terminal.finish(runtime, tenant, job_id, generation, JobStatus.CANCELLED)
        return "cancelled"
    try:
        await access.guard(runtime, tenant, job_id, generation)
        with tempfile.TemporaryDirectory(prefix="sm-images-zip-") as tmp:
            await _import(runtime, tenant, job, coll, Path(tmp))
    except chunk.Stopped:
        return "stopped"
    except ZipRejected as exc:
        logger.info("images.import.zip_rejected job=%s code=%s", job_id, exc.code)
        await terminal.fail(runtime, tenant, job_id, generation, exc.code)
        return "failed"
    done = await terminal.try_complete(runtime, tenant, job_id, generation)
    return "completed" if done else "running"


async def import_zip_async(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int
) -> str:
    """Run (or resume) a sealed ZIP job; ``completed``, ``running``, ``stopped``,
    ``stale``, ``failed`` or ``cancelled``."""
    with tenant_context(tenant), bind_runtime(runtime):
        return await _run(runtime, tenant, job_id, generation)
