"""Undoing a schema change — design doc §8.6.

Split out of :mod:`sm_records.services.schema_change` for the 300-line cap,
and it is the natural piece to move: an undo is an ``apply`` of an earlier
revision, so this module only finds the revision and hands it over. The
re-export keeps ``schema_change.rollback`` the import every caller already
uses.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import RecordType, RecordTypeRevision
from sm_records.schema.changes import SchemaDiff
from sm_records.services.errors import NotFound
from sm_records.settings import RecordsSettings

__all__ = ["rollback"]


async def rollback(
    db: AsyncSession,
    rtype: RecordType,
    *,
    to_version: int,
    expected_version: int,
    settings: RecordsSettings,
    actor: str | None = None,
    force: bool = False,
    orphaned: str | None = None,
) -> tuple[RecordType, SchemaDiff]:
    """Write an earlier schema revision back, as a new change (§8.6).

    Not a restore in the "put the row back" sense: the earlier ``fields`` go
    through :func:`apply` and are classified against what is stored *now*.
    Undoing a field deletion is therefore an addition, which meets §8.8's
    orphaned-key refusal — the point: the values are still there, and whether
    they come back is the operator's call, not the undo's.
    """
    # Imported here, not at the top: ``schema_change`` imports this module to
    # re-export ``rollback``, so the pair can only be acyclic one way round.
    from sm_records.services.schema_change import apply

    revision = (
        (
            await db.execute(
                select(RecordTypeRevision).where(
                    RecordTypeRevision.type_id == rtype.id,
                    RecordTypeRevision.version == to_version,
                )
            )
        )
        .scalars()
        .first()
    )
    if revision is None:
        raise NotFound(f"record type {rtype.key!r} has no revision at version {to_version}")
    return await apply(
        db,
        rtype,
        fields_raw=list(revision.fields or []),
        expected_version=expected_version,
        settings=settings,
        actor=actor,
        force=force,
        orphaned=orphaned,
        changes={
            "display_field": revision.display_field,
            "slug_field": revision.slug_field,
        },
    )
