"""The janitor's purge (spec §7 "Purge"): trashed rows past the grace period.

Runs in the caller's session under the bound tenant (the janitor binds each in
turn); :mod:`sm_images.jobs.purge_select` decides the rows and their keys. One pass:

1. **Uploads.** Every upload session that may still hold multipart parts is
   taken over and its upload aborted *before* its row can go - the row is the
   only record of the backend's upload id. A failed abort keeps the session,
   and its collection, for the next pass.
2. **Keys, group by group.** One batched delete; if it fails, each image's
   keys, then each whole collection's own keys (its map, import staging) are
   deleted separately. A group whose delete fails keeps its rows - the next
   pass retries with the rows still there to say what to delete - and only
   that group: an image is recorded (``purge_failed_at``, which sends it to
   the back of later passes) and its collection is not removed. After
   :data:`FAILURE_LIMIT` failures a pass stops trying (storage is down).
3. **Rows** of what was cleared, children first, and a whole collection's
   share rows (``sharing.contracts.forget_resource``, in this session and
   tenant); the intents of the deleted keys; the images' storage-hold
   releases (:mod:`sm_images.core.billing.ops`). The caller commits.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sharing.contracts import forget_resource
from sharing.policy import canonical_id
from simple_module_db.independent import independent_session
from sqlalchemy import and_, delete, or_, select, update

from sm_images.core.access import COLLECTION_RESOURCE
from sm_images.core.billing import ops as billing_ops
from sm_images.core.constants import NO_SYNC
from sm_images.ingest.upload_session import mark_cleaned, move
from sm_images.jobs.purge_delete import FAILURE_LIMIT, delete_keys
from sm_images.jobs.purge_select import MIN_INTENT_AGE, Keys, Selection, chunks, collect_keys, pick
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

__all__ = ["FAILURE_LIMIT", "MIN_INTENT_AGE", "PurgeReport", "purge_expired"]

logger = logging.getLogger(__name__)

_UNSETTLED = or_(
    UploadSession.status.in_((UploadStatus.OPEN, UploadStatus.COMPLETING)),
    and_(UploadSession.status == UploadStatus.ABORTED, UploadSession.cleaned_at.is_(None)),
)


@dataclass
class PurgeReport:
    dry_run: bool
    collections: list[uuid.UUID] = field(default_factory=list)
    images: list[uuid.UUID] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    """Deleted (or, on a dry run, that would be)."""
    kept: list[str] = field(default_factory=list)
    """Collected but still referenced by a surviving row: never deleted."""
    failed: list[uuid.UUID] = field(default_factory=list)
    """Images whose objects would not delete: kept, retried by a later pass."""


async def _abort_one(db: Any, store: Any, row: Any) -> bool:
    """Take the session over (committed on its own), abort, record it clean."""
    if row.status is not UploadStatus.ABORTED:
        async with independent_session(db) as s:
            values = {"status": UploadStatus.ABORTED, "claim_token": uuid.uuid4()}
            if not await move(s, row.id, row.status, values):
                return False  # it moved under us: next pass
    abort = getattr(store.backend, "abort_multipart", None)
    if abort is not None:  # a backend without multipart has no parts to drop
        await abort(row.storage_key, row.backend_upload_id)
    async with independent_session(db) as s:
        await mark_cleaned(s, row.id)
    return True


async def _abort_uploads(db: Any, store: Any, image_ids: list, whole: list) -> list[Any]:
    """Abort every unsettled upload; the sessions that could not be."""
    owners = [UploadSession.collection_id.in_(whole)] if whole else []
    for chunk in chunks(image_ids):
        owners.append(UploadSession.image_id.in_(chunk))
    if not owners:
        return []
    stmt = select(UploadSession).where(or_(*owners), _UNSETTLED)
    rows = [
        (r.id, r.collection_id, r.status, r.storage_key, r.backend_upload_id)
        for r in (await db.execute(stmt)).scalars()
    ]
    stuck = []
    for sid, cid, status, key, upload in rows:
        row = _Upload(sid, cid, status, key, upload)
        try:
            if await _abort_one(db, store, row):
                continue
        except Exception:
            logger.warning("images.purge.upload_abort_failed session=%s", sid, exc_info=True)
        stuck.append(row)
    return stuck


@dataclass(frozen=True)
class _Upload:
    id: uuid.UUID
    collection_id: uuid.UUID
    status: UploadStatus
    storage_key: str
    backend_upload_id: str


async def _delete_rows(
    db: Any, image_ids: list, whole_ids: list, keys: list[str], keep_sessions: list
) -> None:
    async def run(stmt: Any) -> None:
        await db.execute(stmt.execution_options(**NO_SYNC))

    for chunk in chunks(image_ids):
        await run(update(ImportItem).where(ImportItem.image_id.in_(chunk)).values(image_id=None))
        for model in (StepRun, Rendition, PromptResult):
            await run(delete(model).where(model.image_id.in_(chunk)))
        await run(
            delete(UploadSession).where(
                UploadSession.image_id.in_(chunk), UploadSession.id.not_in(keep_sessions)
            )
        )
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
        for chunk in chunks([canonical_id(cid) for cid in whole_ids]):
            await forget_resource(db, COLLECTION_RESOURCE, chunk)
    for chunk in chunks(keys):
        await run(delete(ObjectIntent).where(ObjectIntent.key.in_(chunk)))


async def _record(db: Any, model: Any, ids: set, now: datetime) -> None:
    """Send what failed to the back of later passes."""
    if ids:
        await db.execute(
            update(model)
            .where(model.id.in_(sorted(ids)))
            .values(purge_failed_at=now)
            .execution_options(**NO_SYNC, include_deleted=True)
        )


async def _clear(db: Any, store: Any, sel: Selection, keys: Keys, now: datetime):
    """Steps 1 and 2: what may go. Returns ``(images, whole, failed, stuck, deleted)``."""
    whole = {c.id for c in sel.whole}
    stuck = await _abort_uploads(db, store, [i.id for i in sel.images], sorted(whole))
    blocked = {u.storage_key for u in stuck}
    whole -= {u.collection_id for u in stuck}
    for group in (*keys.images.values(), *keys.collections.values()):
        group -= blocked
    of = {i.id: i.collection_id for i in sel.images}
    cleared = await delete_keys(store, keys, of, whole)
    failed = {ident for kind, ident in cleared.failed if kind == "image"}
    kept = {ident for kind, ident in cleared.kept() if kind == "image"}
    picked = {c.id for c in sel.collections}
    bad = {ident for kind, ident in cleared.failed if kind == "collection"}
    bad |= {u.collection_id for u in stuck} | {of[i] for i in failed}
    await _record(db, Image, failed, now)
    await _record(db, Collection, bad & picked, now)
    images = [i for i in sel.images if i.id not in kept]
    return images, whole, failed, stuck, cleared.deleted


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
    sel = await pick(db, now - timedelta(days=grace_days), cap)
    report = PurgeReport(dry_run, [c.id for c in sel.whole], [i.id for i in sel.images])
    if not sel.images and not sel.whole:
        return report
    keys = await collect_keys(db, sel, now)
    report.keys, report.kept = sorted(keys.all()), sorted(keys.kept)
    if dry_run:
        await db.rollback()  # nothing changed; let the row locks go
        return report
    images, whole, failed, stuck, deleted = await _clear(db, store, sel, keys, now)
    report.images, report.collections = [i.id for i in images], sorted(whole)
    report.keys, report.failed = sorted(deleted), sorted(failed)
    await _delete_rows(db, report.images, report.collections, report.keys, [u.id for u in stuck])
    await billing_ops.release_storage(
        db, [(i.id, i.storage_hold_id, i.storage_bytes) for i in images]
    )
    return report
