"""Revision history — reading it, restoring from it, and the one write every
record change makes.

The write helper lives here rather than in ``records`` so
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

from sm_records.constants import ORPHANED_KEY
from sm_records.models import (
    Record,
    RecordRevision,
    RecordType,
    RecordTypeRevision,
    RevisionEvent,
    tables_of,
)
from sm_records.services._common import utcnow
from sm_records.services._payload import field_defs
from sm_records.services.errors import NotFound
from sm_records.settings import RecordsSettings


async def list_revisions(db: AsyncSession, record: Record) -> list[RecordRevision]:
    """Newest first — the order a history panel reads in.

    The revision table is the record's own (Phase 5 §6.3), found from the
    record's *class* rather than from a ``RecordType`` argument: these three
    helpers are called from places that hold a row and no type, and the class
    cannot disagree with the row about which table it came from.
    """
    revision = tables_of(record).revision
    stmt = select(revision).where(revision.record_id == record.id).order_by(revision.id.desc())
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
    revision = tables_of(record).revision(
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
    revision = tables_of(record).revision
    stale = (
        (
            await db.execute(
                select(revision.id)
                .where(revision.record_id == record.id)
                .order_by(revision.id.desc())
                .offset(limit)
            )
        )
        .scalars()
        .all()
    )
    if stale:
        await db.execute(delete(revision).where(revision.id.in_(list(stale))))


def _split(rtype: RecordType, snapshot: dict) -> tuple[dict, dict]:
    """A revision's payload as ``(write payload, orphaned keys)``.

    The split is by what the type declares *now*: a key it still has is part
    of the write and validates like any other, and a key it has dropped since
    the snapshot was taken is recovery data. A revision's own ``_orphaned``
    sub-key folds into the second half — it was already recovery data when the
    snapshot was taken — but only for keys still undeclared, since a key that
    has come back reads from the record's own ``_orphaned`` anyway
    (``schema.compile.from_stored``) and must not be written twice.
    """
    declared = {field.key for field in field_defs(rtype)}
    data = {k: v for k, v in snapshot.items() if k in declared}
    orphaned = {k: v for k, v in snapshot.items() if k not in declared and k != ORPHANED_KEY}
    for key, value in (snapshot.get(ORPHANED_KEY) or {}).items():
        if key not in declared:
            orphaned.setdefault(key, value)
    return data, orphaned


async def restore(
    db: AsyncSession,
    rtype: RecordType,
    record: Record,
    *,
    revision_id: int,
    expected_version: int,
    settings: RecordsSettings,
    actor: str | None = None,
) -> Record:
    """Write a past revision's payload back as a new version of the record.

    **It validates against the schema as it is now, not as it was.** A revision
    written under an older ``schema_version`` may therefore be refused — a
    field that has since become required and is absent from it, a value the
    type no longer accepts — and that is the correct answer rather than a
    limitation: the alternative is storing a payload that the current schema
    says cannot exist, which is exactly the state §8.3 keeps records *out* of
    by restamping on every write. The operator's recourse is the same as for
    any other invalid content: fix the value, or change the schema.

    **A key the schema no longer declares is not a refusal, though.** Every
    revision taken before a field was deleted still carries that field at top
    level, and the compiled validator is ``extra="forbid"`` — so handing the
    snapshot back whole made *every* such revision a permanent 422, which is
    the opposite of what a history is for. The payload is split instead:
    declared keys are the write, and the rest is filed under ``_orphaned`` by
    ``update_record``'s internal ``orphaned_extra``, exactly where the field's
    value would have gone had the record been edited after the deletion (§8.3).
    Nothing from the revision is dropped, and nothing about the client-facing
    rule changes: an inbound payload carrying ``_orphaned`` is still refused.

    The revision must belong to this record, and it is looked up in the
    record's **own** revision table (``tables_of(record).revision``) exactly as
    :func:`list_revisions` and :func:`write_revision` do. Naming the global
    ``RecordRevision`` here would match by ``(id, record_id)`` against another
    table entirely: two collections number their records independently and so
    does the global set, so a collection record's restore would write an
    unrelated record's payload over it. Nothing else in the API takes a
    revision id, so an id from another record is a 404 rather than a 403 —
    there is no resource here the caller is being refused access to.

    ``RevisionEvent.RESTORE`` is stamped on the revision this write itself
    appends, so the history shows "restored from" as its own event rather than
    as an ordinary update that happens to repeat an older payload.
    """
    revision_table = tables_of(record).revision
    revision = (
        (
            await db.execute(
                select(revision_table).where(
                    revision_table.id == revision_id,
                    revision_table.record_id == record.id,
                )
            )
        )
        .scalars()
        .first()
    )
    if revision is None:
        raise NotFound(f"record {record.uuid} has no revision {revision_id!r}")

    # Imported here, not at the top: ``records`` imports this module for
    # ``write_revision``, so the pair can only be acyclic one way round.
    from sm_records.services.records import update_record

    data, orphaned = _split(rtype, dict(revision.data or {}))

    return await update_record(
        db,
        rtype,
        record,
        expected_version=expected_version,
        data=data,
        settings=settings,
        actor=actor,
        event=RevisionEvent.RESTORE,
        orphaned_extra=orphaned,
    )
