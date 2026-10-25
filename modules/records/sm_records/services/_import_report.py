"""The import's report and its "nothing was imported" refusal.

Split from :mod:`sm_records.services.import_` for the 300-line cap: that
module parses, plans and writes; this is how the outcome is told.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import NoReturn

from sm_records.contracts.io import ERROR_CAP, ImportReport, ImportRowError
from sm_records.services._import_plan import ImportOptions
from sm_records.services.errors import ImportRefused

__all__ = ["Tally", "refuse", "report"]


@dataclass(slots=True)
class Tally:
    """Running counts, so the three places a report is built (dry run,
    refusal, success) share one call rather than three argument lists that
    can disagree about what ``skipped`` meant."""

    total: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0


def report(
    options: ImportOptions,
    tally: Tally,
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


def refuse(
    options: ImportOptions,
    tally: Tally,
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
        report(options, Tally(total=tally.total, skipped=tally.skipped), errors, started),
        f"{len({item.row for item in errors})} row(s) failed; nothing was imported",
    )
