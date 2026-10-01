"""The rebuild must not run inside the transaction that scheduled it.

Every other test in this directory runs against ``:memory:`` on a ``StaticPool``,
where *every* session shares one connection — so the deferred rebuild reads the
schema write before it is committed and can never lose a lock to it. Both are
artefacts of the harness, and together they hid the defect QA found on a real
server: an index-affecting ``PUT`` left ``reindex_pending`` set forever, and the
rebuild died with ``sqlite3.OperationalError: database is locked`` on its first
``DELETE FROM records_index_text``.

The cause was FastAPI's ordering, not SQLite's. A ``BackgroundTasks`` entry runs
inside the ``AsyncExitStack`` that ``fastapi.routing.request_response`` opens
around the response, and ``get_db``'s commit is registered on that same stack —
so the rebuild ran while the request still held the write lock, and the request
could not release it until the rebuild returned. :mod:`sm_records.deferred` is
the fix; this module is the proof, and so it insists on the two things the rest
of the suite gives away: a **file-backed** database and the **default pool**,
which is one connection per session exactly as a server has.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sm_records.models import IndexText
from sm_records.settings import RecordsSettings
from sqlalchemy import select

from tests.app_harness import seed_record, seed_type

#: Small enough that the seeded records below span several batches, so the
#: per-batch commit of ``run_pending`` is exercised rather than assumed.
BATCH = 4
RECORDS = 14


def _field(key: str, **overrides: Any) -> dict[str, Any]:
    definition = {"key": key, "type": "text", "label": key.title()}
    definition.update(overrides)
    return definition


@pytest_asyncio.fixture
async def file_client(file_client):
    """The shared :func:`file_client`, with the batch size these tests need."""
    file_client.app.state.sm_records.settings = RecordsSettings(reindex_batch_size=BATCH)
    return file_client


async def _pending(client: AsyncClient) -> dict[str, str]:
    response = await client.get("/api/records/types/product")
    assert response.status_code == 200, response.text
    return response.json()["reindex_pending"]


async def _readers(client: AsyncClient, stop: asyncio.Event) -> int:
    """The banner poll QA had running: ``GET`` the type until told to stop.

    They are not the lock holder — the defect reproduces without them — but a
    rebuild that cannot survive concurrent readers is not fixed either, and
    this is the traffic the type editor actually generates.
    """
    seen = 0
    while not stop.is_set():
        assert (await client.get("/api/records/types/product")).status_code == 200
        seen += 1
        await asyncio.sleep(0.01)
    return seen


async def _put_indexed(client: AsyncClient, version: int, indexed: set[str]):
    return await client.put(
        "/api/records/types/product",
        json={
            "expected_version": version,
            "fields": [
                _field("name", indexed="name" in indexed),
                _field("sku", indexed="sku" in indexed),
            ],
        },
    )


async def _change_schema_under_polling(client: AsyncClient, version: int, indexed: set[str]):
    stop = asyncio.Event()
    readers = asyncio.create_task(_readers(client, stop))
    try:
        return await _put_indexed(client, version, indexed)
    finally:
        stop.set()
        await readers


async def test_an_index_affecting_change_finishes_its_rebuild_on_a_file_database(
    file_client, file_db, caplog
):
    """Two index-affecting changes in a row, each with the banner poll running.

    Before :mod:`sm_records.deferred` the first left ``reindex_pending`` set
    (the rebuild read the type row as it was *before* the uncommitted schema
    write, found nothing pending and returned ``0``) and the second died with
    ``database is locked`` after the driver's five-second busy timeout — which
    is also five seconds added to the ``PUT`` the user was waiting on.
    """
    caplog.set_level(logging.WARNING)
    rtype = await seed_type(
        file_db, "product", [_field("name"), _field("sku")], display_field="name"
    )
    for index in range(RECORDS):
        await seed_record(file_db, rtype, {"name": f"name-{index}", "sku": f"sku-{index}"})

    first = await _change_schema_under_polling(file_client, rtype.schema_version, {"sku"})
    assert first.status_code == 200, first.text
    assert set(first.json()["reindex_pending"]) == {"sku"}, "the PUT should enqueue the rebuild"
    assert await _pending(file_client) == {}, "the deferred rebuild never cleared its marker"

    second = await _change_schema_under_polling(
        file_client, first.json()["version"], {"sku", "name"}
    )
    assert second.status_code == 200, second.text
    assert await _pending(file_client) == {}, "the second rebuild never cleared its marker"

    assert "database is locked" not in caplog.text

    # The point of the rebuild: both fields answer filters, over every record.
    async with file_db.session_factory() as session:
        rows = (await session.execute(select(IndexText.field_key))).scalars().all()
    assert sorted(set(rows)) == ["name", "sku"]
    assert len(rows) == RECORDS * 2

    filtered = await file_client.get(
        "/api/records/types/product/records", params=[("filter", "sku:eq:sku-3")]
    )
    assert filtered.status_code == 200, filtered.text
    assert [item["data"]["name"] for item in filtered.json()["items"]] == ["name-3"]


async def test_the_deferred_job_runs_only_after_the_request_released_its_session(
    file_client, file_db
):
    """The invariant behind the fix, asserted directly rather than inferred.

    A job that observes the schema write is a job that ran after the commit —
    and on SQLite, a session that can read the new ``schema_version`` from a
    second connection is a session whose writer has let go of the file.
    """
    rtype = await seed_type(file_db, "product", [_field("name"), _field("sku")])
    await seed_record(file_db, rtype, {"name": "only", "sku": "one"})

    seen: list[tuple[int, dict[str, str]]] = []
    from sm_records.services import reindex_runner

    original = reindex_runner.run_pending

    async def observing(db_state, type_id: int, *, settings):
        async with db_state.session_factory() as session:
            row = (await session.execute(select(reindex_runner.RecordType))).scalars().one()
            seen.append((row.schema_version, dict(row.reindex_pending or {})))
        return await original(db_state, type_id, settings=settings)

    reindex_runner.run_pending = observing
    try:
        response = await _put_indexed(file_client, rtype.schema_version, {"sku"})
    finally:
        reindex_runner.run_pending = original

    assert response.status_code == 200, response.text
    assert len(seen) == 1
    schema_version, pending = seen[0]
    assert schema_version == response.json()["schema_version"]
    assert set(pending) == {"sku"}


@pytest.mark.parametrize("message", ["database is locked", "database table is locked"])
def test_both_wordings_of_sqlite_lock_contention_are_retried(message):
    """``_is_locked`` is a string match, so the strings are pinned here."""
    from sm_records.services.reindex_runner import _is_locked
    from sqlalchemy.exc import OperationalError

    assert _is_locked(OperationalError("DELETE", {}, Exception(message)))
    assert not _is_locked(OperationalError("DELETE", {}, Exception("no such table")))
