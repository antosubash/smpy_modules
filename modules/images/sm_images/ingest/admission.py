"""Admission for a new direct or ZIP upload, in the transaction that opens it.

An open upload session lets a client write straight to storage; the storage
gauge is only enforced when ``complete`` (or a ZIP's extracted items) take
their holds. So :func:`admit` refuses, before the session row is inserted:

* past ``max_open_uploads_per_tenant`` sessions still open (``open`` or
  ``completing``, not expired) in the tenant - 429 ``too_many_open_uploads``;
* when the declared sizes of those sessions plus this one would not fit the
  gauge's headroom - 402 ``quota_exceeded``. The headroom (``limit - level``,
  :func:`sm_images.core.billing.headroom`) is read by :func:`prepare` *before* the
  lock, so admission never opens a billing connection while holding it.
  Without billing this part is skipped.

**Serialised per tenant.** :func:`admit` first *writes* the tenant's
``images_upload_admission`` row (an upsert, then an ``UPDATE``): the row lock on
Postgres, the database write lock on SQLite. The caller inserts the session row
in the same transaction and commits, which releases the lock, so the next
admission counts it. The cap is therefore hard. The quota check is soft:
the headroom was read before the lock, so any gauge growth between that read
and the lock (a ``complete``, a form upload, a step that grows an image) is not
seen - an overshoot of at most the sum of those concurrent increases, each of
which its own hold then refuses or counts. Run :func:`admit` as the transaction's first statement
(SQLite: a transaction that read first can fail to take the write lock with
``SQLITE_BUSY_SNAPSHOT`` instead of waiting).

**Billing's ``user`` mode.** The headroom is the collection owner's
(``user:<owner>``), so the pending bytes compared with it are only those of
open sessions whose collection's owner maps to the same subject: another
owner's open upload is held against that owner's gauge, not this one's room.
When the subject fell back to the tenant (an owner billing cannot bill), every
open session of the tenant counts, as in ``tenant`` mode. The open-session
count, the cap and the lock stay per tenant: the cap bounds concurrency, it is
not a quota.

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

from sm_images.core import billing
from sm_images.core.billing.subject import user_subject
from sm_images.core.clock import utcnow
from sm_images.core.errors import StorageQuotaExceeded, TooManyOpenUploads
from sm_images.models import Collection, UploadAdmission, UploadSession, UploadStatus

__all__ = ["Admission", "admit", "open_uploads", "pending_for", "prepare"]

Admission = Callable[[Any], Awaitable[None]]
"""Called with the session that will insert the upload's row (``open_upload``).

Holds no connection but that session's: the billing read is done by
:func:`prepare`, and the open-session count and the cap use ``db``."""

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


def _is_open(tenant: str) -> tuple[Any, ...]:
    """The criteria of an open session: *tenant*'s, not expired, not settled."""
    return (
        UploadSession.tenant_id == tenant,
        UploadSession.status.in_(_OPEN),
        UploadSession.expires_at > utcnow(),
    )


async def open_uploads(db: Any, tenant: str) -> tuple[int, int]:
    """``(count, declared bytes)`` of *tenant*'s unexpired open sessions."""
    stmt = select(func.count(), func.coalesce(func.sum(UploadSession.size), 0)).where(
        *_is_open(tenant)
    )
    count, total = (await db.execute(stmt)).one()
    return int(count), int(total)


async def pending_for(db: Any, tenant: str, subject: str) -> int:
    """Declared bytes of *tenant*'s unexpired open sessions whose collection's
    owner bills as the user *subject*. Grouped by owner and mapped in Python, so
    any spelling of an owner's id maps as billing maps it; a trashed collection's
    open session still counts."""
    stmt = (
        select(Collection.owner_id, func.coalesce(func.sum(UploadSession.size), 0))
        .join(Collection, Collection.id == UploadSession.collection_id)
        .where(*_is_open(tenant))
        .group_by(Collection.owner_id)
        .execution_options(include_deleted=True)
    )
    rows = (await db.execute(stmt)).all()
    return sum(int(n) for owner, n in rows if user_subject(owner) == subject)


async def admit(
    db: Any, tenant: str, size: int, *, cap: int, room: int | None, subject: str | None = None
) -> None:
    """Lock, count and refuse opening an upload of *size* bytes (see module).
    ``room``: the gauge's headroom read before the lock (``None``: unlimited).
    ``subject``: whose gauge ``room`` is; a user's counts only that user's
    open sessions, ``None`` or the tenant every open session of the tenant."""
    await _lock(db, tenant)
    count, pending = await open_uploads(db, tenant)
    if count >= cap:
        raise TooManyOpenUploads(_TOO_MANY)
    if room is None:
        return
    if subject is not None and subject != tenant:
        pending = await pending_for(db, tenant, subject)
    if pending + int(size) > room:
        raise StorageQuotaExceeded(billing.FULL)


async def prepare(
    app: Any, tenant: str, size: int, *, cap: int, subject: str | None = None
) -> Admission:
    """Read the gauge's headroom now (402 if *size* alone does not fit), and
    return :func:`admit` bound to everything but the session, for ``open_upload``.
    ``subject`` is whose gauge is read (the collection owner's in billing's
    ``user`` mode); ``None``: the tenant's."""
    room = await billing.headroom(app, subject or tenant, size)

    async def run(db: Any) -> None:
        await admit(db, tenant, size, cap=cap, room=room, subject=subject)

    return run
