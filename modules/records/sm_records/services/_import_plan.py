"""Deciding what an import *would* do, before it does any of it.

Split from :mod:`sm_records.services.import_` for the 300-line cap, along the
seam that module's docstring already draws: the whole file is parsed and
validated before one row is written, so "what does this file say and what would
it do" is a phase of its own — and it is the *only* phase a dry run runs. A dry
run and a real run therefore share this code exactly, which is the only thing
that makes a dry run worth reading.

Nothing here writes. Nothing here commits.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import locales
from sm_records.contracts.io import ImportMode, ImportRowError, OnError
from sm_records.models import Record, RecordType
from sm_records.schema.fields import FieldDefinition
from sm_records.services import _import_checks as _checks
from sm_records.services import _payload, _relations, _uuids
from sm_records.services._common import type_id_map
from sm_records.services._import_match import resolve_matches
from sm_records.services._import_parse import ImportRow, refuses_orphaned
from sm_records.services._import_rows import (
    Envelope,
    envelope_for,
    mode_error,
    unchanged,
    version_required,
)
from sm_records.services.errors import ValidationFailed
from sm_records.settings import RecordsSettings

__all__ = ["ImportOptions", "Plan", "plan_rows", "validate_rows"]


@dataclass(frozen=True, slots=True)
class ImportOptions:
    """Everything the caller chose, in one object.

    ``dry_run`` defaults to ``True``: this is the one operation in the module
    that can touch every record of a type at once, so a caller that means it
    says so and a caller that forgot gets a report.
    """

    mode: ImportMode = ImportMode.UPSERT
    dry_run: bool = True
    on_error: OnError = OnError.ABORT
    match_by: str = "uuid"
    force: bool = False


@dataclass(slots=True)
class Plan:
    """One row, its coerced envelope, and the record it would write — ``None``
    for a row that would create one."""

    row: ImportRow
    envelope: Envelope
    record: Record | None


def _errors_for(row: ImportRow, exc: ValidationFailed) -> list[ImportRowError]:
    return [
        ImportRowError(
            row=row.number, uuid=row.uuid, field=item.get("field"), message=item["message"]
        )
        for item in exc.errors
    ]


async def validate_rows(
    db: AsyncSession,
    rtype: RecordType,
    rows: Sequence[ImportRow],
    *,
    defs: list[FieldDefinition],
    settings: RecordsSettings,
    errors: list[ImportRowError],
    stop_on_error: bool = False,
) -> list[tuple[ImportRow, Envelope]]:
    """Validate every row against the *current* schema, writing nothing.

    The same ``_payload.validate`` a single write uses — so the size ceiling,
    the ``_orphaned`` refusal and the compiled model are one implementation
    rather than an import-shaped copy — plus ``create_record``'s relation
    target check, the rule a file breaks far more often than a form does.

    ``stop_on_error`` returns at the first bad row instead of validating the
    rest — S4. It is set only by a **real** ``on_error=abort`` run, where the
    answer is already settled: nothing will be written, and the report names
    the row that settled it. A *dry run* never sets it, because a dry run's
    whole job is the complete list of what is wrong with the file, and
    ``on_error=skip`` never sets it either, because there every other row is
    still going to be written.
    """
    types = await type_id_map(db)
    out: list[tuple[ImportRow, Envelope]] = []
    for row in rows:
        reserved = refuses_orphaned(row)
        if reserved is not None:
            errors.append(reserved)
            if stop_on_error:
                break
            continue
        try:
            values, stored = _payload.validate(
                rtype, defs, row.data, max_payload_bytes=settings.max_payload_bytes
            )
            await _relations.check_targets(db, defs, values, types)
            envelope = envelope_for(row)
            # A missing ``locale`` column means the default content locale — a
            # file written before this install spoke more than one language is
            # a file of default-locale records. A locale that is *named* and
            # not configured is this row's error, not the file's: one bad cell
            # in 40,000 should be reported, not abort the parse.
            envelope.locale = locales.require(settings, envelope.locale)
        except ValidationFailed as exc:
            errors.extend(_errors_for(row, exc))
            if stop_on_error:
                break
            continue
        row.locale = envelope.locale
        row.values, row.stored = values, stored
        out.append((row, envelope))
    return out


async def plan_rows(
    db: AsyncSession,
    rtype: RecordType,
    pairs: Sequence[tuple[ImportRow, Envelope]],
    *,
    options: ImportOptions,
    defs: list[FieldDefinition],
    errors: list[ImportRowError],
    stop_on_error: bool = False,
) -> tuple[list[Plan], int]:
    """Decide per row what would happen, and count the no-ops.

    **Everything a write can refuse for a reason this pass can see is refused
    here.** The module's bargain is that a dry run is the real run with the
    writing switched off (:mod:`sm_records.services.import_`), and a check that
    lived in :func:`~sm_records.services._import_rows.write_row` broke it: the
    preview reported "1 to update, 0 failed" and the apply then failed the row.
    That is worse than either answer on its own, because the whole point of the
    default dry run is that the caller acts on it. So the version requirement
    (:func:`~sm_records.services._import_rows.version_required`) is asked here
    and ``write_row`` keeps it only as a guard for a direct caller.

    ``stop_on_error`` is :func:`validate_rows`'s, and means the same thing: a
    real ``abort`` run stops at the row that settles the answer instead of
    planning the other 8,999 (S4). The batched lookups above it still run once
    for the whole file — they are one statement each, and splitting them to
    save the tail of a refused import would be the per-row shape §2 exists to
    avoid.
    """
    duplicates = _checks.duplicates(pairs)
    claims = _checks.group_claims(pairs)
    matches = await resolve_matches(
        db, rtype, [row for row, _ in pairs], match_by=options.match_by, defs=defs
    )
    # One batched lookup for the whole file rather than one per row, and none
    # at all on a host with no collections declared (Phase 5 §6.5).
    elsewhere = await _uuids.uuids_claimed_elsewhere(
        db, rtype, [row.uuid for row, _ in pairs if row.uuid and matches.get(row.number) is None]
    )
    taken = await _checks.groups_in_type(
        db,
        rtype,
        {
            envelope.translation_group
            for row, envelope in pairs
            if envelope.translation_group
            and envelope.translation_group != row.uuid
            and claims.get(envelope.translation_group, 0) <= 1
        },
    )
    plans: list[Plan] = []
    skipped = 0
    for row, envelope in pairs:
        problem = duplicates.get(row.number)
        record = matches.get(row.number)
        if problem is None and record is not None and record.type_id != rtype.id:
            problem = f"uuid {row.uuid} belongs to a different record type"
        elif problem is None and record is not None and record.is_deleted:
            problem = f"record {record.uuid} is in the trash; restore or purge it first"
        elif problem is None and record is not None:
            problem = _checks.immutable(record, row, envelope)
        elif problem is None and row.uuid in elsewhere:
            # A uuid is unique across every table set (§6.4) and this row would
            # *create* a record under one another set already holds — which the
            # importer used to do happily, because it keeps a file's uuid
            # verbatim. See :mod:`sm_records.services._uuids`.
            problem = _uuids.uuid_claim_message(row.uuid, elsewhere[row.uuid])
        elif problem is None:
            problem = _checks.forged_group(rtype, row, envelope, claims, taken)
        problem = problem or mode_error(options.mode, record)
        if problem is not None:
            errors.append(ImportRowError(row=row.number, uuid=row.uuid, message=problem))
            if stop_on_error:
                break
            continue
        if record is not None and unchanged(rtype, record, row, envelope):
            skipped += 1
            continue
        if record is not None and not options.force:
            missing = version_required(record, row)
            if missing is not None:
                errors.append(
                    ImportRowError(row=row.number, uuid=row.uuid, field="version", message=missing)
                )
                if stop_on_error:
                    break
                continue
        plans.append(Plan(row, envelope, record))
    return plans, skipped
