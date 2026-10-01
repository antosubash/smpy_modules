"""The export is a stream, and this is the test that keeps it one.

Two claims, neither of which survives someone "simplifying" the walk into a
list comprehension:

* **It pages.** Counted with a statement counter on the engine rather than
  inferred from timing: a ``SELECT`` per batch is the shape, and both failure
  modes are visible in the count — one statement means the whole type was
  loaded at once, five thousand means a query per record.
* **Memory stays flat.** Measured with ``tracemalloc`` against the size of
  what was produced. The assertion is deliberately relative (peak well under
  the bytes emitted) rather than an absolute megabyte figure, because an
  absolute one is a number that drifts with Python versions and gets raised
  until it means nothing.

Driven against ``services.export`` rather than through the HTTP client on
purpose: ``httpx``'s test transport buffers the whole response body, so an
end-to-end assertion about memory would be an assertion about ``httpx``.
"""

from __future__ import annotations

import tracemalloc

import pytest
from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db
from sm_records.models import Base, Record, RecordType
from sm_records.services import export as export_service
from sm_records.settings import RecordsSettings
from sqlalchemy import event, insert
from sqlalchemy.pool import StaticPool

RECORDS = 5000
PADDING = "x" * 1000
"""Each record carries about a kilobyte, so the whole document is several
megabytes — otherwise "peak is under the output size" is satisfied by any
implementation, including the one this test exists to refuse."""


@pytest.fixture
async def big_type():
    """5,000 records, inserted with one core ``INSERT`` rather than 5,000 ORM
    writes: what is under test is the *read*, and seeding it through
    ``create_record`` would spend a minute proving nothing."""
    state = init_db("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    register_listeners(state)
    async with state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with state.session_factory() as session:
        rtype = RecordType(
            key="bulk",
            label="Bulk",
            label_plural="Bulks",
            fields=[
                {"key": "name", "type": "text", "label": "Name", "indexed": True},
                {"key": "body", "type": "longtext", "label": "Body"},
            ],
            schema_version=1,
        )
        session.add(rtype)
        await session.flush()
        await session.execute(
            insert(Record.__table__),
            [
                {
                    "uuid": f"{index:032x}",
                    "type_id": rtype.id,
                    # A Core bulk insert is never stamped from the bound
                    # tenant (tenancy design FACT 1e), so it names its own.
                    "tenant_id": rtype.tenant_id,
                    "data": {"name": f"row {index}", "body": PADDING},
                    "schema_version": 1,
                    "version": 1,
                    "status": "draft",
                    "position": 0,
                    "display_title": f"row {index}",
                    "is_deleted": False,
                }
                for index in range(RECORDS)
            ],
        )
        await session.commit()
        type_id = int(rtype.id)
    yield state, type_id
    await state.engine.dispose()


def _count_selects(state) -> list[str]:
    seen: list[str] = []

    @event.listens_for(state.engine.sync_engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "records_record" in statement:
            seen.append(statement)

    return seen


async def test_export_pages_and_keeps_memory_flat(big_type):
    state, type_id = big_type
    statements = _count_selects(state)
    settings = RecordsSettings()

    tracemalloc.start()
    try:
        total = 0
        peaks: list[int] = []
        async for chunk in export_service.iter_json(
            state.session_factory, type_id, settings=settings
        ):
            total += len(chunk)
            peaks.append(tracemalloc.get_traced_memory()[1])
            tracemalloc.reset_peak()
    finally:
        tracemalloc.stop()

    # 5,000 records at a batch of 500: ten full batches plus the one that
    # comes back empty and ends the walk. Neither 1 (the whole type at once)
    # nor 5,000 (a query per record) is in this window.
    expected = RECORDS // settings.reindex_batch_size + 1
    assert expected - 1 <= len(statements) <= expected + 2, len(statements)
    assert total > RECORDS * len(PADDING)

    # Flat, in the sense that matters: the cost of the eighth batch is the
    # cost of the third. A walk that accumulated — a list of rows, an identity
    # map nobody expunges — would climb monotonically across this window.
    plateau = peaks[2:-1]
    assert max(plateau) <= min(plateau) * 1.2, peaks

    # And bounded below the document it produced. An implementation that
    # materialised the export first peaks at several times ``total`` (every
    # row exists at once as an ORM object, a view dict and a JSON string);
    # this one never holds more than a batch of each.
    assert max(peaks) < total, (max(peaks), total)


async def test_walk_orders_by_id_and_visits_every_record(big_type):
    """Keyset paging is only correct if it is total: every record exactly
    once, in ``Record.id`` order, with no row straddling a batch boundary."""
    state, type_id = big_type
    settings = RecordsSettings()
    async with state.session_factory() as session:
        from sm_records.services.types import get_type_by_id

        rtype = await get_type_by_id(session, type_id)
        seen: list[int] = []
        async for batch in export_service.walk_records(session, rtype, settings=settings):
            seen.extend(int(record.id) for record in batch)
    assert len(seen) == RECORDS
    assert len(set(seen)) == RECORDS
    assert seen == sorted(seen)
