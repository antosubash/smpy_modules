"""The state machine behind direct uploads (``images_upload_session``).

::

    open --complete claims--> completing --insert commits--> completed
      |                           |
      +--abort claims--> aborted <+-- (bytes refused after assembly)
                                  +-- open again (parts refused before assembly)

Every transition out of ``open`` is a compare-and-set (``UPDATE ... WHERE
status = 'open'``), so exactly one of a racing ``complete`` and ``abort`` wins
and the loser backs off instead of acting on the same object:

* the claims (``open -> completing``, ``open -> aborted``) commit **on their
  own**, in a short independent transaction, before any storage call - so the
  other side sees them at once and never waits behind a slow S3 assembly;
* ``completing -> completed`` commits in the request's transaction, with the
  image row it describes;
* a ``complete`` that fails hands the session back (``settle``): to ``open``
  when the parts were refused, so the client can resend them, or to
  ``aborted`` once the assembled object has been discarded.

A process dying between the claim and the insert leaves ``completing``; the
reaper takes that back too, but only :data:`COMPLETING_GRACE` after the
session expired - a complete must claim before expiry, so by then nothing can
still be running.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from simple_module_db.independent import independent_session
from sqlalchemy import and_, or_, select, update

from sm_images import constants
from sm_images.errors import UploadInProgress, UploadNotFound
from sm_images.ingest.dedupe import find_id
from sm_images.models import UploadSession, UploadStatus

__all__ = [
    "COMPLETING_GRACE",
    "claim_abort",
    "claim_complete",
    "finish",
    "new_session",
    "reap_expired_uploads",
    "settle",
]

logger = logging.getLogger(__name__)

COMPLETING_GRACE: Final = timedelta(hours=1)
"""How long after expiry a ``completing`` session is presumed dead."""

_GONE = "Upload not found"
_BUSY = "This upload is being completed"


def _now() -> datetime:
    return datetime.now(UTC)


def new_session(ticket: Any, collection_id: uuid.UUID) -> UploadSession:
    """The ``open`` row for a ticket ``start`` just minted."""
    return UploadSession(
        id=uuid.UUID(ticket.session),
        collection_id=collection_id,
        image_id=uuid.UUID(ticket.image),
        storage_key=ticket.key,
        backend_upload_id=ticket.upload,
        size=ticket.size,
        content_type=ticket.content_type,
        status=UploadStatus.OPEN,
        expires_at=_now() + timedelta(seconds=constants.DIRECT_UPLOAD_TTL_SECONDS),
    )


async def _move(
    db: Any, sid: uuid.UUID, frm: UploadStatus, to: UploadStatus, *, live_at: datetime | None = None
) -> bool:
    """The compare-and-set: ``frm -> to``; ``live_at`` also requires the session unexpired."""
    stmt = update(UploadSession).where(UploadSession.id == sid, UploadSession.status == frm)
    if live_at is not None:
        stmt = stmt.where(UploadSession.expires_at > live_at)
    result = await db.execute(stmt.values(status=to).execution_options(synchronize_session=False))
    return result.rowcount == 1


async def _status(db: Any, sid: uuid.UUID) -> UploadStatus | None:
    stmt = select(UploadSession.status).where(UploadSession.id == sid)
    return (await db.execute(stmt)).scalars().first()


async def claim_complete(db: Any, ticket: Any) -> bool:
    """``open -> completing``, committed at once. ``False``: already completed
    (the caller answers with the row). Raises when the other side owns it."""
    sid = uuid.UUID(ticket.session)
    async with independent_session(db) as s:
        if await _move(s, sid, UploadStatus.OPEN, UploadStatus.COMPLETING, live_at=_now()):
            return True
        found = await _status(s, sid)
    if found is UploadStatus.COMPLETED:
        return False
    if found is UploadStatus.COMPLETING:
        raise UploadInProgress(_BUSY)
    raise UploadNotFound(_GONE)  # aborted, expired or unknown


async def claim_abort(db: Any, ticket: Any) -> bool:
    """``open -> aborted``, committed at once. ``True``: the caller discards the
    objects (also on a repeated abort, so a failed cleanup can be retried);
    ``False``: completed, nothing to do. Raises while a complete runs."""
    sid = uuid.UUID(ticket.session)
    async with independent_session(db) as s:
        if await _move(s, sid, UploadStatus.OPEN, UploadStatus.ABORTED):
            return True
        found = await _status(s, sid)
    if found is UploadStatus.ABORTED:
        return True
    if found is UploadStatus.COMPLETED:
        return False
    if found is UploadStatus.COMPLETING:
        raise UploadInProgress(_BUSY)
    raise UploadNotFound(_GONE)


async def finish(db: Any, ticket: Any) -> None:
    """``completing -> completed`` in the caller's transaction (with the row)."""
    await _move(db, uuid.UUID(ticket.session), UploadStatus.COMPLETING, UploadStatus.COMPLETED)


async def settle(db: Any, ticket: Any, to: UploadStatus) -> None:
    """Hand a failed complete's claim back. The request's transaction is rolled
    back first (it is failing anyway), so on SQLite it holds no write lock the
    independent transaction would wait on."""
    await db.rollback()
    async with independent_session(db) as s:
        await _move(s, uuid.UUID(ticket.session), UploadStatus.COMPLETING, to)


# -- reaping abandoned uploads (called by the janitor, Task 15) -----------


async def _reap_one(db: Any, store: Any, row: UploadSession) -> bool:
    async with db.begin_nested():
        if not await _move(db, row.id, row.status, UploadStatus.ABORTED):
            return False  # a complete or abort got there first
        await store.backend.abort_multipart(row.storage_key, row.backend_upload_id)
        if not await find_id(db, row.image_id):
            await store.delete_keys([row.storage_key])
    return True


async def reap_expired_uploads(db: Any, store: Any, now: datetime, cap: int) -> int:
    """Abort up to ``cap`` expired sessions in the bound tenant; how many were.

    Each is claimed ``aborted`` before its parts are discarded and its staged
    key deleted (never a key an image row owns). The key's write-ahead intent
    is left alone: it is the janitor's backstop, cleared by its own sweep. A
    session whose storage cleanup fails is rolled back to its savepoint and
    retried on the next run. The caller commits.
    """
    stale = or_(
        and_(UploadSession.status == UploadStatus.OPEN, UploadSession.expires_at <= now),
        and_(
            UploadSession.status == UploadStatus.COMPLETING,
            UploadSession.expires_at <= now - COMPLETING_GRACE,
        ),
    )
    stmt = select(UploadSession).where(stale).order_by(UploadSession.expires_at).limit(cap)
    reaped = 0
    for row in list((await db.execute(stmt)).scalars()):
        try:
            reaped += await _reap_one(db, store, row)
        except Exception:
            logger.warning("images: could not reap upload session %s", row.id, exc_info=True)
    return reaped
