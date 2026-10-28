"""The janitor's purge (spec §7 "Purge"): trashed rows past the grace period.

Runs in the caller's session under the bound tenant (the janitor binds each in
turn). One pass:

1. **Lock.** Collections soft-deleted before the cutoff, then images - every
   image of such a collection (trashed or not), and images trashed on their
   own - are selected ``FOR UPDATE SKIP LOCKED``: a step completing on one
   holds its lock, so the purge skips it this pass instead of racing it, and
   a completion arriving later finds no row and drops its staged objects.
   ``cap`` bounds the rows of one pass; a collection is removed only in the
   pass that takes its last image.
2. **Collect** every key: the original, the current display copy and
   renditions from the rows, upload sessions, a collection's map and its
   import jobs' staging - and, from the write-ahead intents under each
   image's (and purged collection's) prefix, every *replaced* display
   generation and rendition whose after-commit delete failed, and anything a
   crashed worker staged. A key a surviving row still references is kept.
3. **Delete the keys, then the rows** (children first), then the intents, and
   release the images' storage holds (:mod:`sm_images.billing`). Keys go first:
   a failed delete raises before any row is touched, so the next pass retries
   with the rows still there to say what to delete. The caller commits.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, or_, select, update

from sm_images import billing, storage_keys
from sm_images.models import (
    Collection,
    Group,
    Image,
    ImportItem,
    ImportJob,
    ObjectIntent,
    PipelineRestart,
    Prompt,
    PromptResult,
    Rendition,
    StepRun,
    UploadSession,
    UploadStatus,
)

__all__ = ["PurgeReport", "purge_expired"]

_CHUNK = 500
_SYNC = {"synchronize_session": False}
_LIVE_UPLOADS = (UploadStatus.OPEN, UploadStatus.COMPLETING)


@dataclass
class PurgeReport:
    dry_run: bool
    collections: list[uuid.UUID] = field(default_factory=list)
    images: list[uuid.UUID] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    """Deleted (or, on a dry run, that would be)."""
    kept: list[str] = field(default_factory=list)
    """Collected but still referenced by a surviving row: never deleted."""


def _chunks[T](items: Iterable[T], n: int = _CHUNK) -> Iterator[list[T]]:
    batch = list(items)
    for i in range(0, len(batch), n):
        yield batch[i : i + n]


def _locked(stmt: Any) -> Any:
    return stmt.execution_options(include_deleted=True).with_for_update(skip_locked=True)


async def _scalars(db: Any, stmt: Any) -> list[Any]:
    return list((await db.execute(stmt)).scalars())


async def _pick(db: Any, cutoff: datetime, cap: int) -> tuple[list[Image], list[Collection]]:
    """The rows of this pass: whole collections and the images to purge."""
    colls = await _scalars(
        db,
        _locked(
            select(Collection)
            .where(Collection.is_deleted.is_(True), Collection.deleted_at <= cutoff)
            .order_by(Collection.deleted_at, Collection.id)
            .limit(cap)
        ),
    )
    budget, images, whole = cap, [], []
    for coll in colls:
        if budget <= 0:
            break
        stmt = select(Image).where(Image.collection_id == coll.id).order_by(Image.id)
        rows = await _scalars(db, _locked(stmt.limit(budget + 1)))
        if len(rows) < budget:  # all of them, and the collection row too
            images += rows
            whole.append(coll)
            budget -= len(rows) + 1
        else:
            images += rows[:budget]
            budget = 0
    if budget > 0:
        stmt = select(Image).where(Image.is_deleted.is_(True), Image.deleted_at <= cutoff)
        if colls:
            stmt = stmt.where(Image.collection_id.not_in([c.id for c in colls]))
        images += await _scalars(
            db, _locked(stmt.order_by(Image.deleted_at, Image.id).limit(budget))
        )
    return images, whole


async def _intent_keys(db: Any, prefixes: Iterable[str]) -> set[str]:
    found: set[str] = set()
    for chunk in _chunks(sorted(set(prefixes)), 100):
        match = or_(*[ObjectIntent.key.startswith(p, autoescape=True) for p in chunk])
        found.update(await _scalars(db, select(ObjectIntent.key).where(match)))
    return found


async def _keys(db: Any, images: list[Image], whole: list[Collection]) -> set[str]:
    keys = {i.storage_key for i in images} | {i.display_key for i in images if i.display_key}
    prefixes = {
        storage_keys.image_prefix(i.tenant_id, str(i.collection_id), str(i.id)) for i in images
    }
    for chunk in _chunks([i.id for i in images]):
        keys.update(
            await _scalars(db, select(Rendition.storage_key).where(Rendition.image_id.in_(chunk)))
        )
        keys.update(
            await _scalars(
                db, select(UploadSession.storage_key).where(UploadSession.image_id.in_(chunk))
            )
        )
    whole_ids = [c.id for c in whole]
    for coll in whole:
        keys.add(storage_keys.map_key(coll.tenant_id, str(coll.id)))
        prefixes.add(storage_keys.collection_prefix(coll.tenant_id, str(coll.id)))
    if whole_ids:
        sessions = select(UploadSession.storage_key).where(
            UploadSession.collection_id.in_(whole_ids)
        )
        keys.update(await _scalars(db, sessions))
        jobs = await _scalars(db, select(ImportJob).where(ImportJob.collection_id.in_(whole_ids)))
        for job in jobs:
            keys.update(k for k in [job.source_key, *(job.staged_keys or [])] if k)
            prefixes.add(storage_keys.import_prefix(job.tenant_id, str(job.id)))
    return keys | await _intent_keys(db, prefixes)


async def _referenced(
    db: Any, keys: set[str], image_ids: list[uuid.UUID], whole_ids: list[uuid.UUID]
) -> set[str]:
    """The keys a row that survives this pass still points at."""
    found: set[str] = set()
    for chunk in _chunks(sorted(keys)):
        images = (
            select(Image.storage_key, Image.display_key)
            .where(
                or_(Image.storage_key.in_(chunk), Image.display_key.in_(chunk)),
                Image.id.not_in(image_ids),
            )
            .execution_options(include_deleted=True)
        )
        for original, display in (await db.execute(images)).all():
            found.update(k for k in (original, display) if k in chunk)
        renditions = select(Rendition.storage_key).where(
            Rendition.storage_key.in_(chunk), Rendition.image_id.not_in(image_ids)
        )
        found.update(await _scalars(db, renditions))
        uploads = select(UploadSession.storage_key).where(
            UploadSession.storage_key.in_(chunk),
            UploadSession.status.in_(_LIVE_UPLOADS),
            UploadSession.image_id.not_in(image_ids),
            UploadSession.collection_id.not_in(whole_ids),
        )
        found.update(await _scalars(db, uploads))
    return found


async def _delete_rows(
    db: Any, image_ids: list[uuid.UUID], whole_ids: list[uuid.UUID], keys: list[str]
) -> None:
    async def run(stmt: Any) -> None:
        await db.execute(stmt.execution_options(**_SYNC))

    for chunk in _chunks(image_ids):
        await run(update(ImportItem).where(ImportItem.image_id.in_(chunk)).values(image_id=None))
        for model in (StepRun, Rendition, PromptResult, UploadSession):
            await run(delete(model).where(model.image_id.in_(chunk)))
        await run(delete(Image).where(Image.id.in_(chunk)))
    if whole_ids:
        prompts = select(Prompt.id).where(Prompt.collection_id.in_(whole_ids))
        groups = select(Group.id).where(Group.collection_id.in_(whole_ids))
        jobs = select(ImportJob.id).where(ImportJob.collection_id.in_(whole_ids))
        await run(
            delete(PromptResult).where(
                or_(PromptResult.prompt_id.in_(prompts), PromptResult.group_id.in_(groups))
            )
        )
        await run(delete(ImportItem).where(ImportItem.job_id.in_(jobs)))
        for model in (Prompt, Group, ImportJob, PipelineRestart, UploadSession):
            await run(delete(model).where(model.collection_id.in_(whole_ids)))
        await run(delete(Collection).where(Collection.id.in_(whole_ids)))
    for chunk in _chunks(keys):
        await run(delete(ObjectIntent).where(ObjectIntent.key.in_(chunk)))


async def purge_expired(
    db: Any,
    store: Any,
    *,
    now: datetime,
    grace_days: int,
    dry_run: bool = False,
    cap: int = 1000,
) -> PurgeReport:
    """Hard-delete what was trashed more than ``grace_days`` before ``now``."""
    images, whole = await _pick(db, now - timedelta(days=grace_days), cap)
    report = PurgeReport(dry_run, [c.id for c in whole], [i.id for i in images])
    if not images and not whole:
        return report
    keys = await _keys(db, images, whole)
    kept = await _referenced(db, keys, report.images, report.collections)
    report.keys, report.kept = sorted(keys - kept), sorted(kept)
    if dry_run:
        await db.rollback()  # nothing changed; let the row locks go
        return report
    holds = [(i.id, i.storage_hold_id, i.storage_bytes) for i in images]
    await store.delete_keys(report.keys)
    await _delete_rows(db, report.images, report.collections, report.keys)
    await billing.release_storage(db, holds)
    return report
