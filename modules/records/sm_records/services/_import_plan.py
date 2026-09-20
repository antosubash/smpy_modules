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
from sm_records.services import _payload, _relations
from sm_records.services._common import type_id_map
from sm_records.services._import_match import resolve_matches
from sm_records.services._import_parse import ImportRow, refuses_orphaned
from sm_records.services._import_rows import Envelope, envelope_for, mode_error, unchanged
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
) -> list[tuple[ImportRow, Envelope]]:
    """Validate every row against the *current* schema, writing nothing.

    The same ``_payload.validate`` a single write uses — so the size ceiling,
    the ``_orphaned`` refusal and the compiled model are one implementation
    rather than an import-shaped copy — plus ``create_record``'s relation
    target check, the rule a file breaks far more often than a form does.
    """
    types = await type_id_map(db)
    out: list[tuple[ImportRow, Envelope]] = []
    for row in rows:
        reserved = refuses_orphaned(row)
        if reserved is not None:
            errors.append(reserved)
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
            continue
        row.locale = envelope.locale
        row.values, row.stored = values, stored
        out.append((row, envelope))
    return out


def _duplicates(pairs: Sequence[tuple[ImportRow, Envelope]]) -> dict[int, str]:
    """Rows whose identity another row in the same file already claimed.
    Caught here rather than at the unique index, where the second write is a
    raw ``IntegrityError`` — a 500 about a constraint, on a file whose real
    problem is that two exports were concatenated."""
    seen: dict[str, int] = {}
    out: dict[int, str] = {}
    for row, _ in pairs:
        if not row.uuid:
            continue
        first = seen.setdefault(row.uuid, row.number)
        if first != row.number:
            out[row.number] = f"uuid {row.uuid} appears twice in this file (first at row {first})"
    return out


def _immutable(record: Record, row: ImportRow, envelope: Envelope) -> str | None:
    """What this row asks to change about an existing record that cannot change.

    A record's language is fixed for its lifetime and its translation group is
    the relationship it is *in*, so a file asking to move either is refused
    rather than silently ignored — the same answer ``PUT /records/{uuid}``
    gives a body carrying a ``locale`` (§4.3). Ignoring it would make an import
    the one write path where a language change appears to succeed.

    A round trip never trips this: the export writes each record's own values
    back, so the comparison is between a value and itself.
    """
    if row.locale is not None and row.locale != record.locale:
        return (
            f"record {record.uuid} is in {record.locale!r} and a record's locale is fixed "
            f"for its lifetime; create a translation instead of importing it as "
            f"{row.locale!r}"
        )
    if (
        envelope.translation_group is not None
        and envelope.translation_group != record.translation_group
    ):
        return (
            f"record {record.uuid} is already in translation group "
            f"{record.translation_group}; an import cannot move a record between groups"
        )
    return None


async def plan_rows(
    db: AsyncSession,
    rtype: RecordType,
    pairs: Sequence[tuple[ImportRow, Envelope]],
    *,
    options: ImportOptions,
    defs: list[FieldDefinition],
    errors: list[ImportRowError],
) -> tuple[list[Plan], int]:
    """Decide per row what would happen, and count the no-ops."""
    duplicates = _duplicates(pairs)
    matches = await resolve_matches(
        db, rtype, [row for row, _ in pairs], match_by=options.match_by, defs=defs
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
            problem = _immutable(record, row, envelope)
        problem = problem or mode_error(options.mode, record)
        if problem is not None:
            errors.append(ImportRowError(row=row.number, uuid=row.uuid, message=problem))
            continue
        if record is not None and unchanged(rtype, record, row, envelope, defs):
            skipped += 1
            continue
        plans.append(Plan(row, envelope, record))
    return plans, skipped
