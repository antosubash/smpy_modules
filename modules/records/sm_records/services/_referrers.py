"""Who points at this record, and what that costs them on delete (design §9).

Split from :mod:`sm_records.services._relations` for the 300-line cap, along
the seam that module's docstring draws: it is the *write* check — does this
target exist and is it what the payload claims — and this is the read that a
delete, the referrers panel and the editor's badge all run.

One indexed query over ``records_index_ref`` per table set **that can hold a
referrer**, keyed on ``(target_type_id, target_uuid)``. Both columns, always: a
uuid is unique inside each record table and nothing spans them, so predicating
on the uuid alone made a record that borrowed another's uuid inherit its
referrers — and with them a ``restrict`` that refused a delete nothing pointed
at, a ``cascade`` into an unrelated record and a ``set_null`` that blanked its
field.

"That can hold a referrer" is S5. It used to be *every declared* set, so a host
that declared two collections paid three reads on every ``restrict`` delete and
every referrers panel even when both collections were empty — linear in
declarations, and declarations are a host's Alembic history, which only ever
grows. Which sets can hold one is a fact about the schema
(:mod:`sm_records.services._referrer_sets`), and the schema is one query.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import Record, RecordType, tables_of
from sm_records.schema.fields import ON_DELETE_DEFAULT
from sm_records.schema.types import IndexKind
from sm_records.services._common import role_blocked
from sm_records.services._referrer_sets import referring_sets

__all__ = ["Referrer", "field_label", "paged_referrers", "referrer_count", "referrers"]


@dataclass(frozen=True, slots=True)
class Referrer:
    """One record pointing at the record being deleted, and what that costs."""

    record: Record
    rtype: RecordType
    field_key: str
    on_delete: str


def _on_delete(rtype: RecordType, field_key: str) -> str:
    for raw in rtype.fields or []:
        if raw.get("key") == field_key:
            return str((raw.get("options") or {}).get("on_delete") or ON_DELETE_DEFAULT)
    return ON_DELETE_DEFAULT


async def referrers(
    db: AsyncSession, record: Record, *, include_deleted: bool = False
) -> list[Referrer]:
    """Who points at ``record``, and with what delete behaviour.

    Self-references are dropped: a record holding a relation to itself would
    otherwise make its own ``restrict`` field refuse its own delete, which is
    not a referential-integrity problem anybody has.

    **Every table set that can hold a referrer is asked** — see the loop below,
    and :mod:`sm_records.services._referrer_sets` for which those are.

    **A target is ``(target_type_id, target_uuid)``, never a uuid on its own.**
    §6.3 says the ref row "stores ``target_uuid`` and ``target_type_id``"; this
    reads the second half. Predicating on the uuid alone is invisible while
    every uuid is unique everywhere and wrong the moment one is not — a record
    borrowing another's uuid inherited its referrers, so ``restrict`` refused a
    delete nothing pointed at, ``cascade`` trashed an unrelated record and
    ``set_null`` blanked its field.

    Records already in the trash are dropped too, by the framework's
    soft-delete filter and not by a predicate here. Their index rows survive
    (§7.3) so they are found, but a trashed referrer neither blocks a
    ``restrict`` delete nor is followed by a ``cascade`` — it is not content
    anyone can currently reach, and cascading into the trash would rewrite
    rows a restore is supposed to bring back whole.

    ``include_deleted=True`` lifts that filter, and **only the read API passes
    it** (:func:`paged_referrers`): "what references this record" is a question
    about the whole graph, and ``ReferrerRead.is_deleted`` is in the contract
    precisely so the panel can show a trashed referrer greyed out rather than
    pretend it is not there. The delete path keeps the default, because
    including the trash there would change delete semantics — see above.
    """
    own = tables_of(record)
    out: list[Referrer] = []
    # **One query per table set that can hold a referrer, not one query.** A ref
    # row lives in the *referrer's* tables and names its target by
    # ``(target_uuid, target_type_id)``, so the rows pointing at this record are
    # scattered across every set that holds a type with a relation to it (Phase
    # 5 §6.4). A UNION would collapse them into one result and lose the one
    # thing the ids need to be read with — *which* record table each
    # ``record_id`` belongs to — so the loop keeps each set's ids with that
    # set's class. The sets come back in ``table_sets()`` order, which is why
    # that order is the global set first and then alphabetical: adding a
    # collection must not reorder an existing referrer list.
    for tables in await referring_sets(db, record.type_id):
        ref = tables.index[IndexKind.REF]
        rows = (
            await db.execute(
                select(ref.record_id, ref.field_key).where(
                    ref.target_uuid == record.uuid, ref.target_type_id == record.type_id
                )
            )
        ).all()
        pairs = {
            (int(rid), str(key))
            for rid, key in rows
            # A record referencing itself is dropped, and "itself" is a row in
            # *this* set with this id — two collections can hold the same id.
            if not (tables is own and int(rid) == record.id)
        }
        if not pairs:
            continue
        records = await _by_id(
            db, tables.record, {rid for rid, _ in pairs}, include_deleted=include_deleted
        )
        types = await _by_id(db, RecordType, {r.type_id for r in records.values()})
        for record_id, field_key in sorted(pairs):
            referring = records.get(record_id)
            rtype = types.get(referring.type_id) if referring is not None else None
            if referring is None or rtype is None:
                continue
            out.append(Referrer(referring, rtype, field_key, _on_delete(rtype, field_key)))
    return out


async def _by_id(
    db: AsyncSession, model: Any, ids: Iterable[int], *, include_deleted: bool = False
) -> dict[int, Any]:
    ids = list(ids)
    if not ids:
        return {}
    stmt = select(model).where(model.id.in_(ids))
    if include_deleted:
        stmt = stmt.execution_options(include_deleted=True)
    rows = (await db.execute(stmt)).scalars().all()
    return {row.id: row for row in rows}


def field_label(rtype: RecordType, field_key: str) -> str:
    """The referring field's label, from the *referring* type's definition.

    Falls back to the key: a definition written before labels were required,
    or a field deleted since (its index rows survive until the record is
    rewritten), still has to render as something in the panel.
    """
    for raw in rtype.fields or []:
        if raw.get("key") == field_key:
            return str(raw.get("label") or field_key)
    return field_key


def _key(ref: Referrer) -> tuple[str | None, int]:
    """What makes two referrer rows the same *record*.

    The id alone does not: two collections number their records independently,
    so ``(collection, id)`` is the identity and an id-keyed set would silently
    merge a global record with a collection one (Phase 5 §6.4).
    """
    return (ref.rtype.collection, ref.record.id)


def _distinct_records(refs: Iterable[Referrer]) -> int:
    """How many *records* these referrer rows represent.

    One definition of "how many things reference this", used by both the
    panel's ``total`` and the editor's badge. A record pointing at the target
    from two relation fields is two rows in ``records_index_ref`` and two
    entries in ``items`` — the panel names the field, so it has to be — but
    it is **one** record, and a badge reading "Referenced by 2" over a list
    of one record is a disagreement nobody can act on.
    """
    return len({_key(ref) for ref in refs})


async def paged_referrers(
    db: AsyncSession,
    record: Record,
    *,
    roles: Sequence[str] | None = None,
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[Referrer], int, int]:
    """One page of "what references this record": ``(items, total, hidden)``.

    Three numbers, each with its own definition and none of them derivable
    from another:

    * ``total`` counts every referring **record** — live, trashed, and the
      ones this caller may not see (:func:`_distinct_records`). A count that
      shrank per caller would make the delete dialog's "3 records reference
      this" disagree with what the delete actually refuses.
    * ``hidden`` is how many of those the caller may not view, so the panel
      can say "and 2 you cannot see" rather than leaving the reader to
      subtract and guess. The count was always inferable from ``total``; what
      was not, and must not be, is *which*.
    * ``items`` is the visible rows, and the page window is taken **over the
      visible set**. Windowing before the role filter (which is what this
      used to do) made ``page_size=1`` an exact oracle: an empty page with a
      non-zero total said "slot *n* is a row you may not see", and since the
      list is sorted by insertion, the positions ordered the hidden records
      against the visible ones.

    The window is applied in Python rather than in SQL because the underlying
    query is already one indexed lookup over ``records_index_ref`` plus two
    id-keyed loads: the row count here is "how many records reference one
    record", which is bounded by the graph an editor built by hand.
    """
    rows = await referrers(db, record, include_deleted=True)
    visible = [ref for ref in rows if not role_blocked(ref.rtype, roles)]
    total = _distinct_records(rows)
    offset = max(page - 1, 0) * page_size
    return visible[offset : offset + page_size], total, total - _distinct_records(visible)


async def referrer_count(db: AsyncSession, record: Record) -> int:
    """The editor's "Referenced by" badge: **the same number** the panel's
    ``total`` reports, from the same helper.

    It was one ``COUNT`` over ``records_index_ref`` and cheaper for it, and
    cheaper was the whole problem: counting index rows counted a referring
    record once per relation field, and counted rows whose record no longer
    exists at all. The badge is what a reader compares against the panel they
    open next, so the two have to answer the same question —
    :func:`paged_referrers` is where that question is defined.

    Still deliberately *not* filtered by the caller's roles or by the trash:
    the badge is a prompt to open the panel, where ``hidden`` says how much
    of it is not for this reader.
    """
    return _distinct_records(await referrers(db, record, include_deleted=True))
