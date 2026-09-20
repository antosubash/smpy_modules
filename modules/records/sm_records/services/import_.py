"""Importing a file of records — the run, its report, and its atomicity.

Named with a trailing underscore because ``import`` is a keyword. It is the
counterpart of :mod:`sm_records.services.export` and reads what that writes.

**The whole file is parsed and validated before one row is written.** A
streaming importer that validated as it wrote would make ``on_error=abort`` a
promise it could keep only by undoing work, and would make the dry run a
different code path from the real one — so it would stop predicting it, which
is the only thing a dry run is for. Here the two are one function with the
writing step switched off, and both produce the same report.

**``abort`` is the request's transaction, not a loop counter.** Nothing here
commits (``CLAUDE.md``: the framework's session does). A refused run raises
:class:`~sm_records.services.errors.ImportRefused`, which ``RecordsErrorRoute``
turns into a 422 *and rolls the session back* — so a file failing on row 501
leaves the first 500 unwritten without this module tracking what it wrote.
``skip`` is the opposite bargain and needs a savepoint per row: a refused
write can leave the session needing a rollback that would otherwise take the
valid rows with it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.io import (
    ERROR_CAP,
    ImportFormat,
    ImportMode,
    ImportReport,
    ImportRowError,
    OnError,
)
from sm_records.models import Record, RecordType
from sm_records.services import _payload, _relations
from sm_records.services._common import type_id_map
from sm_records.services._import_parse import (
    ImportRow,
    parse_csv,
    parse_json,
    refuses_orphaned,
)
from sm_records.services._import_rows import (
    Envelope,
    envelope_for,
    match_field,
    mode_error,
    resolve_matches,
    unchanged,
    write_row,
)
from sm_records.services.errors import ImportRefused, RecordsError, ValidationFailed
from sm_records.settings import RecordsSettings

__all__ = ["ImportOptions", "import_records"]

_SKIP = "skipped"


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
class _Plan:
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


async def _validate(
    db: AsyncSession,
    rtype: RecordType,
    rows: Sequence[ImportRow],
    *,
    defs: list[Any],
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
        except ValidationFailed as exc:
            errors.extend(_errors_for(row, exc))
            continue
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


async def _plan(
    db: AsyncSession,
    rtype: RecordType,
    pairs: Sequence[tuple[ImportRow, Envelope]],
    *,
    options: ImportOptions,
    defs: list[Any],
    errors: list[ImportRowError],
) -> tuple[list[_Plan], int]:
    """Decide per row what would happen, and count the no-ops."""
    duplicates = _duplicates(pairs)
    matches = await resolve_matches(
        db, rtype, [row for row, _ in pairs], match_by=options.match_by, defs=defs
    )
    plans: list[_Plan] = []
    skipped = 0
    for row, envelope in pairs:
        problem = duplicates.get(row.number)
        record = matches.get(row.number)
        if problem is None and record is not None and record.type_id != rtype.id:
            problem = f"uuid {row.uuid} belongs to a different record type"
        elif problem is None and record is not None and record.is_deleted:
            problem = f"record {record.uuid} is in the trash; restore or purge it first"
        problem = problem or mode_error(options.mode, record)
        if problem is not None:
            errors.append(ImportRowError(row=row.number, uuid=row.uuid, message=problem))
            continue
        if record is not None and unchanged(rtype, record, row, envelope, defs):
            skipped += 1
            continue
        plans.append(_Plan(row, envelope, record))
    return plans, skipped


async def _write(
    db: AsyncSession,
    rtype: RecordType,
    plans: Sequence[_Plan],
    *,
    options: ImportOptions,
    settings: RecordsSettings,
    actor: str | None,
    errors: list[ImportRowError],
) -> tuple[int, int]:
    counts = {"created": 0, "updated": 0}
    for plan in plans:
        kwargs = {
            "mode": options.mode,
            "envelope": plan.envelope,
            "settings": settings,
            "actor": actor,
            "force": options.force,
        }
        if options.on_error is OnError.ABORT:
            result = await write_row(db, rtype, plan.row, plan.record, **kwargs)
            counts[result] += 1
            continue
        try:
            # A savepoint per row: a refused write leaves the session needing
            # a rollback, and rolling the *outer* transaction back would take
            # every valid row with it — which is ``abort``'s behaviour, not
            # this one's.
            async with db.begin_nested():
                result = await write_row(db, rtype, plan.row, plan.record, **kwargs)
            counts[result] += 1
        except RecordsError as exc:
            errors.append(
                ImportRowError(row=plan.row.number, uuid=plan.row.uuid, message=exc.detail)
            )
    return counts["created"], counts["updated"]


@dataclass(slots=True)
class _Tally:
    """Running counts, so the three places a report is built (dry run,
    refusal, success) share one call rather than three argument lists that
    can disagree about what ``skipped`` meant."""

    total: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0


def _report(
    options: ImportOptions,
    tally: _Tally,
    errors: Sequence[ImportRowError],
    started: float,
) -> ImportReport:
    return ImportReport(
        dry_run=options.dry_run,
        mode=options.mode,
        total=tally.total,
        created=tally.created,
        updated=tally.updated,
        skipped=tally.skipped,
        failed=len({item.row for item in errors}),
        errors=list(errors[:ERROR_CAP]),
        errors_truncated=len(errors) > ERROR_CAP,
        duration_ms=int((perf_counter() - started) * 1000),
    )


async def import_records(
    db: AsyncSession,
    rtype: RecordType,
    text: str,
    *,
    fmt: ImportFormat,
    options: ImportOptions,
    settings: RecordsSettings,
    actor: str | None = None,
) -> ImportReport:
    """Parse, validate, plan, and — unless this is a dry run — write."""
    started = perf_counter()
    defs = _payload.field_defs(rtype)
    if options.match_by not in ("uuid", "slug"):
        match_field(rtype, defs, options.match_by)
    parsed = parse_json(text) if fmt is ImportFormat.JSON else parse_csv(text, defs)
    errors: list[ImportRowError] = list(parsed.errors)
    tally = _Tally(total=len(parsed.rows) + len({item.row for item in parsed.errors}))

    pairs = await _validate(db, rtype, parsed.rows, defs=defs, settings=settings, errors=errors)
    plans, tally.skipped = await _plan(db, rtype, pairs, options=options, defs=defs, errors=errors)

    if options.dry_run:
        tally.created = sum(1 for plan in plans if plan.record is None)
        tally.updated = len(plans) - tally.created
        return _report(options, tally, errors, started)
    if errors and options.on_error is OnError.ABORT:
        # Nothing has been written yet, so the refusal costs no rollback —
        # but raising is still what gives the caller the report rather than a
        # 200 that quietly wrote nothing, and what makes the endpoint discard
        # whatever the validation pass happened to touch.
        raise ImportRefused(
            _report(options, _Tally(total=tally.total, skipped=tally.skipped), errors, started),
            f"{len({item.row for item in errors})} row(s) failed; nothing was imported",
        )
    try:
        tally.created, tally.updated = await _write(
            db, rtype, plans, options=options, settings=settings, actor=actor, errors=errors
        )
    except RecordsError as exc:
        errors.append(ImportRowError(row=0, message=exc.detail))
        raise ImportRefused(
            _report(options, _Tally(total=tally.total, skipped=tally.skipped), errors, started),
            f"import refused: {exc.detail}",
        ) from exc
    return _report(options, tally, errors, started)
