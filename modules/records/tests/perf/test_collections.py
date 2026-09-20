"""A type in a collection against the same type in the global tables — §6.

The design's claim is that a collection is a *physical partition* built by the
same factory, so its tables are identical modulo the prefix and one query layer
serves both. If that is true the numbers have to be boring: the same statement
count, the same plan shape, the same milliseconds. A row here that is not
boring means the table-set refactor left a path naming the global tables — or
that a collection costs something the design did not price.

The measurement runs in a **subprocess** (``_collection_worker``), because
``declare_collection`` is a process-global side effect that must happen before
any app is built: declaring one here would add eight tables to the seeded file
every other measurement in this directory runs against, and would make
``referrers`` walk two table sets in rows meant to describe a host with none.

The one row that is *not* boring is the last: ``referrers`` asks every declared
table set, so declaring a collection costs one statement per set on every
delete and every referrers panel, whether or not any type lives in it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from sm_records.collections import collections
from sm_records.index.query import build_query
from sm_records.services._relations import referrers

from tests.perf._bench import Results, Timing, capture, repeat
from tests.perf._http import plan_label
from tests.perf.conftest import DATASET_SIZE, REPS, load_type, type_counts

pytestmark = pytest.mark.perf

WORKER_RECORDS = max(min(DATASET_SIZE // 10, 2000), 40)
"""How many records each of the two benchmark types gets.

A fraction of the suite's size rather than a constant: the comparison is
global-against-collection on *equal* tables, so what matters is that the two
are the same and that the default run stays inside its minute."""


def _run_worker(tmp_path: Path, collections_declared: int) -> dict:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("_collection_worker.py")),
            str(tmp_path / f"collection_perf_{collections_declared}.db"),
            str(WORKER_RECORDS),
            str(collections_declared),
            str(max(REPS // 2, 3)),
        ],
        capture_output=True,
        text=True,
        cwd=str(root),
        check=False,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def _record(rows: list[dict]) -> dict[str, dict]:
    out = {}
    for row in rows:
        timing = Timing([row["p50"]])
        Results.add(
            row["operation"],
            WORKER_RECORDS,
            timing,
            statements=row["statements"],
            plan=plan_label(row["plan"]) if isinstance(row["plan"], list) else str(row["plan"]),
            plan_lines=row["plan"] if isinstance(row["plan"], list) else None,
        )
        out[row["operation"]] = row
    return out


def _shape(plan: list[str], prefix: str = "") -> list[str]:
    """A plan reduced to what "identical modulo the prefix" can honestly mean.

    Two things are normalised away. The collection's table prefix, obviously.
    And the *name* of the composite index a ``records_record`` line uses: the
    fixed-column indexes of F5 are ``(type_id, <column>, id)`` several times
    over, so when only ``type_id`` is constrained they are interchangeable and
    SQLite picks between them on statistics it does not have. A run that reads
    ``ix_records_record_type_updated_id`` globally and
    ``ix_records_record_type_published_id`` in a collection has done the same
    work by the same shape; insisting on the name would make this test a
    coin flip.
    """
    out = []
    for line in plan:
        if prefix:
            line = line.replace(f"records_c_{prefix}_", "records_")
        if "records_record USING" in line:
            head, _, _tail = line.partition("USING")
            kind = "COVERING INDEX" if "COVERING INDEX" in line else "INDEX"
            line = f"{head}USING {kind} ix_records_record_type_*"
        out.append(line)
    return out


async def test_a_collection_type_costs_what_a_global_type_costs(tmp_path):
    """Every read and write row, the two table sets side by side."""
    payload = _run_worker(tmp_path, 1)
    rows = _record(payload["rows"])
    prefix = payload["collections"][0]
    pairs = [
        ("create_record", "create_record (global)", "create_record (collection)"),
        ("list page 25", "list page 25 (global)", "list page 25 (collection)"),
        (
            "number gte filter",
            "list, number gte filter (global)",
            "list, number gte filter (collection)",
        ),
        ("sort by name", "list, sort by name (global)", "list, sort by name (collection)"),
    ]
    for label, g_key, c_key in pairs:
        g, c = rows[g_key], rows[c_key]
        assert g["statements"] == c["statements"], (
            f"{label}: {g['statements']} statements globally, {c['statements']} in a collection"
        )
        assert _shape(c["plan"], prefix) == _shape(g["plan"]), (
            f"{label}: plans differ beyond the prefix\n  global: {_shape(g['plan'])}\n  "
            f"collection: {_shape(c['plan'], prefix)}"
        )
    Results.note(
        "a collection type's statement counts and query plans are the global "
        "type's, modulo the table prefix"
    )


async def test_referrers_costs_one_read_per_declared_table_set(tmp_path):
    """What declaring a collection costs a host that never uses it.

    ``referrers`` cannot union the sets — two collections number their records
    independently, so a union would merge ids that mean different rows (§6.6) —
    so it asks each in turn. The cost is therefore linear in *declared*
    collections rather than in used ones, and it is paid by every delete.
    """
    one = _run_worker(tmp_path, 1)
    two = _run_worker(tmp_path, 2)
    rows_one = _record([r for r in one["rows"] if r["operation"].startswith("referrers")])
    rows_two = _record([r for r in two["rows"] if r["operation"].startswith("referrers")])
    counts_one = {r["statements"] for r in rows_one.values()}
    counts_two = {r["statements"] for r in rows_two.values()}
    assert len(counts_one) == 1 and len(counts_two) == 1, (counts_one, counts_two)
    per_set = (counts_two.pop() - counts_one.pop()) / 1
    Results.note(
        f"referrers costs {per_set:.0f} statement(s) per declared collection "
        "(the walk asks every table set; a union would merge ids across sets)"
    )


async def test_referrers_on_a_host_with_no_collection(perf_db, perf_session):
    """The same call in *this* process, which declares none — the baseline the
    two rows above are read against."""
    assert collections() == (), "a perf process that declares a collection invalidates this row"
    rtype = await load_type(perf_session, "contact")
    counts = await type_counts(perf_session)
    record = (await perf_session.execute(build_query(rtype, []).limit(1))).scalars().first()

    async def run():
        await referrers(perf_session, record)

    timing = await repeat(run, reps=REPS, warmup=3)
    with capture(perf_db.engine) as box:
        await run()
    Results.add(
        "referrers (global, 0 collections declared)",
        counts.get("contact", 0),
        timing,
        statements=box.count,
    )
