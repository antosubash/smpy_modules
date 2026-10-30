"""Reclaiming abandoned direct uploads (called by the janitor, Task 15).

Three kinds of session are candidates, all in the bound tenant:

* ``open`` past ``expires_at`` - the client went away;
* ``completing`` past ``lease_expires_at`` - the completer died (or is so slow
  its lease lapsed). Never on age alone: a held lease is never touched;
* ``aborted`` with ``cleaned_at`` NULL - an abort whose storage cleanup failed.

The first two are taken over by compare-and-set - matching the status *and*
the claim token read, writing a new token - so a completer that resumes finds
its claim gone and its ``renew``/``finish`` fails. The takeover commits on its
own before any storage call; only then are the parts
discarded and the staged key deleted (never one an image row owns), and
``cleaned_at`` is set. The key's write-ahead intent is left alone: it is the
janitor's own backstop.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from simple_module_db.independent import independent_session
from sqlalchemy import and_, or_, select

from sm_images.ingest.upload_session import discard, mark_cleaned, move
from sm_images.models import UploadSession, UploadStatus

__all__ = ["reap_expired_uploads"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Candidate:
    """Plain values: nothing to lazy-load after a savepoint rolls back."""

    id: uuid.UUID
    status: UploadStatus
    token: uuid.UUID | None
    key: str
    upload: str
    image_id: uuid.UUID


async def _take_over(db: Any, c: _Candidate, now: datetime) -> bool:
    """The compare-and-set re-checks expiry in its own WHERE: a lease renewed
    (or an open session extended) after the candidate SELECT makes it miss."""
    if c.status is UploadStatus.ABORTED:
        return True  # already ours to clean; cleanup is idempotent
    same_claim = (
        UploadSession.claim_token.is_(None)
        if c.token is None
        else UploadSession.claim_token == c.token
    )
    expired = (
        UploadSession.expires_at <= now
        if c.status is UploadStatus.OPEN
        else UploadSession.lease_expires_at <= now
    )
    values = {"status": UploadStatus.ABORTED, "claim_token": uuid.uuid4()}
    return await move(db, c.id, c.status, values, same_claim, expired)


async def _reap_one(db: Any, store: Any, c: _Candidate, now: datetime) -> bool:
    """Take over (committed on its own), *then* clean, then record it clean.

    The takeover commits before any storage call, so a cleanup that fails -
    even after it deleted the object - can never roll the old claim token
    back: a resuming completer's ``renew``/``finish`` keeps failing. A failed
    cleanup leaves ``cleaned_at`` NULL and the next run retries it.
    """
    async with independent_session(db) as s:
        took = await _take_over(s, c, now)
    if not took:
        return False  # a complete or abort moved it first
    await discard(db, store, c.key, c.upload, c.image_id)
    async with independent_session(db) as s:
        await mark_cleaned(s, c.id)
    return True


async def reap_expired_uploads(db: Any, store: Any, now: datetime, cap: int) -> int:
    """Reclaim up to ``cap`` sessions; how many were. ``db`` is only read
    through; every state change commits in its own short transaction, so
    nothing here waits for the caller to commit. A session whose storage
    cleanup fails stays ``aborted`` with ``cleaned_at`` NULL for the next run."""
    stale = or_(
        and_(UploadSession.status == UploadStatus.OPEN, UploadSession.expires_at <= now),
        and_(
            UploadSession.status == UploadStatus.COMPLETING,
            UploadSession.lease_expires_at <= now,
        ),
        and_(UploadSession.status == UploadStatus.ABORTED, UploadSession.cleaned_at.is_(None)),
    )
    stmt = select(UploadSession).where(stale).order_by(UploadSession.expires_at).limit(cap)
    candidates = [
        _Candidate(r.id, r.status, r.claim_token, r.storage_key, r.backend_upload_id, r.image_id)
        for r in (await db.execute(stmt)).scalars()
    ]
    reaped = 0
    for c in candidates:
        try:
            reaped += await _reap_one(db, store, c, now)
        except Exception:
            logger.warning("images: could not reap upload session %s", c.id, exc_info=True)
    return reaped
