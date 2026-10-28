"""Reclaiming abandoned direct uploads (called by the janitor, Task 15).

Three kinds of session are candidates, all in the bound tenant:

* ``open`` past ``expires_at`` - the client went away;
* ``completing`` past ``lease_expires_at`` - the completer died (or is so slow
  its lease lapsed). Never on age alone: a held lease is never touched;
* ``aborted`` with ``cleaned_at`` NULL - an abort whose storage cleanup failed.

The first two are taken over by compare-and-set - matching the status *and*
the claim token read, writing a new token - so a completer that resumes finds
its claim gone and its ``finish`` rolls back. Only then are the parts
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


async def _take_over(db: Any, c: _Candidate) -> bool:
    if c.status is UploadStatus.ABORTED:
        return True  # already ours to clean; cleanup is idempotent
    same_claim = (
        UploadSession.claim_token.is_(None)
        if c.token is None
        else UploadSession.claim_token == c.token
    )
    values = {"status": UploadStatus.ABORTED, "claim_token": uuid.uuid4()}
    return await move(db, c.id, c.status, values, same_claim)


async def _reap_one(db: Any, store: Any, c: _Candidate) -> bool:
    async with db.begin_nested():
        if not await _take_over(db, c):
            return False  # a complete or abort moved it first
        await discard(db, store, c.key, c.upload, c.image_id)
        await mark_cleaned(db, c.id)
    return True


async def reap_expired_uploads(db: Any, store: Any, now: datetime, cap: int) -> int:
    """Reclaim up to ``cap`` sessions; how many were. A session whose storage
    cleanup fails rolls back to its savepoint and is retried next run. The
    caller commits."""
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
            reaped += await _reap_one(db, store, c)
        except Exception:
            logger.warning("images: could not reap upload session %s", c.id, exc_info=True)
    return reaped
