"""Counting and windowing referrers **in SQL** — the read half of design §9.

Split from :mod:`sm_records.services._referrers` for the 300-line cap, along
the seam that module's docstring already draws: it owns *what* a referrer is
(the ``(target_uuid, target_type_id)`` lookup, the self-reference rule, the
``on_delete`` a field declares), and this owns the arithmetic the panel and
the editor's badge need — how many there are, how many of them this caller
may not see, and which page of the visible ones to load.

**Why it is SQL and not a slice.** ``paged_referrers`` used to load every
referring row, resolve every referring record, and then window the result in
Python; ``referrer_count`` loaded the same set to call ``len`` on it. Its
justification was that "how many records reference one record" is bounded by
the graph an editor built by hand — and ``POST …/records/import`` is how that
stopped being true. A thousand rows pointing at one record made
``?page_size=1`` load a thousand ORM objects, and the editor screen did it
again for a badge, on every load.

**Visibility is a type-level predicate, so it fits in the query.** A referrer
is hidden from this caller when its *type* narrows ``allowed_roles`` past
them (``services._common.role_blocked``) — a fact about the type, not the
row, and one the schema answers in a single read before the walk starts. So
"which types are blocked" becomes ``tid NOT IN (…)`` and the page window is
taken over the visible set in ``LIMIT``/``OFFSET``, which is the property the
panel's contract rests on: windowing before the role filter made
``page_size=1`` an oracle that located the hidden rows by their gaps.

**The referrer's own type id comes off the index row.** ``_IndexRow.type_id``
is denormalised onto every index row — it is the *referrer's* type, since a
ref row lives in the referrer's table set (§6.4) — so the predicate needs no
join to the record table, and the count of a thousand referrers is one index
scan rather than a thousand loaded rows.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Subquery

from sm_records.models import Record, RecordType, TableSet, tables_of
from sm_records.schema.types import IndexKind

__all__ = ["pair_page", "pair_rows", "set_counts", "types_by_id"]

SetCounts = tuple[int, int, int]
"""``(records, visible_records, visible_rows)`` for one table set.

The three are not derivable from one another: ``records`` counts every
referring **record** (the panel's ``total``, which cannot shrink per caller),
``visible_records`` is how many of those this caller may read — ``total -
visible_records`` is ``hidden`` — and ``visible_rows`` counts *rows* rather
than records, since one record referring through two fields is two entries in
``items``, which is what the page window is taken over.
"""


def pair_rows(tables: TableSet, record: Record) -> Subquery:
    """The distinct ``(record_id, field_key, type_id)`` rows of one table set
    that point at ``record`` **and whose referring record still exists**.

    ``DISTINCT`` because a to-many relation listing the same target twice
    writes two identical ref rows, and the panel shows one entry per
    ``(record, field)``: the set the old Python walk built had the same
    effect and the same reason.

    The join to the record table is that walk's "load the ids and skip the
    ones that came back missing", in SQL. It is not redundant: a record
    removed out of band — by a migration, by a script, by anything that did
    not go through ``hard_delete_record`` — leaves its ref rows behind, and
    counting those made the editor's badge disagree with the panel that
    could not resolve them. **Core tables, not the mapped classes**, so the
    framework's soft-delete criteria never attach: a *trashed* referrer is
    listed here and flagged (``ReferrerRead.is_deleted``), which is the
    panel's contract and the opposite of the delete path's.

    Self-references are dropped here rather than after the fact, and "itself"
    is a row in *this* set with this id — two collections number their
    records independently, so an id alone names two different rows (§6.4). A
    record holding a relation to itself would otherwise make its own
    ``restrict`` field refuse its own delete.
    """
    ref = tables.index[IndexKind.REF].__table__
    rows = tables.record.__table__
    stmt = (
        select(
            ref.c.record_id.label("rid"),
            ref.c.field_key.label("fk"),
            ref.c.type_id.label("tid"),
        )
        .select_from(ref.join(rows, rows.c.id == ref.c.record_id))
        .where(ref.c.target_uuid == record.uuid, ref.c.target_type_id == record.type_id)
    )
    if tables is tables_of(record):
        stmt = stmt.where(ref.c.record_id != record.id)
    return stmt.distinct().subquery()


async def set_counts(db: AsyncSession, rows: Subquery, blocked: list[int]) -> SetCounts:
    """The three numbers above, in one statement over :func:`pair_rows`.

    ``blocked`` is the ids of the types this caller may not read. Empty is
    the common case — no type on the install narrows, or there is no caller
    at all — and it takes the branch without a ``CASE``, so an install that
    uses none of §10 reads the same statement it always did.
    """
    if blocked:
        visible = rows.c.tid.notin_(blocked)
        columns = (
            func.count(distinct(rows.c.rid)),
            func.count(distinct(case((visible, rows.c.rid)))),
            func.count(case((visible, 1))),
        )
    else:
        columns = (
            func.count(distinct(rows.c.rid)),
            func.count(distinct(rows.c.rid)),
            func.count(),
        )
    row = (await db.execute(select(*columns).select_from(rows))).one()
    return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)


async def pair_page(
    db: AsyncSession,
    rows: Subquery,
    blocked: list[int],
    *,
    offset: int,
    limit: int,
) -> list[tuple[int, str]]:
    """One window of the *visible* ``(record_id, field_key)`` pairs.

    Ordered by ``(record_id, field_key)``, which is insertion order for the
    records and declaration-independent for the fields — the order the Python
    walk produced, kept so adding this window did not reorder anybody's
    panel.
    """
    stmt = select(rows.c.rid, rows.c.fk).select_from(rows)
    if blocked:
        stmt = stmt.where(rows.c.tid.notin_(blocked))
    stmt = stmt.order_by(rows.c.rid, rows.c.fk).limit(limit).offset(offset)
    return [(int(rid), str(field_key)) for rid, field_key in (await db.execute(stmt)).all()]


async def types_by_id(db: AsyncSession) -> dict[int, Any]:
    """Every record type on the install, keyed by id — one query.

    Both halves of the panel need it and neither can be answered without it:
    ``role_blocked`` is a predicate over a type's ``allowed_roles``, and a
    listed referrer carries its type's label and the field definition its
    ``field_label``/``on_delete`` come from. The install's type count is the
    same small number ``GET /types`` returns.
    """
    rows = (await db.execute(select(RecordType))).scalars().all()
    return {int(rtype.id): rtype for rtype in rows if rtype.id is not None}
