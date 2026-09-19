"""Measurement helpers: timing, statement counting, query plans, the table.

Deliberately dependency-free — ``time.perf_counter`` and the SQLAlchemy
``before_cursor_execute`` event, nothing else — so the perf suite adds no
install for a host that never runs it.

Three things are load-bearing and easy to get wrong when extending this:

*The plan is taken from the SQL that actually ran*, not from compiling the
``Select``. The framework's soft-delete filter is a ``with_loader_criteria``
hook applied at execute time, so a statement compiled by hand is missing the
``is_deleted`` predicate the real query carries — and that predicate is
exactly what decides whether SQLite can use an index.

*Statement counts come from the same event*, so "how many round trips does one
create cost" is a hard number rather than a reading of the code.

*Nothing asserts a wall-clock threshold.* A timing assertion on a shared CI
box is a flake generator; the suite asserts plan shape and statement counts,
which are properties of the code, and prints the timings for a human.
"""

from __future__ import annotations

import os
import statistics
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, ClassVar

from sqlalchemy import event


@dataclass
class Capture:
    """Statements seen while a :func:`capture` block was open."""

    statements: list[tuple[str, Any]] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.statements)

    def matching(self, needle: str) -> list[tuple[str, Any]]:
        return [row for row in self.statements if needle in row[0]]

    def last(self) -> tuple[str, Any]:
        return self.statements[-1]

    def longest(self) -> tuple[str, Any]:
        """The biggest statement in the block — for a page read that is the
        filtered ``SELECT``, which is the one worth a plan."""
        return max(self.statements, key=lambda row: len(row[0]))


@contextmanager
def capture(engine: Any) -> Iterator[Capture]:
    """Record every statement this engine executes inside the block.

    ``engine`` is the ``AsyncEngine``; the event goes on its ``sync_engine``,
    which is where SQLAlchemy emits ``before_cursor_execute``.
    """
    box = Capture()

    def _on_execute(conn, cursor, statement, parameters, context, executemany):
        box.statements.append((statement, parameters))

    sync_engine = getattr(engine, "sync_engine", engine)
    event.listen(sync_engine, "before_cursor_execute", _on_execute)
    try:
        yield box
    finally:
        event.remove(sync_engine, "before_cursor_execute", _on_execute)


async def explain(session: Any, sql: str, params: Any) -> list[str]:
    """``EXPLAIN QUERY PLAN`` for a statement captured by :func:`capture`.

    Runs the driver SQL verbatim with the parameters it was given, so the plan
    describes the query the module actually issued.
    """
    conn = await session.connection()
    rows = (await conn.exec_driver_sql("EXPLAIN QUERY PLAN " + sql, params)).all()
    return [str(row[-1]) for row in rows]


def plan_scans_records(plan: list[str]) -> bool:
    """True when the plan reads ``records_record`` without an index — the
    full-scan shape design §7.2 exists to prevent."""
    return any("SCAN records_record" in line and "USING" not in line for line in plan)


def plan_uses(plan: list[str], index_name: str) -> bool:
    return any(index_name in line for line in plan)


def plan_temp_btree(plan: list[str]) -> bool:
    return any("TEMP B-TREE" in line.upper() for line in plan)


@dataclass
class Timing:
    """p50/p95 over N repetitions, in milliseconds."""

    samples: list[float] = field(default_factory=list)

    @property
    def p50(self) -> float:
        return statistics.median(self.samples) if self.samples else 0.0

    @property
    def p95(self) -> float:
        if not self.samples:
            return 0.0
        ordered = sorted(self.samples)
        idx = min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))
        return ordered[idx]

    @property
    def mean(self) -> float:
        return statistics.fmean(self.samples) if self.samples else 0.0


BUDGET_SECONDS = float(os.environ.get("RECORDS_PERF_BUDGET", "20"))
"""Wall-clock ceiling on one measurement's timed phase.

Some queries in this module are seconds each at 100k rows — that is a
finding, not a reason for the suite to take an hour. A measurement stops
early once the timed phase has spent this long, so a query that takes a
minute contributes one sample rather than twenty. The sample count travels
with the result and is printed, so a p95 over 3 is never read as a p95 over
20."""

MIN_SAMPLES = 1


async def repeat(fn: Callable[[], Awaitable[Any]], *, reps: int, warmup: int = 3) -> Timing:
    """Await ``fn`` ``warmup`` times untimed, then up to ``reps`` times timed,
    stopping early if the timed phase exceeds :data:`BUDGET_SECONDS`."""
    warm_deadline = time.perf_counter() + BUDGET_SECONDS / 4
    for _ in range(max(warmup, 0)):
        await fn()
        if time.perf_counter() > warm_deadline:
            # A call slow enough to blow a quarter of the budget on warming up
            # is one the page cache will not rescue; stop warming and measure.
            break
    timing = Timing()
    deadline = time.perf_counter() + BUDGET_SECONDS
    for _ in range(reps):
        started = time.perf_counter()
        await fn()
        timing.samples.append((time.perf_counter() - started) * 1000.0)
        if len(timing.samples) >= MIN_SAMPLES and time.perf_counter() > deadline:
            break
    return timing


@dataclass
class Row:
    operation: str
    n: int
    p50: float
    p95: float
    statements: int | str
    plan: str
    reps: int = 0


class Results:
    """The table the suite prints at the end.

    Process-global on purpose: tests in three files contribute to one table,
    and a fixture handing it around would make every test signature longer for
    no benefit.
    """

    rows: ClassVar[list[Row]] = []
    notes: ClassVar[list[str]] = []

    plans: ClassVar[list[tuple[str, list[str]]]] = []

    @classmethod
    def add(
        cls,
        operation: str,
        n: int,
        timing: Timing,
        *,
        statements: int | str = "-",
        plan: str = "-",
        plan_lines: list[str] | None = None,
    ) -> None:
        cls.rows.append(
            Row(operation, n, timing.p50, timing.p95, statements, plan, len(timing.samples))
        )
        if plan_lines:
            # Kept in full and in order: the summary cell sorts the index
            # names to stay narrow, and *which table SQLite drives from* is
            # exactly what the order tells you.
            cls.plans.append((operation, list(plan_lines)))

    @classmethod
    def note(cls, text: str) -> None:
        cls.notes.append(text)

    @classmethod
    def render(cls) -> str:
        if not cls.rows:
            return "records perf: no measurements recorded"
        head = ("operation", "N", "p50 ms", "p95 ms", "reps", "stmts", "plan")
        body = [
            (
                row.operation,
                str(row.n),
                f"{row.p50:.2f}",
                f"{row.p95:.2f}",
                str(row.reps),
                str(row.statements),
                row.plan,
            )
            for row in cls.rows
        ]
        widths = [max(len(head[i]), *(len(r[i]) for r in body)) for i in range(len(head))]
        line = "  ".join(head[i].ljust(widths[i]) for i in range(len(head)))
        out = [line, "  ".join("-" * widths[i] for i in range(len(head)))]
        out += ["  ".join(r[i].ljust(widths[i]) for i in range(len(head))) for r in body]
        if cls.notes:
            out.append("")
            out += [f"note: {note}" for note in cls.notes]
        if cls.plans:
            out.append("")
            out.append("EXPLAIN QUERY PLAN (heaviest statement per operation)")
            for operation, lines in cls.plans:
                out.append(f"  {operation}")
                out += [f"    {line}" for line in lines]
        return "\n".join(out)
