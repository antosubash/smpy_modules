"""Relations: checking on write that a target exists and is what it claims.

There is no foreign key behind a ``relation`` field — the target is named by
``{"type": ..., "uuid": ...}`` inside a JSON payload — so both halves of what a
foreign key would give you are enforced in this package (design §9). This
module is the **write** half. The other half, "what references this record",
is :mod:`sm_records.services._referrers`, split out for the 300-line cap and
re-exported here so callers still import one module; it is only cheap because
``records_index_ref`` exists, which makes that question one indexed query
rather than a scan of every payload in the install.

Both halves key a target on ``(target_type_id, target_uuid)`` and resolve the
table set from the declared type (Phase 5 §6.4). A uuid alone is not an
identity: it is unique inside each record table and nothing in the database
spans them, so every lookup that used one acted on the wrong row the moment two
sets held the same value — see :mod:`sm_records.services._uuids`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import table_sets
from sm_records.schema.fields import FieldDefinition
from sm_records.schema.types import FieldType

# Re-exported: the referrer half of §9 lives in its own module for the file
# cap, and every caller still imports ``_relations``.
from sm_records.services._referrers import (
    Referrer,
    field_label,
    paged_referrers,
    referrer_count,
    referrers,
)
from sm_records.services.errors import ValidationFailed

__all__ = [
    "Referrer",
    "check_targets",
    "field_label",
    "paged_referrers",
    "referrer_count",
    "referrers",
]


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
    #
    # **Keyed by ``(uuid, type_id)``, never by uuid alone.** A merged uuid →
    # type map let the last set asked overwrite the first, so one record
    # borrowing another's uuid made every later write pointing at the original
    # a 422 saying it "is not a hall". ``seen`` is the other half of the
    # answer: whether the uuid exists at all.
    live: set[tuple[str, int]] = set()
    seen: set[str] = set()
    for tables in table_sets():
        cls = tables.record
        rows = (await db.execute(select(cls.uuid, cls.type_id).where(cls.uuid.in_(uuids)))).all()
        for found_uuid, type_id in rows:
            live.add((str(found_uuid), int(type_id)))
            seen.add(str(found_uuid))

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
        elif (uuid, target_id) in live:
            continue
        elif uuid not in seen:
            errors.append({"field": key, "message": f"no record with uuid {uuid!r}"})
        else:
            errors.append({"field": key, "message": f"record {uuid!r} is not a {declared!r}"})
    if errors:
        raise ValidationFailed("; ".join(item["message"] for item in errors), errors)
