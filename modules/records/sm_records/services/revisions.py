"""Revision history — reading it, and the one write every record change makes.

Restoring *from* a revision is Phase 3 (design §16), so this module is
deliberately thin. The write helper lives here rather than in ``records`` so
that the cap of :attr:`RecordsSettings.revision_limit` has one owner: a trim
that ran on create but not on update is the bug this module exists to make
impossible.

Type revisions are never capped. Types are few and schema edits are rare, so
the table stays tiny — and it is what makes the rollback of §8.6 possible,
which a cap would eventually delete.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import Record, RecordRevision, RecordType, RecordTypeRevision, RevisionEvent
from sm_records.services._common import utcnow


async def list_revisions(db: AsyncSession, record: Record) -> list[RecordRevision]:
    """Newest first — the order a history panel reads in."""
    stmt = (
        select(RecordRevision)
        .where(RecordRevision.record_id == record.id)
        .order_by(RecordRevision.id.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_type_revisions(db: AsyncSession, rtype: RecordType) -> list[RecordTypeRevision]:
    stmt = (
        select(RecordTypeRevision)
        .where(RecordTypeRevision.type_id == rtype.id)
        .order_by(RecordTypeRevision.id.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def write_revision(
    db: AsyncSession,
    record: Record,
    event: RevisionEvent,
    *,
    limit: int,
    actor: str | None = None,
) -> RecordRevision:
    """Append one snapshot and prune anything past ``limit``."""
    revision = RecordRevision(
        record_id=record.id,
        schema_version=record.schema_version,
        version=record.version,
        data=dict(record.data or {}),
        display_title=record.display_title,
        event=event,
        created_at=utcnow(),
        created_by=actor,
    )
    db.add(revision)
    await db.flush()
    await _trim(db, record, limit)
    return revision


async def _trim(db: AsyncSession, record: Record, limit: int) -> None:
    """Delete the oldest revisions beyond ``limit``.

    Two statements rather than ``DELETE … LIMIT``: MySQL takes that syntax,
    Postgres and SQLite do not, and a correlated subquery with ``OFFSET`` is
    harder to read than the select it would inline. The set is bounded by
    ``limit`` plus the one row just written, so the round trip is cheap.

    ``limit`` is clamped to 1 rather than treated as unlimited below it.
    :attr:`RecordsSettings.revision_limit` is validated ``ge=1`` so the
    setting cannot express 0 at all; the clamp covers a direct caller, for
    which "keep none beyond the current" is the reading of 0 nobody is
    surprised by — "0 means keep everything" is how a cap quietly stops
    capping.
    """
    limit = max(limit, 1)
    stale = (
        (
            await db.execute(
                select(RecordRevision.id)
                .where(RecordRevision.record_id == record.id)
                .order_by(RecordRevision.id.desc())
                .offset(limit)
            )
        )
        .scalars()
        .all()
    )
    if stale:
        await db.execute(delete(RecordRevision).where(RecordRevision.id.in_(list(stale))))
