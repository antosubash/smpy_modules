"""The state machine behind direct uploads (``images_upload_session``).

::

    open --complete claims (token, lease)--> completing --finish--> completed
      |                                          |
      +--abort claims--> aborted <---------------+-- bytes refused after assembly,
                            ^                    |   or the reaper takes over an
                            |                    |   expired lease (new token)
                     cleaned_at set              +-- open again (parts refused)
                     once storage is clean

Every transition is a compare-and-set (``UPDATE ... WHERE status = ...``), so
exactly one of a racing ``complete``, ``abort`` and reaper wins and the others
back off instead of acting on the same object:

* the claims commit **on their own**, in a short independent transaction,
  before any storage call - the other side sees them at once and never waits
  behind a slow S3 assembly;
* ``completing`` is a **fenced lease**: the claim writes a fresh
  ``claim_token`` and ``lease_expires_at`` (:data:`COMPLETE_LEASE`), and the
  completer renews it between its expensive phases (:func:`renew`), so the
  lease bounds each phase and a completer whose token is gone stops. The
  reaper takes over only an expired lease, and its takeover - committed before
  any storage call - changes the token. ``finish`` (``completing ->
  completed``, in the request's transaction with the image row) and
  ``settle`` (a failed complete handing the claim back) both match the token;
  a ``finish`` that matches nothing rolls the request back - its image row
  with it - so a completer that lost its lease never commits a row whose
  object the new owner may have deleted;
* ``aborted`` keeps ``cleaned_at`` NULL until the parts and staged object are
  gone, so a cleanup that failed is retried by the reaper
  (:mod:`sm_images.ingest.upload_reaper`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from simple_module_db.independent import independent_session
from sqlalchemy import select, update

from sm_images import constants
from sm_images.errors import UploadInProgress, UploadNotFound, UploadNotOpen
from sm_images.ingest.dedupe import find_id
from sm_images.models import UploadSession, UploadStatus

__all__ = [
    "COMPLETE_LEASE",
    "claim_abort",
    "claim_complete",
    "discard",
    "finish",
    "mark_cleaned",
    "move",
    "new_session",
    "renew",
    "require_open",
    "settle",
]

COMPLETE_LEASE: Final = timedelta(minutes=15)
"""How long a ``complete`` holds its claim; a bounded image assembles in seconds."""

_GONE = "Upload not found"
_BUSY = "This upload is being completed"
_CLOSED = "This upload no longer accepts parts"


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


async def move(
    db: Any, sid: uuid.UUID, frm: UploadStatus, values: dict[str, Any], *where: Any
) -> bool:
    """The compare-and-set: from ``frm`` (and ``where``) to ``values``; one row or none."""
    stmt = update(UploadSession).where(UploadSession.id == sid, UploadSession.status == frm, *where)
    result = await db.execute(stmt.values(**values).execution_options(synchronize_session=False))
    return result.rowcount == 1


async def _status(db: Any, sid: uuid.UUID) -> UploadStatus | None:
    stmt = select(UploadSession.status).where(UploadSession.id == sid)
    return (await db.execute(stmt)).scalars().first()


async def claim_complete(db: Any, ticket: Any) -> uuid.UUID | None:
    """``open -> completing``, committed at once; the claim's token. ``None``:
    already completed (the caller answers with the row). Raises when another
    party owns the session, or it is aborted, expired or unknown."""
    sid, token, now = uuid.UUID(ticket.session), uuid.uuid4(), _now()
    lease = {"claim_token": token, "lease_expires_at": now + COMPLETE_LEASE}
    async with independent_session(db) as s:
        claimed = await move(
            s,
            sid,
            UploadStatus.OPEN,
            {"status": UploadStatus.COMPLETING, **lease},
            UploadSession.expires_at > now,
        )
        found = None if claimed else await _status(s, sid)
    if claimed:
        return token
    if found is UploadStatus.COMPLETED:
        return None
    if found is UploadStatus.COMPLETING:
        raise UploadInProgress(_BUSY)
    raise UploadNotFound(_GONE)


async def claim_abort(db: Any, ticket: Any) -> bool:
    """``open -> aborted``, committed at once. ``True``: the caller discards the
    objects (also on a repeated abort, so a failed cleanup can be retried);
    ``False``: completed, nothing to do. Raises while a complete holds it."""
    sid = uuid.UUID(ticket.session)
    async with independent_session(db) as s:
        values = {"status": UploadStatus.ABORTED, "claim_token": uuid.uuid4()}
        claimed = await move(s, sid, UploadStatus.OPEN, values)
        found = None if claimed else await _status(s, sid)
    if claimed or found is UploadStatus.ABORTED:
        return True
    if found is UploadStatus.COMPLETED:
        return False
    if found is UploadStatus.COMPLETING:
        raise UploadInProgress(_BUSY)
    raise UploadNotFound(_GONE)


async def renew(db: Any, ticket: Any, token: uuid.UUID) -> None:
    """Extend this claim's lease by :data:`COMPLETE_LEASE`, committed at once.
    Called between a complete's expensive phases, so each phase - not the whole
    complete - is bounded by the lease. The token gone (the reaper took over):
    404, and the completer stops before doing more."""
    async with independent_session(db) as s:
        renewed = await move(
            s,
            uuid.UUID(ticket.session),
            UploadStatus.COMPLETING,
            {"lease_expires_at": _now() + COMPLETE_LEASE},
            UploadSession.claim_token == token,
        )
    if not renewed:
        raise UploadNotFound(_GONE)


async def finish(db: Any, ticket: Any, token: uuid.UUID) -> None:
    """``completing -> completed`` in the caller's transaction, only under this
    claim. Lost (the reaper took the lease over): roll the caller back - the
    image row with it - and answer 404; the object is the new owner's."""
    done = await move(
        db,
        uuid.UUID(ticket.session),
        UploadStatus.COMPLETING,
        {"status": UploadStatus.COMPLETED},
        UploadSession.claim_token == token,
    )
    if not done:
        await db.rollback()
        raise UploadNotFound(_GONE)


async def settle(db: Any, ticket: Any, token: uuid.UUID, to: UploadStatus) -> None:
    """Hand a failed complete's claim back (only if it is still this claim).
    The request's transaction is rolled back first (it is failing anyway), so
    on SQLite it holds no write lock the independent transaction would wait on."""
    await db.rollback()
    async with independent_session(db) as s:
        await move(
            s,
            uuid.UUID(ticket.session),
            UploadStatus.COMPLETING,
            {"status": to},
            UploadSession.claim_token == token,
        )


async def require_open(db: Any, ticket: Any) -> None:
    """Parts are accepted only while ``open``: 409 ``upload_not_open`` once a
    complete claimed or finished it, 404 once aborted. A part write already in
    flight when a complete claims is harmless: the complete assembles only
    what ``list_parts`` shows with the declared sizes (and claimed etags)."""
    found = await _status(db, uuid.UUID(ticket.session))
    if found is UploadStatus.OPEN:
        return
    if found in (UploadStatus.COMPLETING, UploadStatus.COMPLETED):
        raise UploadNotOpen(_CLOSED)
    raise UploadNotFound(_GONE)


async def discard(db: Any, store: Any, key: str, upload: str, image_id: uuid.UUID) -> None:
    """Drop the parts, and the staged object unless an image row owns it."""
    await store.backend.abort_multipart(key, upload)
    if not await find_id(db, image_id):
        await store.delete_keys([key])


async def mark_cleaned(db: Any, sid: uuid.UUID) -> None:
    """Record that an ``aborted`` session's storage is clean (in ``db``'s transaction)."""
    await db.execute(
        update(UploadSession)
        .where(UploadSession.id == sid, UploadSession.status == UploadStatus.ABORTED)
        .values(cleaned_at=_now())
        .execution_options(synchronize_session=False)
    )
