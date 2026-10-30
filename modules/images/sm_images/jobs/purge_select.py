"""The purge's read half: which rows one pass takes, and which keys go with them.

**Selection.** Collections soft-deleted before the cutoff, then images - every
image of such a collection (trashed or not), and images trashed on their own -
are selected ``FOR UPDATE SKIP LOCKED``. A collection is taken *whole* (its
row and its own objects: the map, import staging, upload sessions) only when
the selected images are all it has: ``SKIP LOCKED`` silently passes over an
image a step is completing on, so the pass counts the collection's images
again *without* it and leaves the collection for the next pass if any remain.
Collections and images whose purge already failed (``purge_failed_at``) come
last, so a key that will not delete cannot take the budget of every pass.

**Keys** are grouped by what owns them - each image, and each whole
collection - so the caller can delete them group by group and keep the rows
of a group whose delete failed. Intents add the replaced display generations
and renditions only the write-ahead log remembers; an intent younger than
:data:`MIN_INTENT_AGE` may be a ``stage()`` still in flight and is left to
the intent reaper. A key a surviving row references is moved to ``kept``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select

from sm_images.core.storage import keys as storage_keys
from sm_images.models import (
    Collection,
    Image,
    ImportJob,
    ObjectIntent,
    Rendition,
    UploadSession,
    UploadStatus,
)

__all__ = ["MIN_INTENT_AGE", "Keys", "Selection", "chunks", "collect_keys", "pick"]

MIN_INTENT_AGE = timedelta(days=1)
"""An intent younger than this is never acted on, whatever the grace setting
(``0`` is allowed): its writer may still be about to put the object or commit
the row."""
_CHUNK = 500
_LIVE_UPLOADS = (UploadStatus.OPEN, UploadStatus.COMPLETING)


@dataclass
class Selection:
    images: list[Image] = field(default_factory=list)
    whole: list[Collection] = field(default_factory=list)
    """Collections every one of whose images is in ``images``."""
    collections: list[Collection] = field(default_factory=list)
    """Every trashed collection this pass reached (whole or not)."""


@dataclass
class Keys:
    images: dict[uuid.UUID, set[str]] = field(default_factory=dict)
    collections: dict[uuid.UUID, set[str]] = field(default_factory=dict)
    """A whole collection's own keys (none of its images')."""
    kept: set[str] = field(default_factory=set)

    def all(self) -> set[str]:
        return set().union(*self.images.values(), *self.collections.values())


def chunks[T](items: Iterable[T], n: int = _CHUNK) -> Iterator[list[T]]:
    batch = list(items)
    for i in range(0, len(batch), n):
        yield batch[i : i + n]


def _locked(stmt: Any) -> Any:
    return stmt.execution_options(include_deleted=True).with_for_update(skip_locked=True)


async def _scalars(db: Any, stmt: Any) -> list[Any]:
    return list((await db.execute(stmt)).scalars())


def _failed_last(*order: Any) -> list[Any]:
    return [Image.purge_failed_at.asc().nulls_first(), *order]


async def _count(db: Any, collection_id: uuid.UUID) -> int:
    """Every image of the collection, locked or not (a plain read never waits)."""
    stmt = select(func.count()).select_from(Image).where(Image.collection_id == collection_id)
    return (await db.execute(stmt.execution_options(include_deleted=True))).scalar_one()


async def pick(db: Any, cutoff: datetime, cap: int) -> Selection:
    """The rows of this pass: the images to purge and the whole collections."""
    colls = await _scalars(
        db,
        _locked(
            select(Collection)
            .where(Collection.is_deleted.is_(True), Collection.deleted_at <= cutoff)
            .order_by(
                Collection.purge_failed_at.asc().nulls_first(),
                Collection.deleted_at,
                Collection.id,
            )
            .limit(cap)
        ),
    )
    out, budget = Selection(), cap
    for coll in colls:
        if budget <= 0:
            break
        out.collections.append(coll)
        stmt = select(Image).where(Image.collection_id == coll.id)
        rows = await _scalars(db, _locked(stmt.order_by(*_failed_last(Image.id)).limit(budget + 1)))
        taken = rows[:budget]
        out.images += taken
        budget -= len(taken)
        if len(rows) < budget + len(taken) and await _count(db, coll.id) == len(rows):
            out.whole.append(coll)  # nothing locked away, nothing beyond the budget
            budget -= 1
    if budget > 0:
        stmt = select(Image).where(Image.is_deleted.is_(True), Image.deleted_at <= cutoff)
        if colls:
            stmt = stmt.where(Image.collection_id.not_in([c.id for c in colls]))
        stmt = stmt.order_by(*_failed_last(Image.deleted_at, Image.id)).limit(budget)
        out.images += await _scalars(db, _locked(stmt))
    return out


def _uuid(text: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(text)
    except ValueError:
        return None


def _owner(key: str, images: set[str], jobs: dict[str, uuid.UUID]) -> tuple[str, str] | None:
    """``("image", prefix)``, ``("collection", id)`` or ``None`` for a key's group."""
    parts = key.split("/")
    if len(parts) < 4:
        return None
    if parts[2] == "imports":
        job = "/".join(parts[:4]) + "/"
        return ("collection", str(jobs[job])) if job in jobs else None
    image = "/".join(parts[:4]) + "/"
    return ("image", image) if image in images else ("collection", parts[2])


async def _intents(db: Any, prefixes: Iterable[str], before: datetime) -> list[str]:
    found: list[str] = []
    for chunk in chunks(sorted(set(prefixes)), 100):
        match = or_(*[ObjectIntent.key.startswith(p, autoescape=True) for p in chunk])
        stmt = select(ObjectIntent.key).where(match, ObjectIntent.created_at <= before)
        found += await _scalars(db, stmt)
    return found


async def _row_keys(db: Any, sel: Selection, out: Keys) -> dict[str, uuid.UUID]:
    """Keys named by rows; returns the whole collections' import prefixes."""
    for img in sel.images:
        out.images[img.id] = {k for k in (img.storage_key, img.display_key) if k}
    for chunk in chunks([i.id for i in sel.images]):
        for model in (Rendition, UploadSession):
            stmt = select(model.image_id, model.storage_key).where(model.image_id.in_(chunk))
            for image_id, key in (await db.execute(stmt)).all():
                out.images[image_id].add(key)
    jobs: dict[str, uuid.UUID] = {}
    for coll in sel.whole:
        out.collections[coll.id] = {coll.map_key} if coll.map_key else set()
    whole_ids = list(out.collections)
    if whole_ids:
        stmt = select(UploadSession.collection_id, UploadSession.storage_key).where(
            UploadSession.collection_id.in_(whole_ids)
        )
        for coll_id, key in (await db.execute(stmt)).all():
            out.collections[coll_id].add(key)
        for job in await _scalars(
            db, select(ImportJob).where(ImportJob.collection_id.in_(whole_ids))
        ):
            out.collections[job.collection_id].update(
                k for k in [job.source_key, *(job.staged_keys or [])] if k
            )
            jobs[storage_keys.import_prefix(job.tenant_id, str(job.id))] = job.collection_id
    return jobs


async def collect_keys(db: Any, sel: Selection, now: datetime) -> Keys:
    out = Keys()
    jobs = await _row_keys(db, sel, out)
    by_prefix = {
        storage_keys.image_prefix(i.tenant_id, str(i.collection_id), str(i.id)): i.id
        for i in sel.images
    }
    prefixes = set(by_prefix) | set(jobs)
    prefixes |= {storage_keys.collection_prefix(c.tenant_id, str(c.id)) for c in sel.whole}
    for key in await _intents(db, prefixes, now - MIN_INTENT_AGE):
        owner = _owner(key, set(by_prefix), jobs)
        if owner is None:
            continue
        kind, ident = owner
        if kind == "image":
            out.images[by_prefix[ident]].add(key)
        elif (cid := _uuid(ident)) in out.collections:
            out.collections[cid].add(key)
    out.kept = await _referenced(db, out.all(), [i.id for i in sel.images], list(out.collections))
    for group in (*out.images.values(), *out.collections.values()):
        group.difference_update(out.kept)
    return out


async def _referenced(
    db: Any, keys: set[str], image_ids: list[uuid.UUID], whole_ids: list[uuid.UUID]
) -> set[str]:
    """The keys a row that survives this pass still points at."""
    found: set[str] = set()
    for chunk in chunks(sorted(keys)):
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
