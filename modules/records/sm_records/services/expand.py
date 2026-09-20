"""``?expand=`` — resolving what a relation field points at (design §9).

The forward half of relations, and the one the API makes opt-in: a read
returns the stored ``{"type": ..., "uuid": ...}`` untouched unless the caller
names the field, at which point this resolves it *one* level and no further.

Four rules, all of them load-bearing:

* **One batched query per named field, for the whole page.** The list screen
  expands every relation column it renders (§9), so a per-row lookup would
  make a page of fifty records fifty queries per column. Every uuid a field
  holds across the page is collected first and read in one ``IN``.
* **Depth one.** An expanded target's own relations stay bare. Depth > 1 is
  not a parameter that was left out — it needs a cycle guard, and a
  user-defined graph has cycles.
* **A missing target is flagged, never fatal.** Trashed and purged both read
  back as ``dangling`` (:func:`~sm_records.contracts.relations.expanded_ref`),
  because §9 says a restorable delete must not break what references it. The
  lookup runs with ``include_deleted`` so a trashed row is *found* and marked
  by this pass — a second query to tell "trashed" from "purged" apart would be
  a query per read to produce the same word. So do the two things a payload
  can hold that are not a resolvable reference: an entry that is not a
  ``{"type", "uuid"}`` object at all, and one whose uuid is not a record of
  the *declared* target type. Both keep their slot (:func:`_refs`), because
  a to-many expansion is rendered positionally against ``data``.
* **A target the caller may not see is ``restricted``, decided from the
  field's declared ``target_type`` alone.** Nothing about the row is read, so
  a restricted expansion leaks neither its content nor whether the uuid still
  exists. The predicate is ``_common.role_blocked`` — the same one
  ``deps.check_type_roles`` raises on, so the read surface cannot be more
  permissive than the write surface.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.constants import MAX_DISPLAY_TITLE_LEN
from sm_records.contracts.relations import ExpandedRef, expanded_ref
from sm_records.index.query import QueryError
from sm_records.models import Record, RecordType
from sm_records.schema.types import FieldType
from sm_records.services._common import role_blocked

__all__ = ["ExpandedMap", "expand", "relation_field_keys"]

ExpandedMap = dict[str, dict[str, list[ExpandedRef]]]
"""``{record uuid: {field key: [ExpandedRef, ...]}}`` — what fills
``RecordRead.expanded``. Keyed by uuid and not by row id because that is the
identifier the contract, the payload and the URL all speak."""

_RELATION = FieldType.RELATION.value


def _relation_defs(rtype: RecordType) -> dict[str, dict[str, Any]]:
    """The type's ``relation`` fields, by key, as stored JSON.

    The raw definitions rather than ``FieldDefinition`` objects: a read must
    not fail because some *other* field of the type no longer validates, and
    ``field_defs`` validates the lot.
    """
    return {
        str(raw.get("key")): raw
        for raw in (rtype.fields or [])
        if raw.get("type") == _RELATION and raw.get("key")
    }


def relation_field_keys(rtype: RecordType) -> list[str]:
    """Every relation field of the type, in declaration order.

    What the admin screens expand: §9's "the generic list screen is the one
    caller that always passes it" — a column of bare UUIDs is not a list
    screen, and the editor has to show a title next to a relation picker.
    """
    return list(_relation_defs(rtype))


def _refs(record: Record, field_key: str, declared: str) -> list[tuple[str, str, bool]]:
    """``(type key, uuid, resolvable)`` per stored entry, **in payload order**.

    A to-many field's expansion has to line up with ``data[key]``
    positionally — the UI renders the two together — so the list is built
    from the payload and never from the index rows, which carry no order.

    **Every entry produces one tuple, including one that is not a reference
    at all.** A ``null`` (or anything else that is not ``{"type", "uuid"}``)
    used to be skipped, which shortened the list and put every later
    expansion one slot out of step with the payload it is rendered beside —
    ``expanded[1]`` labelling ``data[2]``. Such an entry is marked
    unresolvable here and comes back ``dangling``, carrying the stored value
    stringified as its ``uuid`` so the position is visible rather than
    silently plausible. Writes cannot create one any more
    (``schema._builders._check_ref_list``); rows written before that check
    can.

    The stored ``type`` is echoed when the payload has one and the field's
    declared target substituted when it does not. The two are allowed to
    disagree on a row written before ``_relations.check_targets`` existed,
    and :func:`_targets` is what refuses to resolve such a row.
    """
    value = (record.data or {}).get(field_key)
    items = value if isinstance(value, list) else [value]
    out: list[tuple[str, str, bool]] = []
    for item in items:
        if isinstance(item, dict) and item.get("uuid"):
            out.append((str(item.get("type") or declared), str(item["uuid"]), True))
        else:
            out.append((declared, str(item)[:MAX_DISPLAY_TITLE_LEN], False))
    return out


def _check_keys(rtype: RecordType, field_keys: Sequence[str], relations: dict[str, Any]) -> None:
    """Refuse a key that is not a relation field of this type, by name.

    ``QueryError`` and not an ad-hoc exception: ``?expand=`` is the same kind
    of promise ``?filter=`` is — "this field key means something on this
    type" — and the endpoint layer already turns that refusal into a 400
    naming the field and the reason (``endpoints/api/_errors.py``).
    """
    declared = {str(raw.get("key")) for raw in (rtype.fields or []) if raw.get("key")}
    for key in field_keys:
        if key in relations:
            continue
        if key not in declared:
            raise QueryError(key, "unknown", f"{key!r} is not a field of {rtype.key!r}")
        raise QueryError(
            key, "not_a_relation", f"{key!r} is not a relation field, so it cannot be expanded"
        )


async def _types_by_key(db: AsyncSession, keys: set[str]) -> dict[str, RecordType]:
    """The target types, in one statement — they decide ``restricted``."""
    if not keys:
        return {}
    rows = (await db.execute(select(RecordType).where(RecordType.key.in_(keys)))).scalars().all()
    return {row.key: row for row in rows}


async def _targets(db: AsyncSession, uuids: list[str], type_id: int) -> dict[str, Record]:
    """Every target of one field, in one ``IN``.

    ``include_deleted``: see the module docstring — a trashed target has to be
    *found* here, or telling it from a purged one costs a second query per
    read to produce the same ``dangling`` either way.

    ``type_id`` is the **declared** target type's, and it is a predicate and
    not a filter applied afterwards: ``restricted`` is decided from the
    declared target alone, so a row found under any *other* type would carry
    a decision that was never made about it — which is how a stored ref
    saying ``{"type": "secret", ...}`` on a field declared ``author`` came
    back with the secret record's title and ``restricted: false``. A uuid
    that is not a record of the declared type is simply not found, and reads
    as ``dangling`` like every other unresolvable reference (§9).
    """
    if not uuids:
        return {}
    stmt = (
        select(Record)
        .where(Record.uuid.in_(uuids), Record.type_id == type_id)
        .execution_options(include_deleted=True)
    )
    return {row.uuid: row for row in (await db.execute(stmt)).scalars().all()}


async def expand(
    db: AsyncSession,
    rtype: RecordType,
    records: Sequence[Record],
    field_keys: Sequence[str],
    *,
    roles: Sequence[str] | None = None,
) -> ExpandedMap:
    """Resolve ``field_keys`` for every record in ``records``.

    ``roles`` is the caller's role list (``deps.caller_roles``); ``None`` means
    no caller at all — a CLI or background path — and resolves everything, the
    same reading ``role_blocked`` gives it everywhere else.

    Statement count is ``1 + (number of fields actually read)``: one for the
    target types, one per named field. A field whose target type this caller
    may not see is not read at all, so it costs nothing and reveals nothing.
    """
    relations = _relation_defs(rtype)
    _check_keys(rtype, field_keys, relations)
    out: ExpandedMap = {record.uuid: {} for record in records}
    if not field_keys or not records:
        return out

    declared_targets = {
        key: str((relations[key].get("options") or {}).get("target_type") or "")
        for key in field_keys
    }
    types = await _types_by_key(db, set(declared_targets.values()))

    for key in field_keys:
        target_type = types.get(declared_targets[key])
        restricted = target_type is not None and role_blocked(target_type, roles)
        per_record = {record.uuid: _refs(record, key, declared_targets[key]) for record in records}
        wanted = {uuid for refs in per_record.values() for _, uuid, ok in refs if ok}
        # No declared target type (it names a type that no longer exists):
        # nothing can be resolved *as* it, so nothing is read — the same
        # answer the type predicate in ``_targets`` gives for a mismatch.
        found = (
            {}
            if restricted or target_type is None
            else await _targets(db, sorted(wanted), target_type.id)
        )
        for record in records:
            out[record.uuid][key] = [
                expanded_ref(
                    type_key,
                    uuid,
                    _live(found.get(uuid)) if resolvable else None,
                    restricted=restricted,
                )
                for type_key, uuid, resolvable in per_record[record.uuid]
            ]
    return out


def _live(target: Record | None) -> Record | None:
    """A trashed row is not a resolvable target — §9's ``dangling``, reached
    without the second lookup that telling it from a purge would cost."""
    return None if target is None or target.is_deleted else target
