"""Would this schema change leave any record invalid? Design doc §8.2, §8.9.

A batched, read-only pass over every record of one type, validating each
against the *proposed* model. It writes nothing and it holds no lock: the
apply path re-runs it inline before writing, because a report taken minutes ago
against records that may have changed since is a report about a different
database (§8.9 says so explicitly, and that is why no report is ever
persisted).

The trash is included. A trashed record still holds content the schema
describes and a restore reads it back under the new shape, so a change that
would break it is a change the operator has to be told about — the same
reasoning ``record_count(include_deleted=True)`` follows everywhere else here.

:func:`needs_dry_run` and :func:`change_report` are the decision around the
scan — when it is worth a full pass, and what a report says when it is not.
They live here rather than in ``schema_change`` so the answer to "is a scan
needed" sits with the scan it guards.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.constants import ORPHANED_KEY
from sm_records.models import Record, RecordType
from sm_records.schema.changes import DRY_RUN_SAMPLE, DryRunReport, FailingRecord, SchemaDiff
from sm_records.schema.compile import (
    PayloadValidationError,
    build_model,
    from_stored,
    validate_payload,
)
from sm_records.schema.fields import FieldDefinition
from sm_records.schema.types import ChangeClass
from sm_records.services._common import record_count
from sm_records.settings import RecordsSettings


async def _batches(db: AsyncSession, rtype: RecordType, batch_size: int):
    """Every record of the type in ``id`` order, in batches.

    Keyset rather than ``OFFSET``: the apply path runs this inside the same
    transaction that will write, and an offset walk over a table being written
    to skips rows — the same reason :func:`sm_records.index.reindex.reindex_type`
    pages this way.
    """
    last_id = 0
    while True:
        rows = (
            (
                await db.execute(
                    select(Record)
                    .where(Record.type_id == rtype.id, Record.id > last_id)
                    .order_by(Record.id)
                    .limit(batch_size)
                    .execution_options(include_deleted=True)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return
        yield rows
        last_id = rows[-1].id or last_id


def _errors_for(model: type, view: dict[str, Any]) -> list[dict[str, str]]:
    try:
        validate_payload(model, view)  # ty: ignore[invalid-argument-type]
    except PayloadValidationError as exc:
        return exc.errors
    return []


def _payload_of(record: Record, drop_keys: frozenset[str]) -> dict[str, Any]:
    data = dict(record.data or {})
    if not drop_keys:
        return data
    orphaned = {k: v for k, v in (data.get(ORPHANED_KEY) or {}).items() if k not in drop_keys}
    data = {k: v for k, v in data.items() if k not in drop_keys}
    if orphaned:
        data[ORPHANED_KEY] = orphaned
    else:
        data.pop(ORPHANED_KEY, None)
    return data


async def dry_run(
    db: AsyncSession,
    rtype: RecordType,
    new_defs: list[FieldDefinition],
    *,
    batch_size: int,
    orphaned_conflicts: dict[str, int] | None = None,
    drop_keys: frozenset[str] = frozenset(),
) -> DryRunReport:
    """Validate every record against ``new_defs`` without writing anything.

    The model is built with :func:`~sm_records.schema.compile.build_model`
    rather than ``get_model``: the proposed version does not exist yet, and
    caching a validator for a ``schema_version`` that may never be written
    would hand the next writer a shape nobody stored.

    Each record is read through :func:`~sm_records.schema.compile.from_stored`
    first — the same lenient read an API caller gets — so a row is judged on
    what it *reads as* under the new schema, defaults filled and values coerced
    (§8.4), not on the raw payload it happens to hold.

    ``drop_keys`` are removed from the payload before that read: they are the
    orphaned values an ``orphaned="discard"`` apply is about to throw away
    (§8.8), and judging a record on a value that will not survive the change
    would refuse the change for content nobody is keeping.
    """
    model = build_model(rtype.key, rtype.schema_version + 1, new_defs)
    checked = failing = 0
    sample: list[FailingRecord] = []
    async for batch in _batches(db, rtype, batch_size):
        for record in batch:
            checked += 1
            errors = _errors_for(model, from_stored(new_defs, _payload_of(record, drop_keys)))
            if not errors:
                continue
            failing += 1
            if len(sample) < DRY_RUN_SAMPLE:
                sample.append(
                    FailingRecord(
                        uuid=record.uuid,
                        display_title=record.display_title or "",
                        errors=tuple(errors),
                    )
                )
    return DryRunReport(
        checked=checked,
        failing=failing,
        sample=tuple(sample),
        orphaned_conflicts=dict(orphaned_conflicts or {}),
    )


def needs_dry_run(diff: SchemaDiff, conflicts: dict[str, int]) -> bool:
    """Only a restrictive change can invalidate a record. An additive or
    index-affecting one cannot, by construction, and a destructive one takes
    the field away rather than the rows — so scanning the type for them would
    be a full pass that can only ever report zero (§8.2). A type change is
    already classified restrictive, so it is covered here.

    **Orphaned keys are the exception, and they are classified additive.**
    Re-adding a deleted key is ``field_added`` — nothing about the *diff* can
    invalidate a record — but the values that key still holds were written
    under the old definition and are read back under the new one
    (``schema.compile.from_stored`` falls back to ``_orphaned`` for a declared
    key), so ``price`` deleted as ``text`` and re-added as ``number`` can
    perfectly well come back as ``"oops"``. §8.8 only offers ``restore`` where
    the values validate, which is a claim nothing but the scan can make — so
    any orphaned conflict forces it, on ``preview`` and on ``apply`` alike.
    """
    if conflicts:
        return True
    return any(c.kind is ChangeClass.RESTRICTIVE for c in diff.changes)


async def change_report(
    db: AsyncSession,
    rtype: RecordType,
    new_defs: list[FieldDefinition],
    settings: RecordsSettings,
    *,
    diff: SchemaDiff,
    conflicts: dict[str, int],
    drop_keys: frozenset[str] = frozenset(),
) -> DryRunReport:
    if not needs_dry_run(diff, conflicts):
        # Skipped, but ``checked`` still has to be an honest count of what
        # was skipped (incl. trash — §8.9's own reasoning for the delete
        # confirmation), or "N records checked, 0 would fail" lies about N.
        checked = await record_count(db, rtype, include_deleted=True)
        return DryRunReport(checked=checked, failing=0, orphaned_conflicts=conflicts)
    return await dry_run(
        db,
        rtype,
        new_defs,
        batch_size=settings.reindex_batch_size,
        orphaned_conflicts=conflicts,
        drop_keys=drop_keys,
    )
