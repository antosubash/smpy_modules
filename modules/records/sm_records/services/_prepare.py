"""The shared front half of both record write paths — validate, lock, check.

Split out of :mod:`sm_records.services.records` for the 300-line cap, along
the seam that was already there: that module is what a create and an update
each *do*, and this is the part they do identically before they diverge.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import RecordType
from sm_records.schema.compile import from_stored
from sm_records.schema.fields import FieldDefinition
from sm_records.services import _claims, _payload, _relations
from sm_records.services._common import type_id_map
from sm_records.settings import RecordsSettings

__all__ = ["Prepared", "prepare"]


class Prepared(NamedTuple):
    """What both write paths need out of :func:`prepare`.

    ``types`` rides along rather than being looked up again: ``{key: id}`` is
    read once here for the relation check and is the same mapping the index
    writer's resolver needs (``index.providers.TypeResolver``), which used to
    make ``SELECT key, id FROM records_type`` a twice-per-write statement. It
    is an argument and not a module-level cache because types are created and
    deleted at runtime, and a stale id would reach the one thing that must not
    have one — the ``relation`` rows ``on_delete`` is enforced from (§9).
    """

    defs: list[FieldDefinition]
    values: dict[str, Any]
    stored: dict[str, Any]
    types: dict[str, int]


async def prepare(
    db: AsyncSession,
    rtype: RecordType,
    data: dict[str, Any],
    settings: RecordsSettings,
    exclude_id: int | None,
    group: str,
    previous: dict[str, Any] | None = None,
) -> Prepared:
    """Validate, then the two checks no database constraint can make.

    The type row is locked before them and not before validation: the lock
    exists to close the check-then-act window of §7.8, and holding it across
    pydantic's work would serialise writes on a type for no benefit.

    ``group`` is the write's translation group, known by both write paths
    before they call: siblings are exempt from each other's ``unique`` claims
    (:func:`sm_records.services._claims.ensure_unique`).

    ``previous`` is the row's payload as it is stored *now* — ``None`` on a
    create, which has no before. It is read through ``from_stored`` with the
    same definitions the write validates against, so what reaches
    ``ensure_unique`` is the pair of coerced views it compares, and a write
    that leaves a ``unique`` value alone is not made to re-claim it. That is
    what keeps a record saveable after a ``unique`` flag was forced onto a
    field that already held duplicates.
    """
    defs = _payload.field_defs(rtype)
    values, stored = _payload.validate(
        rtype, defs, data, max_payload_bytes=settings.max_payload_bytes
    )
    await _claims.lock_type(db, rtype)
    types = await type_id_map(db)
    await _relations.check_targets(db, defs, values, types)
    await _claims.ensure_unique(
        db,
        rtype,
        defs,
        values,
        exclude_id=exclude_id,
        exclude_group=group,
        previous=None if previous is None else from_stored(defs, previous),
    )
    return Prepared(defs, values, stored, types)
