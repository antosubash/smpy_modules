"""The one claim a record write makes that is **not** scoped to its type: its
``uuid``.

Phase 5 §6.4 says "``uuid`` remains globally unique across collections" and
then leaves it to uuid4 — each record table carries its own unique index, and
nothing in the database spans them. That is fine for generated identifiers and
not fine for supplied ones: the importer keeps a file's uuid verbatim so a
round trip is idempotent (§2), so importing a global type's export into a
collection type planted a duplicate deterministically — the §12 motivation for
collections in the first place.

Two layers answer that, and this module is the second. The first is that
everything resolving a record by uuid keys on ``(target_type_id, target_uuid)``
and resolves the table set from the type
(:mod:`sm_records.services._relations`, :mod:`sm_records.services.expand`,
:mod:`sm_records.services._delete_plan`), so a duplicate that already exists
cannot make a delete, a cascade or a relation check act on the wrong row. This
module is what stops one being created.

Its own file rather than a few functions in :mod:`sm_records.services._claims`
for the 300-line cap, and the seam is real: that module is what a write claims
about *the rest of its type* — a slug, a ``unique`` value — held by a lock on
the type row. A uuid is claimed against every table set in the install, and no
type lock covers that.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import RecordType, table_sets, tables_for

__all__ = ["uuid_claim_message", "uuids_claimed_elsewhere"]


def uuid_claim_message(uuid: str, collection: str | None) -> str:
    """Why a caller-supplied uuid is refused, naming where it is already used.

    ``collection`` is a :class:`~sm_records.models.TableSet` name — ``None``
    for the shared tables — so the sentence says "the global set" rather than
    printing ``None`` at an operator reading an import report.
    """
    where = "the global set" if collection is None else f"collection {collection!r}"
    return (
        f"uuid {uuid} already exists in {where}; a record's uuid is unique across every "
        "table set, so a file cannot create a record under one that is already in use"
    )


async def uuids_claimed_elsewhere(
    db: AsyncSession, rtype: RecordType, uuids: Iterable[str]
) -> dict[str, str | None]:
    """Which of ``uuids`` already name a record **outside** this type's tables.

    ``{uuid: collection name or None}``, one entry per uuid that is taken, the
    value naming the set holding it — see the module docstring for why.

    This type's **own** set is skipped: a uuid already in it is the ordinary
    match the importer resolves (an update, or "belongs to a different record
    type"), and reporting it here would replace a precise message with a vague
    one. ``include_deleted`` because a trashed record still owns its uuid until
    it is purged, exactly as it owns its slug.

    **Zero statements on a host that declares no collection** — ``table_sets()``
    is then this type's own set and nothing else — which is the §6.5 property
    this check has to keep.
    """
    wanted = {uuid for uuid in uuids if uuid}
    if not wanted:
        return {}
    own = tables_for(rtype)
    out: dict[str, str | None] = {}
    for tables in table_sets():
        if tables is own:
            continue
        cls = tables.record
        stmt = select(cls.uuid).where(cls.uuid.in_(wanted)).execution_options(include_deleted=True)
        for found in (await db.execute(stmt)).scalars().all():
            out.setdefault(str(found), tables.name)
    return out
