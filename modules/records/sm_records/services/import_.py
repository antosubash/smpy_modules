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

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.io import (
    ERROR_CAP,
    ImportFormat,
    ImportReport,
    ImportRowError,
    OnError,
)
from sm_records.models import RecordType
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
                result = await write_row(db, rtype, plan.row, plan.record, **kwargs)
            except RecordsError as exc:
                raise _RowWriteError(plan.row.number, plan.row.uuid, exc) from exc
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

    pairs = await validate_rows(db, rtype, parsed.rows, defs=defs, settings=settings, errors=errors)
    plans, tally.skipped = await plan_rows(
        db, rtype, pairs, options=options, defs=defs, errors=errors
    )

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
    except _RowWriteError as failure:
        errors.append(
            ImportRowError(row=failure.row, uuid=failure.uuid, message=failure.error.detail)
        )
        raise ImportRefused(
            _report(options, _Tally(total=tally.total, skipped=tally.skipped), errors, started),
            f"import refused: {failure.error.detail}",
        ) from failure.error
    return _report(options, tally, errors, started)
