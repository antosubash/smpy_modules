"""Relations: checking a target exists on write, and finding referrers on delete.

There is no foreign key behind a ``relation`` field — the target is named by
``{"type": ..., "uuid": ...}`` inside a JSON payload — so both halves of what a
foreign key would give you are enforced here (design §9). The second half is
only cheap because ``records_index_ref`` exists: "what references this record?"
is one indexed query rather than a scan of every payload in the install.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import IndexRef, Record, RecordType
from sm_records.schema.fields import ON_DELETE_DEFAULT, FieldDefinition
from sm_records.schema.types import FieldType
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
    rows = (
        await db.execute(select(Record.uuid, Record.type_id).where(Record.uuid.in_(uuids)))
    ).all()
    live = {uuid: int(type_id) for uuid, type_id in rows}

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


async def referrers(db: AsyncSession, record: Record) -> list[Referrer]:
    """Who points at ``record``, and with what delete behaviour.

    Self-references are dropped: a record holding a relation to itself would
    otherwise make its own ``restrict`` field refuse its own delete, which is
    not a referential-integrity problem anybody has.

    Records already in the trash are dropped too, by the framework's
    soft-delete filter and not by a predicate here. Their index rows survive
    (§7.3) so they are found, but a trashed referrer neither blocks a
    ``restrict`` delete nor is followed by a ``cascade`` — it is not content
    anyone can currently reach, and cascading into the trash would rewrite
    rows a restore is supposed to bring back whole.
    """
    rows = (
        await db.execute(
            select(IndexRef.record_id, IndexRef.type_id, IndexRef.field_key).where(
                IndexRef.target_uuid == record.uuid
            )
        )
    ).all()
    pairs = {(int(rid), str(key)) for rid, _, key in rows if int(rid) != record.id}
    if not pairs:
        return []

    records = await _by_id(db, Record, {rid for rid, _ in pairs})
    types = await _by_id(db, RecordType, {r.type_id for r in records.values()})
    out: list[Referrer] = []
    for record_id, field_key in sorted(pairs):
        referring = records.get(record_id)
        rtype = types.get(referring.type_id) if referring is not None else None
        if referring is None or rtype is None:
            continue
        out.append(Referrer(referring, rtype, field_key, _on_delete(rtype, field_key)))
    return out


async def _by_id(db: AsyncSession, model: Any, ids: Iterable[int]) -> dict[int, Any]:
    ids = list(ids)
    if not ids:
        return {}
    rows = (await db.execute(select(model).where(model.id.in_(ids)))).scalars().all()
    return {row.id: row for row in rows}
