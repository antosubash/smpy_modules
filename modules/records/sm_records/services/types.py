"""Record Type CRUD — the schema half of the module.

A type's ``fields`` is a JSON column on one row, so changing it is an
``UPDATE`` and never DDL (design §4, §8.1). What that ``UPDATE`` is allowed to
be is the whole of §8, and Phase 3 ships it: a ``fields`` edit on a type that
already holds records is classified, dry-run and — if it would leave rows
invalid — refused with a report, by
:mod:`sm_records.services.schema_change`. ``update_type`` routes there rather
than re-implementing any of it; what stays here is the row lifecycle around
the schema (labels, flags, the delete) and the fast path for a type with no
records, where there is nothing to classify against and nothing to reindex.

Phase 1's blanket refusal — a type that held any record had read-only
``fields`` — is gone from this path, and so is the exception that expressed
it: nothing raises it, so keeping it importable would only leave an error the
endpoints layer maps and no code path can produce.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.collections import collections
from sm_records.constants import MAX_KEY_LEN, RESERVED_TYPE_KEYS, TYPE_KEY_PATTERN
from sm_records.models import RecordType, RecordTypeRevision
from sm_records.schema.types import FieldType
from sm_records.services._common import record_count, record_counts, type_id_map
from sm_records.services._schema import check_pointers, check_targets, normalise, snapshot
from sm_records.services._type_update import update_type
from sm_records.services.errors import (
    Conflict,
    NotFound,
    ReferencedByOthers,
    ValidationFailed,
)
from sm_records.services.records import purge_type_records
from sm_records.settings import RecordsSettings

__all__ = [
    "create_type",
    "delete_type",
    "get_type",
    "get_type_by_id",
    "list_types",
    "record_count",
    "record_counts",
    "type_id_map",
    "update_type",
]

_KEY_RE = re.compile(TYPE_KEY_PATTERN)


async def list_types(db: AsyncSession) -> list[RecordType]:
    stmt = select(RecordType).order_by(RecordType.label, RecordType.key)
    return list((await db.execute(stmt)).scalars().all())


async def get_type(db: AsyncSession, key: str) -> RecordType:
    rtype = (await db.execute(select(RecordType).where(RecordType.key == key))).scalars().first()
    if rtype is None:
        raise NotFound(f"no record type with key {key!r}")
    return rtype


async def get_type_by_id(db: AsyncSession, type_id: int) -> RecordType:
    rtype = (await db.execute(select(RecordType).where(RecordType.id == type_id))).scalars().first()
    if rtype is None:
        raise NotFound(f"no record type with id {type_id!r}")
    return rtype


def _check_collection(collection: str | None) -> None:
    """A type may only be created in a collection this process declares
    (Phase 5 §6.2).

    422 and not 409: the name is a value in the request body that does not
    name anything, which is what 422 is for, and the message lists what *is*
    declared because the answer is a property of the host's code rather than of
    anything the caller can create. ``None`` — the global tables — is always
    valid and is what a host that declares none can ever use.
    """
    if collection is None:
        return
    declared = collections()
    if collection not in declared:
        named = ", ".join(declared) or "none — this host declares no collections"
        raise ValidationFailed(
            f"collection {collection!r} is not declared by this host (declared: {named}); "
            "a collection's tables come from declare_collection() at import time",
            [{"field": "collection", "message": f"{collection!r} is not a declared collection"}],
        )


async def create_type(
    db: AsyncSession,
    *,
    key: str,
    label: str,
    settings: RecordsSettings,
    label_plural: str | None = None,
    description: str | None = None,
    icon: str | None = None,
    fields_raw: list[dict[str, Any]] | None = None,
    display_field: str | None = None,
    slug_field: str | None = None,
    is_public: bool = False,
    translatable: bool = False,
    allowed_roles: list[str] | None = None,
    collection: str | None = None,
    actor: str | None = None,
) -> RecordType:
    if key in RESERVED_TYPE_KEYS:
        raise ValidationFailed(
            f"key {key!r} is reserved: it would shadow a records screen",
            [{"field": "key", "message": "reserved"}],
        )
    if not _KEY_RE.match(key or "") or len(key) > MAX_KEY_LEN:
        raise ValidationFailed(
            f"key must match {TYPE_KEY_PATTERN} and be at most {MAX_KEY_LEN} characters",
            [{"field": "key", "message": f"{key!r} is not a valid type key"}],
        )
    if (await db.execute(select(RecordType.id).where(RecordType.key == key))).scalars().first():
        raise Conflict(f"a record type with key {key!r} already exists")

    _check_collection(collection)
    defs, fields = normalise(fields_raw or [], settings)
    check_pointers(defs, display_field, slug_field)
    await check_targets(db, defs, key)

    rtype = RecordType(
        key=key,
        label=label,
        label_plural=label_plural or label,
        description=description,
        icon=icon,
        fields=fields,
        schema_version=1,
        version=1,
        display_field=display_field,
        slug_field=slug_field,
        is_public=is_public,
        translatable=translatable,
        allowed_roles=list(allowed_roles or []),
        collection=collection,
        created_by=actor,
    )
    db.add(rtype)
    await db.flush()
    await snapshot(db, rtype, actor)
    return rtype


async def delete_type(db: AsyncSession, rtype: RecordType, *, confirm_record_count: int) -> None:
    """Delete a type and everything stored against it.

    ``confirm_record_count`` has to match what the type actually holds (§8.9):
    the count is what the operator was shown, and a mismatch means content
    arrived between the dialog and the click. Refusing is the only honest
    answer — the confirmation they gave was for a different amount of data.

    "Holds" counts the trash, because :func:`purge_type_records` purges it —
    a type with nothing live and fifty restorable records used to be deletable
    on a confirmation of ``0``, which destroyed all fifty. ``TypeRead`` carries
    ``trashed_record_count`` alongside ``record_count`` so the dialog can show
    the operator the number this check will actually compare against.
    """
    held = await record_count(db, rtype, include_deleted=True)
    if confirm_record_count != held:
        raise Conflict(
            f"type {rtype.key!r} holds {held} record(s), not {confirm_record_count}; "
            "reload and confirm again"
        )
    referring = [
        other.key
        for other in await list_types(db)
        if other.id != rtype.id
        and any(
            raw.get("type") == FieldType.RELATION.value
            and (raw.get("options") or {}).get("target_type") == rtype.key
            for raw in other.fields or []
        )
    ]
    if referring:
        raise ReferencedByOthers(
            f"type {rtype.key!r} is the target of a relation on {referring}", referring
        )
    await purge_type_records(db, rtype)
    # Explicit, not via the FK's ON DELETE CASCADE: SQLite leaves foreign keys
    # unenforced unless the pragma is on, so the cascade would clean up on
    # Postgres and orphan rows on the default dev backend.
    await db.execute(sa_delete(RecordTypeRevision).where(RecordTypeRevision.type_id == rtype.id))
    await db.delete(rtype)
    await db.flush()
