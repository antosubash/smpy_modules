"""Record Type CRUD — the schema half of the module.

A type's ``fields`` is a JSON column on one row, so changing it is an
``UPDATE`` and never DDL (design §4, §8.1). What that ``UPDATE`` is allowed to
be is the whole of §8, and Phase 1 ships exactly one rule of it: **a type's
``fields`` are read-only once it holds a record** (§16). The classification,
the dry-run and the index-table migration arrive in Phase 3; until they do,
an unguarded ``fields`` write on a populated type is the data loss they exist
to prevent, so :class:`~sm_records.services.errors.FieldsLocked` stands in
for them.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.constants import MAX_KEY_LEN, TYPE_KEY_PATTERN
from sm_records.models import Record, RecordType, RecordTypeRevision
from sm_records.schema.types import FieldType
from sm_records.services._common import guarded_bump, reload, type_id_map
from sm_records.services._payload import field_defs
from sm_records.services._schema import check_pointers, check_targets, normalise, snapshot
from sm_records.services.errors import (
    Conflict,
    FieldsLocked,
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
    "type_id_map",
    "update_type",
]

_KEY_RE = re.compile(TYPE_KEY_PATTERN)

#: Everything ``update_type`` accepts. ``key`` is absent on purpose — it is in
#: URLs, in the public API and in every relation target, so a rename would
#: strand all three (design §5).
_EDITABLE = frozenset(
    {
        "label",
        "label_plural",
        "description",
        "icon",
        "fields_raw",
        "display_field",
        "slug_field",
        "is_public",
        "allowed_roles",
    }
)

#: A change to any of these is snapshotted in ``records_type_revision``. The
#: rest are labels: they cannot damage a record, and a revision per typo would
#: bury the schema edits the table exists to make reversible.
_SNAPSHOT_TRIGGERS = ("fields_raw", "display_field", "slug_field")


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


async def record_count(db: AsyncSession, rtype: RecordType) -> int:
    """How many live records the type holds.

    Not a column: the previous draft denormalised it and §5 removed it,
    because a ``COUNT`` over an indexed column is cheap and cannot go stale.
    ``func.count(Record.id)`` rather than a bare ``count()`` so the statement
    names the mapper — that is what the framework's soft-delete filter attaches
    to, and without it this would count the trash.
    """
    stmt = select(func.count(Record.id)).where(Record.type_id == rtype.id)
    return int((await db.execute(stmt)).scalar_one())


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
    allowed_roles: list[str] | None = None,
    actor: str | None = None,
) -> RecordType:
    if not _KEY_RE.match(key or "") or len(key) > MAX_KEY_LEN:
        raise ValidationFailed(
            f"key must match {TYPE_KEY_PATTERN} and be at most {MAX_KEY_LEN} characters",
            [{"field": "key", "message": f"{key!r} is not a valid type key"}],
        )
    if (await db.execute(select(RecordType.id).where(RecordType.key == key))).scalars().first():
        raise Conflict(f"a record type with key {key!r} already exists")

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
        allowed_roles=list(allowed_roles or []),
        created_by=actor,
    )
    db.add(rtype)
    await db.flush()
    await snapshot(db, rtype, actor)
    return rtype


async def update_type(
    db: AsyncSession,
    rtype: RecordType,
    *,
    expected_version: int,
    settings: RecordsSettings,
    actor: str | None = None,
    **changes: Any,
) -> RecordType:
    """Edit a type under optimistic concurrency (design §8.6).

    ``version`` is bumped by every accepted edit; ``schema_version`` only by a
    change to ``fields``, because it is what record rows stamp themselves with
    and what the compiled-model cache is keyed on. Bumping it for a label edit
    would invalidate every cached validator and mark every record stale for
    nothing.
    """
    unknown = sorted(set(changes) - _EDITABLE)
    if unknown:
        problem = (
            "key is immutable — it is in URLs, the API and every relation target"
            if "key" in unknown
            else f"cannot change {unknown}"
        )
        raise ValidationFailed(problem, [{"field": unknown[0], "message": problem}])

    fields: list[dict[str, Any]] | None = None
    if "fields_raw" in changes:
        defs, fields = normalise(changes.pop("fields_raw"), settings)
        if fields == list(rtype.fields or []):
            fields = None
        else:
            held = await record_count(db, rtype)
            if held:
                raise FieldsLocked(rtype.key, held)
            await check_targets(db, defs, rtype.key)
    else:
        defs = field_defs(rtype)

    check_pointers(
        defs,
        changes.get("display_field", rtype.display_field),
        changes.get("slug_field", rtype.slug_field),
    )

    if not await guarded_bump(db, RecordType, rtype.id, expected_version):
        raise Conflict(
            f"record type {rtype.key!r} has changed since it was read",
            current=await reload(db, RecordType, rtype.id),
        )

    needs_snapshot = fields is not None or any(n in changes for n in _SNAPSHOT_TRIGGERS)
    for name, value in changes.items():
        setattr(rtype, name, value)
    if fields is not None:
        rtype.fields = fields
        rtype.schema_version = rtype.schema_version + 1
    rtype.version = expected_version + 1
    rtype.updated_by = actor
    db.add(rtype)
    await db.flush()
    if needs_snapshot:
        await snapshot(db, rtype, actor)
    return rtype


async def delete_type(db: AsyncSession, rtype: RecordType, *, confirm_record_count: int) -> None:
    """Delete a type and everything stored against it.

    ``confirm_record_count`` has to match what the type actually holds (§8.9):
    the count is what the operator was shown, and a mismatch means content
    arrived between the dialog and the click. Refusing is the only honest
    answer — the confirmation they gave was for a different amount of data.
    """
    held = await record_count(db, rtype)
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
