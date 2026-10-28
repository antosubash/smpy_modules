"""Recording one chunk of parsed features: :func:`record_chunk`.

**One transaction** per chunk (at most ``runner.CHUNK`` features):

1. the chunk's groups are upserted (by key, per collection);
2. each feature is classified - unusable (``failed``), seen earlier in this job
   (dedupe layer 1, ``duplicate``), already an image of this collection from
   this source, trashed ones included (layer 2, ``duplicate`` with its id), or
   ``pending`` work;
3. its items are inserted ``ON CONFLICT (job_id, feature_index) DO NOTHING`` -
   a replay of a recorded chunk inserts nothing and so counts nothing;
4. the checkpoint advances (never backwards) together with the counters of
   what was *newly* recorded, conditional on the runner's generation and the
   job still ``running``. If that fails, nothing of the chunk is kept.

So "recorded" and "checkpointed" can never disagree. Work (a base64 ingest, a
download) happens after the commit and is found again from the rows.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from sm_images.imports.features import Parsed
from sm_images.imports.jobs import COUNTERS, JobSnap, now, where
from sm_images.ingest import dedupe
from sm_images.models import Image, ImportItem, ImportJob
from sm_images.models.enums import ItemStatus, JobStatus
from sm_images.pipeline.runtime import Runtime

__all__ = ["SOURCE", "Stopped", "advance_checkpoint", "pending_items", "record_chunk"]

SOURCE = "import"
"""``external_source`` of every imported image: one dedupe namespace per collection."""


class Stopped(Exception):  # noqa: N818 - a signal, not an error
    """The runner no longer owns the job (paused, restarted, deleted)."""


def _insert(db: Any) -> Any:
    return pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert


async def _seen_in_job(db: Any, tenant: str, job_id: uuid.UUID, ids: list[str]) -> dict[str, int]:
    """External id -> the first feature index that recorded it in this job."""
    if not ids:
        return {}
    stmt = (
        select(ImportItem.external_id, func.min(ImportItem.feature_index))
        .where(
            ImportItem.job_id == job_id,
            ImportItem.tenant_id == tenant,
            ImportItem.external_id.in_(ids),
        )
        .group_by(ImportItem.external_id)
    )
    return dict((await db.execute(stmt)).tuples().all())


async def _existing_images(
    db: Any, tenant: str, collection_id: uuid.UUID, ids: list[str]
) -> dict[str, uuid.UUID]:
    if not ids:
        return {}
    stmt = (
        select(Image.external_id, Image.id)
        .where(
            Image.collection_id == collection_id,
            Image.tenant_id == tenant,
            Image.external_source == SOURCE,
            Image.external_id.in_(ids),
        )
        .execution_options(include_deleted=True)
    )
    return dict((await db.execute(stmt)).tuples().all())


def _row(tenant: str, job_id: uuid.UUID, p: Parsed, status: ItemStatus, image_id) -> dict:
    stamp = now()
    return {
        "tenant_id": tenant,
        "created_at": stamp,
        "updated_at": stamp,
        "job_id": job_id,
        "feature_index": p.index,
        "url": p.url,
        "external_id": p.external_id,
        "status": status,
        "attempts": 0,
        "last_error": p.error,
        "lat": p.lat,
        "lng": p.lng,
        "captured_at": p.captured_at,
        "group_key": p.group_key,
        "group_role": p.group_role,
        "properties": p.properties,
        "image_id": image_id,
    }


async def _classify(db: Any, tenant: str, job: JobSnap, parsed: Sequence[Parsed]) -> list[dict]:
    usable = [p for p in parsed if p.error is None and p.external_id is not None]
    ids = list(dict.fromkeys(p.external_id for p in usable if p.external_id))
    seen = await _seen_in_job(db, tenant, job.id, ids)
    known = await _existing_images(db, tenant, job.collection_id, ids)
    rows = []
    for p in parsed:
        status, image_id = ItemStatus.PENDING, None
        if p.error is not None:
            status = ItemStatus.FAILED
        elif p.external_id in known:
            status, image_id = ItemStatus.DUPLICATE, known[p.external_id]
        elif seen.get(p.external_id, p.index) < p.index:
            status = ItemStatus.DUPLICATE
        else:
            seen[p.external_id] = min(seen.get(p.external_id, p.index), p.index)
        rows.append(_row(tenant, job.id, p, status, image_id))
    return rows


async def advance_checkpoint(
    db: Any, tenant: str, job: JobSnap, end: int, deltas: dict[ItemStatus, int]
) -> bool:
    """Checkpoint ``end`` (if further) and the new counters, for this generation only."""
    values: dict[str, Any] = {
        "checkpoint_index": case(
            (ImportJob.checkpoint_index < end, end), else_=ImportJob.checkpoint_index
        ),
        "heartbeat_at": now(),
        "updated_at": now(),
    }
    for status, n in deltas.items():
        if n and status in COUNTERS:
            values[COUNTERS[status]] = getattr(ImportJob, COUNTERS[status]) + n
    stmt = (
        update(ImportJob)
        .where(
            *where(tenant, job.id),
            ImportJob.generation == job.generation,
            ImportJob.status == JobStatus.RUNNING,
        )
        .values(**values)
        .returning(ImportJob.id)
        .execution_options(synchronize_session=False)
    )
    return (await db.execute(stmt)).first() is not None


async def record_chunk(
    runtime: Runtime, tenant: str, job: JobSnap, parsed: Sequence[Parsed]
) -> None:
    """Record ``parsed`` (consecutive features) and checkpoint past them, or
    raise :class:`Stopped` with nothing kept."""
    if not parsed:
        return
    async with runtime.session_factory() as db:
        for key in sorted({p.group_key for p in parsed if p.error is None and p.group_key}):
            await dedupe.ensure_group(db, job.collection_id, key)
        rows = await _classify(db, tenant, job, parsed)
        stmt = (
            _insert(db)(ImportItem)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["job_id", "feature_index"])
            .returning(ImportItem.feature_index)
        )
        inserted = set((await db.execute(stmt)).scalars())
        deltas: dict[ItemStatus, int] = {}
        for row in rows:
            if row["feature_index"] in inserted and row["status"] is not ItemStatus.PENDING:
                deltas[row["status"]] = deltas.get(row["status"], 0) + 1
        if not await advance_checkpoint(db, tenant, job, parsed[-1].index + 1, deltas):
            await db.rollback()
            raise Stopped()
        await finalize_session(db)


async def pending_items(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, first: int, last: int
) -> list[tuple[int, int]]:
    """``(item id, feature index)`` of the items in ``[first, last]`` still
    waiting for work (pending and without an image)."""
    stmt = (
        select(ImportItem.id, ImportItem.feature_index)
        .where(
            ImportItem.job_id == job_id,
            ImportItem.tenant_id == tenant,
            ImportItem.feature_index.between(first, last),
            ImportItem.status == ItemStatus.PENDING,
            ImportItem.image_id.is_(None),
        )
        .order_by(ImportItem.feature_index)
    )
    async with runtime.session_factory() as db:
        rows = [(int(i), int(f)) for i, f in (await db.execute(stmt)).all()]
        await finalize_session(db)
    return rows
