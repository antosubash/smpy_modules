"""Admission for a new direct or ZIP upload, in the transaction that opens it.

An open upload session lets a client write straight to storage; the storage
gauge is only enforced when ``complete`` (or a ZIP's extracted items) take
their holds. So :func:`admit` refuses, before the session row is inserted:

* past ``max_open_uploads_per_tenant`` sessions still open (``open`` or
  ``completing``, not expired) in the tenant - 429 ``too_many_open_uploads``;
* when the gauge plus the declared sizes of those sessions plus this one would
  not fit the plan - billing's pre-flight, :func:`sm_images.billing.check`,
  402 ``quota_exceeded``. Without billing this part is skipped.

**Serialised per tenant.** :func:`admit` first *writes* the tenant's
``images_upload_admission`` row (an upsert, then an ``UPDATE``): the row lock on
Postgres, the database write lock on SQLite. The caller inserts the session row
in the same transaction and commits, which releases the lock, so the next
admission counts it. The cap is therefore hard. The quota check is as exact as
billing's gauge: the open uploads it adds are all committed, so only a
``complete`` taking its hold at the same moment can overshoot, by at most that
upload's declared size. Run :func:`admit` as the transaction's first statement
(SQLite: a transaction that read first can fail to take the write lock with
``SQLITE_BUSY_SNAPSHOT`` instead of waiting).

The declared size is held to at part and complete time: every part must be
exactly its expected size, and ``multipart.assemble`` refuses a missing, short
or extra part, so the object can never exceed what was admitted.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from sm_images import billing
from sm_images.clock import utcnow
from sm_images.errors import TooManyOpenUploads
from sm_images.models import UploadAdmission, UploadSession, UploadStatus

__all__ = ["Admission", "admit", "admitter", "open_uploads"]

Admission = Callable[[Any], Awaitable[None]]
"""Called with the session that will insert the upload's row (``open_upload``)."""

_OPEN = (UploadStatus.OPEN, UploadStatus.COMPLETING)
_TOO_MANY = "Too many uploads are open in this workspace. Finish or cancel one and try again."


async def _lock(db: Any, tenant: str) -> None:
    """Take the tenant's admission lock: a write, held until ``db`` commits."""
    now = utcnow()
    dialect = db.get_bind().dialect.name
    insert = pg_insert if dialect == "postgresql" else sqlite_insert
    stmt = insert(UploadAdmission).values(tenant=tenant, admitted=0, updated_at=now)
    await db.execute(stmt.on_conflict_do_nothing(index_elements=["tenant"]))
    await db.execute(
        update(UploadAdmission)
        .where(UploadAdmission.tenant == tenant)
        .values(admitted=UploadAdmission.admitted + 1, updated_at=now)
        .execution_options(synchronize_session=False)
    )


async def open_uploads(db: Any, tenant: str) -> tuple[int, int]:
    """``(count, declared bytes)`` of *tenant*'s unexpired open sessions."""
    stmt = select(func.count(), func.coalesce(func.sum(UploadSession.size), 0)).where(
        UploadSession.tenant_id == tenant,
        UploadSession.status.in_(_OPEN),
        UploadSession.expires_at > utcnow(),
    )
    count, total = (await db.execute(stmt)).one()
    return int(count), int(total)


async def admit(app: Any, db: Any, tenant: str, size: int, *, cap: int) -> None:
    """Lock, count and refuse opening an upload of *size* bytes (see module)."""
    await _lock(db, tenant)
    count, pending = await open_uploads(db, tenant)
    if count >= cap:
        raise TooManyOpenUploads(_TOO_MANY)
    await billing.check(app, tenant, pending + int(size))


def admitter(app: Any, tenant: str, size: int, *, cap: int) -> Admission:
    """:func:`admit` bound to everything but the session, for ``open_upload``."""

    async def run(db: Any) -> None:
        await admit(app, db, tenant, size, cap=cap)

    return run
