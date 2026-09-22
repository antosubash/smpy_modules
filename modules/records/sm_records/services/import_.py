"""Importing a file of records — the run, its report, and its atomicity.

Named with a trailing underscore because ``import`` is a keyword. It is the
counterpart of :mod:`sm_records.services.export` and reads what that writes.

**The whole file is parsed and validated before one row is written.** A
streaming importer that validated as it wrote would make ``on_error=abort`` a
promise it could keep only by undoing work, and would make the dry run a
different code path from the real one — so it would stop predicting it, which
is the only thing a dry run is for. Here the two are one function with the
writing step switched off, and both produce the same report.

**Except when the answer is already no.** A real ``on_error=abort`` run stops
at the first bad row (S4): nothing is going to be written, so validating the
remaining 8,999 rows only decides *how long the refusal takes*. The report then
names one row instead of up to ``ERROR_CAP`` of them, which is the trade — and
it is the right one, because ``abort`` means the caller has to fix the file and
re-post it, and a caller who wants the whole list of what is wrong asks for the
dry run that exists to produce it. A dry run and ``on_error=skip`` are both
unaffected: the first must report everything, and the second is going to write
every row that is fine.

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
from typing import NoReturn

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.io import (
    ERROR_CAP,
    ImportFormat,
    ImportReport,
    ImportRowError,
    OnError,
)
from sm_records.models import Record, RecordType
from sm_records.services import _payload
from sm_records.services._import_match import match_field
from sm_records.services._import_parse import parse_csv, parse_json
from sm_records.services._import_plan import ImportOptions, Plan, plan_rows, validate_rows
from sm_records.services._import_rows import write_row
from sm_records.services.errors import ImportRefused, RecordsError
from sm_records.settings import RecordsSettings

__all__ = ["ImportOptions", "import_records"]

_SKIP = "skipped"


class _RowWriteError(Exception):
    """A row that failed *during the write pass*, carrying which row it was.

    ``on_error=abort`` raises out of the loop, and the refusal used to be
    reported as ``row: 0`` — a hard-coded placeholder, because the exception
    reaching :func:`import_records` carried a message and nothing else. §2's
    whole bargain is that the caller "fixes the rows it names and re-posts the
    same file", and on a 40,000-row file "row 0" names nothing. The write loop
    knows ``plan.row.number``; this is what carries it out.
    """

    def __init__(self, row: int, uuid: str | None, error: RecordsError) -> None:
        super().__init__(error.detail)
        self.row = row
        self.uuid = uuid
        self.error = error


@dataclass(slots=True)
class _Tally:
    """Running counts, so the three places a report is built (dry run,
    refusal, success) share one call rather than three argument lists that
    can disagree about what ``skipped`` meant."""

    total: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0


async def _write(
    db: AsyncSession,
    rtype: RecordType,
    plans: Sequence[Plan],
    *,
    options: ImportOptions,
    settings: RecordsSettings,
    actor: str | None,
    errors: list[ImportRowError],
    written: list[tuple[str, Record]] | None,
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
            try:
                result, row_record = await write_row(db, rtype, plan.row, plan.record, **kwargs)
            except RecordsError as exc:
                raise _RowWriteError(plan.row.number, plan.row.uuid, exc) from exc
            counts[result] += 1
            if written is not None:
                written.append((result, row_record))
            continue
        try:
            # A savepoint per row: a refused write leaves the session needing
            # a rollback, and rolling the *outer* transaction back would take
            # every valid row with it — which is ``abort``'s behaviour, not
            # this one's.
            async with db.begin_nested():
                result, row_record = await write_row(db, rtype, plan.row, plan.record, **kwargs)
            counts[result] += 1
            if written is not None:
                written.append((result, row_record))
        except RecordsError as exc:
            errors.append(
                ImportRowError(row=plan.row.number, uuid=plan.row.uuid, message=exc.detail)
            )
    return counts["created"], counts["updated"]


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


def _refuse(
    options: ImportOptions,
    tally: _Tally,
    errors: Sequence[ImportRowError],
    started: float,
) -> NoReturn:
    """Raise the "nothing was imported" refusal.

    Nothing has been written when this fires, so the refusal costs no rollback
    — but raising is still what gives the caller the report rather than a 200
    that quietly wrote nothing, and what makes the endpoint discard whatever
    the validation pass happened to touch.

    A function because ``abort`` now has three places to reach it: a parse that
    already failed, a validation pass that stopped at its first bad row, and
    the full pass a non-short-circuiting run still does (S4). Three copies of
    one ``raise`` are three chances for the report to disagree with itself.
    """
    raise ImportRefused(
        _report(options, _Tally(total=tally.total, skipped=tally.skipped), errors, started),
        f"{len({item.row for item in errors})} row(s) failed; nothing was imported",
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
    written: list[tuple[str, Record]] | None = None,
) -> ImportReport:
    """Parse, validate, plan, and — unless this is a dry run — write.

    ``written`` is an optional sink the caller passes to learn *which* records
    each row wrote: ``("created" | "updated", record)`` in file order, only
    for rows that actually wrote. The report's counts cannot answer that, and
    the endpoint needs it to publish one domain event per record rather than
    one per file (:mod:`sm_records.events`). A dry run appends nothing,
    because it wrote nothing.
    """
    started = perf_counter()
    defs = _payload.field_defs(rtype)
    if options.match_by not in ("uuid", "slug"):
        match_field(rtype, defs, options.match_by)
    parsed = parse_json(text) if fmt is ImportFormat.JSON else parse_csv(text, defs)
    errors: list[ImportRowError] = list(parsed.errors)
    tally = _Tally(total=len(parsed.rows) + len({item.row for item in parsed.errors}))

    # A real ``abort`` run may stop at the first bad row, and the parse pass has
    # already found some if ``errors`` is non-empty — so the file is refused
    # before it is validated at all. See the module docstring.
    stop_early = not options.dry_run and options.on_error is OnError.ABORT
    if stop_early and errors:
        _refuse(options, tally, errors, started)

    pairs = await validate_rows(
        db,
        rtype,
        parsed.rows,
        defs=defs,
        settings=settings,
        errors=errors,
        stop_on_error=stop_early,
    )
    if stop_early and errors:
        _refuse(options, tally, errors, started)
    plans, tally.skipped = await plan_rows(
        db, rtype, pairs, options=options, defs=defs, errors=errors, stop_on_error=stop_early
    )

    if options.dry_run:
        tally.created = sum(1 for plan in plans if plan.record is None)
        tally.updated = len(plans) - tally.created
        return _report(options, tally, errors, started)
    if errors and options.on_error is OnError.ABORT:
        _refuse(options, tally, errors, started)
    try:
        tally.created, tally.updated = await _write(
            db,
            rtype,
            plans,
            options=options,
            settings=settings,
            actor=actor,
            errors=errors,
            written=written,
        )
    except _RowWriteError as failure:
        errors.append(
            ImportRowError(row=failure.row, uuid=failure.uuid, message=failure.error.detail)
        )
        raise ImportRefused(
            _report(options, _Tally(total=tally.total, skipped=tally.skipped), errors, started),
            f"import refused: {failure.error.detail}",
        ) from failure.error
    return _report(options, tally, errors, started)
