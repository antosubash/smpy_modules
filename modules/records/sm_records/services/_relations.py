"""Relations: checking a target exists on write, and finding referrers on delete.

There is no foreign key behind a ``relation`` field — the target is named by
``{"type": ..., "uuid": ...}`` inside a JSON payload — so both halves of what a
foreign key would give you are enforced here (design §9). The second half is
only cheap because ``records_index_ref`` exists: "what references this record?"
is one indexed query rather than a scan of every payload in the install.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import Record, RecordType, table_sets, tables_of
from sm_records.schema.fields import ON_DELETE_DEFAULT, FieldDefinition
from sm_records.schema.types import FieldType, IndexKind
from sm_records.services._common import role_blocked
from sm_records.services.errors import ValidationFailed


@dataclass(frozen=True, slots=True)
class Referrer:
    """One record pointing at the record being deleted, and what that costs."""

    record: Record
    rtype: RecordType
    field_key: str
    on_delete: str


def _targets(
    defs: list[FieldDefinition], values: dict[str, Any]
) -> list[tuple[str, str, str, str]]:
    """``(field key, declared target type, payload type, target uuid)`` per reference.

    The payload's own ``type`` travels alongside the declared one because the
    two are allowed to disagree and must not be: see :func:`check_targets`.
    """
    out: list[tuple[str, str, str, str]] = []
    for field in defs:
        if field.type is not FieldType.RELATION:
            continue
        value = values.get(field.key)
        if value is None:
            continue
        declared = str(field.options.get("target_type") or "")
        items = value if isinstance(value, list) else [value]
        for item in items:
            if isinstance(item, dict) and item.get("uuid"):
                claimed = str(item.get("type") or "")
                out.append((field.key, declared, claimed, str(item["uuid"])))
    return out


async def check_targets(
    db: AsyncSession,
    defs: list[FieldDefinition],
    values: dict[str, Any],
    type_ids: dict[str, int],
) -> None:
    """Every relation value must name a live record of the declared type.

    Four failures, one message each, because a generic form renders them
    against the field: a payload naming a *different* type than the field
    declares, a payload pointing at a type the field was not declared for, a
    uuid that does not exist, and a uuid that exists as a record of some
    *other* type. A soft-deleted target counts as missing — the soft-delete
    filter applies to the lookup — which is deliberate: design §9 lets an
    *existing* reference dangle through a trash-and-restore cycle, but a new
    write should not be allowed to point at something already in the bin.

    The first of those is not cosmetic. ``records_index_ref`` is written
    against the declared target, and a payload whose ``type`` names something
    else used to pass this check on the declared type's uuid while the writer
    indexed — or failed to index — under the payload's key. The reference then
    existed in the document and nowhere in the index, so ``restrict`` saw no
    referrer and the target was deletable out from under it.
    """
    wanted = _targets(defs, values)
    if not wanted:
        return
    uuids = {uuid for *_, uuid in wanted}
    # Every table set, because a relation may point into a collection or out of
    # one (Phase 5 §6.4): the declared target type decides which set holds the
    # target, and this check runs before that type has been resolved to a row.
    # A uuid is unique inside each set and generated as a uuid4, so the merged
    # mapping cannot hold two different records under one key in practice.
    live: dict[str, int] = {}
    for tables in table_sets():
        cls = tables.record
        rows = (await db.execute(select(cls.uuid, cls.type_id).where(cls.uuid.in_(uuids)))).all()
        live.update({uuid: int(type_id) for uuid, type_id in rows})

    errors: list[dict[str, str]] = []
    for key, declared, claimed, uuid in wanted:
        target_id = type_ids.get(declared)
        if claimed and claimed != declared:
            errors.append(
                {
                    "field": key,
                    "message": f"field {key!r} points at {declared!r}, not {claimed!r}",
                }
            )
        elif target_id is None:
            errors.append({"field": key, "message": f"target type {declared!r} does not exist"})
        elif uuid not in live:
            errors.append({"field": key, "message": f"no record with uuid {uuid!r}"})
        elif live[uuid] != target_id:
            errors.append({"field": key, "message": f"record {uuid!r} is not a {declared!r}"})
    if errors:
        raise ValidationFailed("; ".join(item["message"] for item in errors), errors)


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

    **Every declared table set is asked** — see the loop below.

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
    # **One query per declared table set, not one query.** A ref row lives in
    # the *referrer's* tables and names its target by ``(target_uuid,
    # target_type_id)``, so the rows pointing at this record are scattered across
    # every set that holds a type with a relation to it (Phase 5 §6.4). A UNION
    # would collapse them into one result and lose the one thing the ids need to
    # be read with — *which* record table each ``record_id`` belongs to — so the
    # loop keeps each set's ids with that set's class. It is the global set plus
    # one query per declared collection, in ``table_sets()`` order, which is why
    # that order is the global set first and then alphabetical: adding a
    # collection must not reorder an existing referrer list.
    for tables in table_sets():
        ref = tables.index[IndexKind.REF]
        rows = (
            await db.execute(
                select(ref.record_id, ref.field_key).where(ref.target_uuid == record.uuid)
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
