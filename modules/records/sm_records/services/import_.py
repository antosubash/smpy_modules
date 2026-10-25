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

**The row ceiling is applied in the parse, not in the write loop.**
``max_import_rows`` refuses a file that is more work than one request will do
— a ``413``, the status ``max_import_bytes`` already uses — and it refuses it
before anything is validated: exactly, from ``len()`` of the parsed JSON
document, and for CSV at the first row past the ceiling, since a quoted cell
may contain newlines and there is no cheap exact count to check first.

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
from time import perf_counter

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import events
from sm_records.contracts.io import (
    ImportFormat,
    ImportReport,
    ImportRowError,
    OnError,
)
from sm_records.models import Record, RecordType
from sm_records.schema._text_checks import checked
from sm_records.services import _payload
from sm_records.services._import_csv import parse_csv
from sm_records.services._import_match import match_field
from sm_records.services._import_parse import parse_json
from sm_records.services._import_plan import ImportOptions, Plan, plan_rows, validate_rows
from sm_records.services._import_report import Tally, refuse, report
from sm_records.services._import_rows import write_row
from sm_records.services._patterns import batch_budget, precheck
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
                # ``held``: the row's event is built once ``write_row`` has
                # re-stamped the uuid the file chose (:mod:`sm_records.events`).
                with events.held(db):
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
            # ``held`` outside it: a row whose savepoint rolls back announces
            # nothing, though ``create_record`` had already emitted for it.
            with events.held(db):
                async with db.begin_nested():
                    result, row_record = await write_row(db, rtype, plan.row, plan.record, **kwargs)
            counts[result] += 1
            if written is not None:
                written.append((result, row_record))
        except RecordsError as exc:
            errors.append(
                ImportRowError(row=plan.row.number, uuid=plan.row.uuid, message=exc.detail)
            )
            # Rolling the savepoint back expires whatever the refused write
            # touched inside it. On SQLite that is the type row — ``lock_type``
            # bumps it there, where Postgres only locks it — and the caller
            # reads ``rtype`` again afterwards (the report, one event per
            # written row). Reload it here, inside the greenlet, rather than
            # leave the next attribute access to a lazy load that has none.
            if inspect(rtype).expired_attributes:
                await db.refresh(rtype)
    return counts["created"], counts["updated"]


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
    for rows that actually wrote. The report's counts cannot answer that. The
    domain events do not come from here: ``create_record``/``update_record``
    emit one per written row (:mod:`sm_records.events`). A dry run appends
    nothing, because it wrote nothing.
    """
    started = perf_counter()
    defs = _payload.field_defs(rtype)
    if options.match_by not in ("uuid", "slug"):
        match_field(rtype, defs, options.match_by)
    rows_limit = settings.max_import_rows
    parsed = (
        parse_json(text, max_rows=rows_limit)
        if fmt is ImportFormat.JSON
        else parse_csv(text, defs, max_rows=rows_limit)
    )
    errors: list[ImportRowError] = list(parsed.errors)
    tally = Tally(total=len(parsed.rows) + len({item.row for item in parsed.errors}))

    # A real ``abort`` run may stop at the first bad row, and the parse pass has
    # already found some if ``errors`` is non-empty — so the file is refused
    # before it is validated at all. See the module docstring.
    stop_early = not options.dry_run and options.on_error is OnError.ABORT
    if stop_early and errors:
        refuse(options, tally, errors, started)

    # Every row's patterned values in one worker batch, before any of them is
    # validated (``services._patterns``); the plan and the write read the
    # verdicts, so no row matches a pattern on the event loop.
    rows_budget = batch_budget(len(parsed.rows))
    found = await precheck(defs, [row.data for row in parsed.rows], budget=rows_budget)
    with checked(found):
        pairs = await validate_rows(
            db,
            rtype,
            parsed.rows,
            defs=defs,
            settings=settings,
            errors=errors,
            stop_on_error=stop_early,
            match_by=options.match_by,
        )
        if stop_early and errors:
            refuse(options, tally, errors, started)
        plans, tally.skipped = await plan_rows(
            db, rtype, pairs, options=options, defs=defs, errors=errors, stop_on_error=stop_early
        )

        if options.dry_run:
            tally.created = sum(1 for plan in plans if plan.record is None)
            tally.updated = len(plans) - tally.created
            return report(options, tally, errors, started)
        if errors and options.on_error is OnError.ABORT:
            refuse(options, tally, errors, started)
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
                report(options, Tally(total=tally.total, skipped=tally.skipped), errors, started),
                f"import refused: {failure.error.detail}",
            ) from failure.error
        return report(options, tally, errors, started)
