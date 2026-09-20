"""Which table sets can hold a row pointing at one record's type — S5.

Split from :mod:`sm_records.services._referrers` for the 300-line cap, along
the seam that module's own subject draws: it is the walk — who points at this
record, and what that costs them on delete — and this is the one question the
walk asks before it starts, which is about the *schema* rather than about any
record.

``referrers()`` used to ask every **declared** table set, so a host that
declared two collections paid three reads on every ``restrict`` delete and
every referrers panel even when both collections held nothing. That is linear
in declarations, and a host's declarations are its Alembic history, which only
ever grows.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.index.providers import virtual_fields
from sm_records.models import RecordType, TableSet, table_sets
from sm_records.schema.types import FieldType, IndexKind

__all__ = ["referring_sets"]


def _declares_a_relation_to(fields: Any, target_key: str) -> bool:
    """Does this type's stored ``fields`` point a relation at ``target_key``?

    Read off the raw JSON rather than through ``validate_fields``: this is a
    narrowing, so it must be *cheap* and it must never raise. A definition this
    module cannot parse simply does not match, and the type it belongs to fails
    loudly at its next read or write where it should.
    """
    return any(
        str(raw.get("type") or "") == FieldType.RELATION.value
        and str((raw.get("options") or {}).get("target_type") or "") == target_key
        for raw in (fields or [])
    )


async def referring_sets(db: AsyncSession, type_id: int) -> tuple[TableSet, ...]:
    """The table sets that can hold a row pointing at a record of ``type_id``.

    A ``records_index_ref`` row lives in the *referrer's* tables (§6.4), so the
    sets worth asking are the ones holding a type that declares a relation to
    this one — which ``records_type.fields`` answers for the whole install in
    one query. A host declaring ten collections and pointing relations at two
    then pays for two.

    **Three ways out, and all three return every set.** With no collection
    declared there is exactly one set, so the narrowing could only ever *add* a
    query — that is the default host, and it must not pay a statement for a
    feature it does not use. A ``type_id`` no ``records_type`` row carries is a
    record whose type has been deleted out from under it, which is not a case
    to answer by reading fewer tables. And a **provider** may project ``REF``
    entries for a virtual key (§7.6) on a type whose ``fields`` declare no
    relation at all, so the schema stops being the whole answer the moment one
    is registered: the narrowing is switched off rather than made wrong.

    **Not memoised**, although ``plan_delete`` walks a cascade one record at a
    time and asks this for each of them. A memo on ``Session.info`` would make
    the second call of a request free and the number a test can assert depend
    on how many calls came before it; it would also be one more place a schema
    edit and a delete in one session could disagree. What it would save is
    bounded: this query replaces up to one read *per declared collection* on
    every one of those records, so the walk is ahead by ``sets - 1 - relating``
    per record and behind by exactly one statement only on a host where every
    declared collection holds a type pointing at this one.
    """
    sets = table_sets()
    if len(sets) == 1 or any(field.kind is IndexKind.REF for field in virtual_fields().values()):
        return sets
    rows = (
        await db.execute(
            select(RecordType.id, RecordType.key, RecordType.collection, RecordType.fields)
        )
    ).all()
    target = next((str(key) for rid, key, _c, _f in rows if int(rid) == int(type_id)), None)
    if target is None:
        return sets
    holders = {
        collection
        for _rid, _key, collection, fields in rows
        if _declares_a_relation_to(fields, target)
    }
    return tuple(tables for tables in sets if tables.name in holders)
