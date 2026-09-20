"""Import and export at scale — Phase 5 §2: throughput, memory, and a refusal.

Three numbers a host planning a migration actually needs, and one it needs
more: **what an export costs**, **what the round trip back costs**, and **how
long an ``abort`` import takes to refuse a file whose last row is bad** — the
worst case for a mode whose whole promise is that nothing was written.

The memory number is taken under ``tracemalloc`` for the reason
``test_schema_ops`` takes the dry run's: the export is a *stream* and the claim
that it never holds the type in memory is a claim about peak allocation, not
about wall clock. ``walk_records`` expunges between batches, so the peak should
be a batch and a JSON chunk rather than a type.

Everything writes to ``perf_db_copy``; an import against the shared seeded file
would leave it in a different shape than the next run expects.
"""

from __future__ import annotations

import json
import time
import tracemalloc

import pytest
from sm_records.contracts.io import ImportFormat, ImportMode, OnError
from sm_records.services import export as export_service
from sm_records.services.errors import ImportRefused
from sm_records.services.import_ import ImportOptions, import_records
from sm_records.settings import RecordsSettings

from tests.perf._bench import Results, Timing
from tests.perf.conftest import load_type, type_counts

pytestmark = pytest.mark.perf

TYPE = "order"


def _rate(rows: int, seconds: float) -> str:
    return f"{rows / max(seconds, 1e-9):,.0f} rows/s"


async def _drain(stream) -> str:
    parts = []
    async for chunk in stream:
        parts.append(chunk)
    return "".join(parts)


async def _discard(stream) -> int:
    """Consume the stream and keep nothing — how a streaming response reads it.

    Keeping the text is what a *test* wants and exactly what the memory number
    must not include: a caller that joins the whole export holds the file, and
    the claim being measured is that the **exporter** does not."""
    total = 0
    async for chunk in stream:
        total += len(chunk)
    return total


async def _export(db_state, settings, fmt: str) -> tuple[str, float, int]:
    """``(text, seconds, peak bytes)`` for one whole-type export.

    Two passes, because the two numbers are incompatible: the timed pass
    collects the text (a later test imports it back), and the ``tracemalloc``
    pass throws every chunk away so the peak is the generator's own — a batch
    of records and one chunk of output — rather than the file a client would
    be streaming to disk.
    """
    async with db_state.session_factory() as session:
        rtype = await load_type(session, TYPE)
        type_id = rtype.id
    iterator = export_service.iter_json if fmt == "json" else export_service.iter_csv
    began = time.perf_counter()
    text = await _drain(iterator(db_state.session_factory, type_id, settings=settings))
    elapsed = time.perf_counter() - began
    tracemalloc.start()
    await _discard(iterator(db_state.session_factory, type_id, settings=settings))
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return text, elapsed, peak


@pytest.fixture
def io_settings() -> RecordsSettings:
    return RecordsSettings()


async def test_export_json_and_csv(perf_db_copy, io_settings):
    """The whole type, both formats, streamed — wall time, rate, peak memory."""
    async with perf_db_copy.session_factory() as session:
        counts = await type_counts(session)
    n = counts.get(TYPE, 0)
    exported = {}
    peaks: dict[str, int] = {}
    for fmt, suffix in (("json", "JSON"), ("csv", "CSV")):
        text, elapsed, peak = await _export(perf_db_copy, io_settings, fmt)
        exported[fmt] = text
        Results.add(
            f"export {TYPE} as {suffix} (stream)",
            n,
            Timing([elapsed * 1000.0]),
            statements="batched",
            plan=f"{_rate(n, elapsed)}, peak {peak / 1e6:.1f} MB, {len(text) / 1e6:.1f} MB out",
        )
        peaks[fmt] = peak
        # The stream must not hold the type. The ceiling is an absolute one
        # rather than a fraction of the file, and deliberately loose: what it
        # has to catch is an exporter that buffers everything, which at the
        # sizes this suite is pointed at (20,000 records, and 100,000 in the
        # study) is tens of megabytes. The evidence that it does not is the
        # pair of numbers printed beside the file sizes — the two formats
        # produce files that differ by nearly 2x and peak within 10% of each
        # other, because the peak is a batch of records, not the output.
        assert peak < 64e6, f"{suffix} export peaked at {peak / 1e6:.1f} MB"
    parsed = json.loads(exported["json"])
    assert len(parsed["records"]) == n, "the JSON export lost rows"
    assert exported["csv"].count("\n") >= n, "the CSV export lost rows"
    Results.note(
        "export is keyset by id and expunges per batch: peak memory is one batch "
        f"and one chunk ({peaks['json'] / 1e6:.1f} MB for a "
        f"{len(exported['json']) / 1e6:.1f} MB JSON file, {peaks['csv'] / 1e6:.1f} MB "
        f"for a {len(exported['csv']) / 1e6:.1f} MB CSV one), not the {n}-record type"
    )


async def test_import_the_export_back_in_upsert_mode(perf_db_copy, io_settings):
    """A round trip: importing an export changes nothing (§2), at what rate.

    ``skipped`` is the number that says it: every row matched an existing
    record by ``uuid`` and compared equal, so the write pass has nothing to do
    and the cost is parse + validate + one batched match.
    """
    text, _elapsed, _peak = await _export(perf_db_copy, io_settings, "json")
    async with perf_db_copy.session_factory() as session:
        rtype = await load_type(session, TYPE)
        counts = await type_counts(session)
        n = counts.get(TYPE, 0)
        options = ImportOptions(
            mode=ImportMode.UPSERT, dry_run=False, on_error=OnError.ABORT, match_by="uuid"
        )
        began = time.perf_counter()
        report = await import_records(
            session, rtype, text, fmt=ImportFormat.JSON, options=options, settings=io_settings
        )
        elapsed = time.perf_counter() - began
        await session.commit()
        after = await type_counts(session)
    Results.add(
        f"import {TYPE} JSON, upsert (round trip)",
        n,
        Timing([elapsed * 1000.0]),
        statements="batched",
        plan=f"{_rate(report.total, elapsed)}, {report.skipped}/{report.total} skipped",
    )
    assert report.failed == 0, report.errors[:3]
    assert report.skipped == report.total, (
        f"a re-import of an export wrote {report.total - report.skipped} row(s)"
    )
    assert after.get(TYPE) == n, "an idempotent import changed the record count"
    Results.note(
        f"round trip skip rate {report.skipped}/{report.total} — "
        "importing an export twice is a no-op"
    )


async def test_abort_refuses_a_file_whose_last_row_is_bad(perf_db_copy, io_settings):
    """``on_error=abort`` with the bad row at the end — the worst case.

    The refusal has to come *before* anything is written, so the whole file is
    parsed and validated first and the cost of finding out is the cost of the
    validation pass. What this measures is that the refusal is that and nothing
    more: no rollback of half a type, and the record count unchanged.
    """
    text, _elapsed, _peak = await _export(perf_db_copy, io_settings, "json")
    payload = json.loads(text)
    rows = payload["records"]
    if not rows:
        pytest.skip("nothing to import")
    bad_at = min(10_000, len(rows)) - 1
    rows[bad_at] = {**rows[bad_at], "data": {**rows[bad_at]["data"], "total": "not-a-number"}}
    broken = json.dumps(payload)

    async with perf_db_copy.session_factory() as session:
        rtype = await load_type(session, TYPE)
        counts = await type_counts(session)
        n = counts.get(TYPE, 0)
        options = ImportOptions(
            mode=ImportMode.UPSERT, dry_run=False, on_error=OnError.ABORT, match_by="uuid"
        )
        began = time.perf_counter()
        with pytest.raises(ImportRefused) as raised:
            await import_records(
                session,
                rtype,
                broken,
                fmt=ImportFormat.JSON,
                options=options,
                settings=io_settings,
            )
        elapsed = time.perf_counter() - began
        await session.rollback()
        after = await type_counts(session)
    Results.add(
        f"import {TYPE} JSON, abort (bad row {bad_at + 1} of {len(rows)})",
        n,
        Timing([elapsed * 1000.0]),
        statements="batched",
        plan=f"refused in {elapsed * 1000.0:.0f} ms, nothing written",
    )
    assert raised.value.report.created == 0 and raised.value.report.updated == 0
    assert after.get(TYPE) == n, "an aborted import changed the record count"
