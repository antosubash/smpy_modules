"""Schema operations: the dry run, the reindex, and the two bulk writes.

These are the operations design §8.9 says are explicitly *not* request work,
so the numbers that matter are wall time and memory over the whole type, plus
the throughput the batched rebuild achieves — not a per-request latency.

Every test here runs against ``perf_db_copy``, a throwaway copy of the seeded
database, because all of them mutate the type they measure.
"""

from __future__ import annotations

import time
import tracemalloc

import pytest
from sm_records.schema.diff import diff_fields
from sm_records.services import _orphaned, schema_change
from sm_records.services._dry_run import dry_run
from sm_records.services._payload import field_defs
from sm_records.services._schema import normalise
from sm_records.services.reindex_runner import run_pending
from sm_records.services.revisions import list_type_revisions

from tests.perf._bench import Results, Timing, capture
from tests.perf.conftest import load_type

pytestmark = pytest.mark.perf


def _fields(rtype) -> list[dict]:
    return [dict(raw) for raw in (rtype.fields or [])]


def _one(timing_ms: float) -> Timing:
    """A single-shot measurement as a :class:`Timing` — these operations run
    for seconds and are not repeated twenty times."""
    return Timing(samples=[timing_ms])


async def test_dry_run_restrictive(perf_db_copy):
    """``POST /schema/preview``'s expensive half: validate every record of the
    type, trash included, against a proposed model.

    The change made restrictive here is ``order.gift`` becoming required —
    the seeder leaves it unset on some records, so the scan has real work and
    real failures to collect.
    """
    async with perf_db_copy.session_factory() as session:
        rtype = await load_type(session, "order")
        raw = _fields(rtype)
        for field in raw:
            if field["key"] == "gift":
                field["required"] = True
        new_defs, _ = normalise(raw, _settings())

        tracemalloc.start()
        started = time.perf_counter()
        report = await dry_run(session, rtype, new_defs, batch_size=500)
        elapsed = (time.perf_counter() - started) * 1000.0
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

    Results.add(
        "dry_run(order, gift required)",
        report.checked,
        _one(elapsed),
        statements="batched",
        plan=f"peak {peak / 1e6:.1f} MB",
    )
    Results.note(
        f"dry_run checked {report.checked} order record(s), {report.failing} failing, "
        f"{report.checked / max(elapsed / 1000.0, 1e-9):.0f} rec/s"
    )


def _settings():
    from sm_records.settings import RecordsSettings

    return RecordsSettings()


async def test_apply_restrictive_with_force(perf_db_copy):
    """The apply path re-runs the dry run inline before writing (§8.9), so a
    forced restrictive change costs one more full pass plus one row write."""
    settings = _settings()
    async with perf_db_copy.session_factory() as session:
        rtype = await load_type(session, "order")
        raw = _fields(rtype)
        for field in raw:
            if field["key"] == "gift":
                field["required"] = True
        started = time.perf_counter()
        _updated, diff = await schema_change.apply(
            session,
            rtype,
            fields_raw=raw,
            expected_version=rtype.version,
            settings=settings,
            force=True,
        )
        await session.commit()
        elapsed = (time.perf_counter() - started) * 1000.0
    Results.add("schema apply(force, restrictive)", 0, _one(elapsed), statements="batched")
    assert diff.changes


async def test_toggle_indexed_and_reindex_batches(perf_db_copy):
    """Toggle ``indexed`` on one field, then run the rebuild at three batch
    sizes. The number recorded is records rebuilt per second."""
    settings = _settings()
    for batch_size in (100, 500, 2000):
        async with perf_db_copy.session_factory() as session:
            rtype = await load_type(session, "store")
            raw = _fields(rtype)
            for field in raw:
                if field["key"] == "street":
                    field["indexed"] = not field.get("indexed", False)
            await schema_change.apply(
                session,
                rtype,
                fields_raw=raw,
                expected_version=rtype.version,
                settings=settings,
            )
            await session.commit()
            type_id = rtype.id

        settings.reindex_batch_size = batch_size
        started = time.perf_counter()
        count = await run_pending(perf_db_copy, type_id, settings=settings)
        elapsed = time.perf_counter() - started
        Results.add(
            f"reindex store (batch={batch_size})",
            count,
            _one(elapsed * 1000.0),
            statements="batched",
            plan=f"{count / max(elapsed, 1e-9):.0f} rec/s",
        )
        assert count >= 0


async def test_display_field_change_rebuilds_titles(perf_db_copy):
    """A ``display_field`` change enqueues a whole-type rebuild — every
    record's denormalised ``display_title`` is recomputed on top of the index
    rebuild, so this is the most expensive schema edit the module has."""
    settings = _settings()
    async with perf_db_copy.session_factory() as session:
        rtype = await load_type(session, "store")
        await schema_change.apply(
            session,
            rtype,
            expected_version=rtype.version,
            settings=settings,
            changes={"display_field": "city"},
        )
        await session.commit()
        type_id = rtype.id
    started = time.perf_counter()
    count = await run_pending(perf_db_copy, type_id, settings=settings)
    elapsed = time.perf_counter() - started
    Results.add(
        "display_field change, whole-type rebuild",
        count,
        _one(elapsed * 1000.0),
        statements="batched",
        plan=f"{count / max(elapsed, 1e-9):.0f} rec/s",
    )


async def test_orphaned_discard_bulk_write(perf_db_copy):
    """Remove a field, write one record so a value migrates under
    ``_orphaned``, then measure the count-and-discard pass — the one bulk
    payload write in the whole module (§8.8)."""
    settings = _settings()
    async with perf_db_copy.session_factory() as session:
        rtype = await load_type(session, "store")
        raw = [f for f in _fields(rtype) if f["key"] != "hours"]
        await schema_change.apply(
            session, rtype, fields_raw=raw, expected_version=rtype.version, settings=settings
        )
        await session.commit()

        started = time.perf_counter()
        conflicts = await _orphaned.count_conflicts(
            session, rtype, ["hours"], batch_size=settings.reindex_batch_size
        )
        count_ms = (time.perf_counter() - started) * 1000.0

        started = time.perf_counter()
        touched = await _orphaned.discard(
            session, rtype, ["hours"], batch_size=settings.reindex_batch_size
        )
        await session.commit()
        discard_ms = (time.perf_counter() - started) * 1000.0

    Results.add("_orphaned count_conflicts(store.hours)", sum(conflicts.values()), _one(count_ms))
    Results.add("_orphaned discard(store.hours)", touched, _one(discard_ms))


async def test_type_revision_rollback(perf_db_copy):
    """Rolling a type back to an earlier revision goes through ``apply``, so
    it costs the same classification and dry run as the change it undoes."""
    settings = _settings()
    async with perf_db_copy.session_factory() as session:
        rtype = await load_type(session, "store")
        raw = _fields(rtype)
        raw.append(
            {
                "key": "perf_note",
                "type": "text",
                "label": "Perf note",
                "required": False,
                "unique": False,
                "indexed": False,
                "default": None,
                "help": None,
                "constraints": {},
                "options": {},
            }
        )
        await schema_change.apply(
            session, rtype, fields_raw=raw, expected_version=rtype.version, settings=settings
        )
        await session.commit()
        revisions = await list_type_revisions(session, rtype)
        target = revisions[1].version if len(revisions) > 1 else revisions[0].version

        started = time.perf_counter()
        await schema_change.rollback(
            session, rtype, to_version=target, expected_version=rtype.version, settings=settings
        )
        await session.commit()
        elapsed = (time.perf_counter() - started) * 1000.0
    Results.add("type revision rollback", 0, _one(elapsed), statements="batched")


async def test_diff_is_pure(perf_db_copy):
    """The classification itself touches no database — worth a line in the
    report so nobody optimises it."""
    async with perf_db_copy.session_factory() as session:
        rtype = await load_type(session, "order")
        defs = field_defs(rtype)
        with capture(perf_db_copy.engine) as box:
            diff_fields(defs, defs)
    assert box.count == 0
    Results.note("diff_fields issues no SQL; the dry run is the whole cost of a preview")
