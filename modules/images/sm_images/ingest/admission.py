"""Admission for a new direct or ZIP upload, before any upload capability is issued.

An open upload session lets a client write straight to storage; the storage
gauge is only enforced when ``complete`` (or a ZIP's extracted items) take
their holds. So :func:`admit` refuses, before the session is opened:

* past ``max_open_uploads_per_tenant`` sessions still open (``open`` or
  ``completing``, not expired) in the tenant - 429 ``too_many_open_uploads``;
* when the gauge plus the declared sizes of those sessions plus this one would
  not fit the plan - billing's pre-flight, :func:`sm_images.billing.check`,
  402 ``quota_exceeded``. Without billing this part is skipped.

The declared size is held to at part and complete time: every part must be
exactly its expected size, and ``multipart.assemble`` refuses a missing, short
or extra part, so the object can never exceed what was admitted.

**Soft.** Two concurrent opens each count the sessions committed before them,
so together they can overshoot by at most the cap's worth of declared sizes.
The hold taken at ``complete`` is still the enforcement.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from sm_images import billing
from sm_images.errors import TooManyOpenUploads
from sm_images.models import UploadSession, UploadStatus

__all__ = ["admit", "open_uploads"]

_OPEN = (UploadStatus.OPEN, UploadStatus.COMPLETING)
_TOO_MANY = "Too many uploads are open in this workspace. Finish or cancel one and try again."


async def open_uploads(db: Any, tenant: str) -> tuple[int, int]:
    """``(count, declared bytes)`` of *tenant*'s unexpired open sessions."""
    stmt = select(func.count(), func.coalesce(func.sum(UploadSession.size), 0)).where(
        UploadSession.tenant_id == tenant,
        UploadSession.status.in_(_OPEN),
        UploadSession.expires_at > datetime.now(UTC),
    )
    count, total = (await db.execute(stmt)).one()
    return int(count), int(total)


async def admit(app: Any, db: Any, tenant: str, size: int, *, cap: int) -> None:
    """Refuse opening an upload of *size* declared bytes in *tenant* (see module)."""
    count, pending = await open_uploads(db, tenant)
    if count >= cap:
        raise TooManyOpenUploads(_TOO_MANY)
    await billing.check(app, tenant, pending + int(size))
