"""All-or-nothing on SQLite, where a savepoint is not automatically inside one.

pysqlite's legacy transaction control emits ``BEGIN`` only before the first
DML statement it recognises. A batch whose first statement was ``SAVEPOINT``
therefore had that savepoint *start* the transaction, its ``RELEASE`` commit
it, and the outer rollback at the end of a refused batch undo nothing — so
"nothing was changed" was true on Postgres and false on the backend most
installs develop against. `services.bulk.apply_bulk` takes ``lock_type``
before the loop, which is an ``UPDATE`` on SQLite and therefore the ``BEGIN``
the savepoints need.

Every test here builds its own SQLite database (``make_sqlite_db_state``)
rather than the suite's, because this is about that driver: on the Postgres
job the rest of the bulk suite would still pass with the lock removed, and
this file is what would not.

The assertions read the rows through a second session rather than through the
API, so nothing about the read path can make an unchanged row look changed or
the other way round.
"""

from __future__ import annotations

from typing import Any

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sm_records.models import Record, RecordRevision
from sqlalchemy import func, select

from tests.app_harness import ADMIN, build_app, roles
from tests.bulk_helpers import API, BULK, make_product, make_records
from tests.pg_support import make_sqlite_db_state


@pytest_asyncio.fixture
async def sqlite_client(tmp_path):
    """The harness's client, pinned to in-memory SQLite."""
    db_state = await make_sqlite_db_state()
    app, _ = await build_app(tmp_path, db_state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.app = app  # type: ignore[attr-defined]
        client.db_state = db_state  # type: ignore[attr-defined]
        yield client
    await db_state.engine.dispose()


async def _rows(db_state: Any) -> dict[str, tuple[int, bool]]:
    """``{uuid: (version, is_deleted)}`` for every record, trash included."""
    async with db_state.session_factory() as session:
        found = (
            (await session.execute(select(Record).execution_options(include_deleted=True)))
            .scalars()
            .all()
        )
        return {row.uuid: (row.version, row.is_deleted) for row in found}


async def _revisions(db_state: Any) -> int:
    async with db_state.session_factory() as session:
        return int((await session.execute(select(func.count(RecordRevision.id)))).scalar_one())


def test_the_fixture_really_is_sqlite(sqlite_client):
    """Otherwise this whole file could pass by not testing anything."""
    assert sqlite_client.db_state.engine.dialect.name == "sqlite"


async def test_a_refused_batch_leaves_every_record_untouched_on_sqlite(sqlite_client):
    await make_product(sqlite_client)
    uuids = await make_records(sqlite_client, 3)
    before = await _rows(sqlite_client.db_state)
    revisions_before = await _revisions(sqlite_client.db_state)

    refused = await sqlite_client.post(
        BULK,
        json={"action": "trash", "uuids": [*uuids, "f" * 32]},
        headers=roles(ADMIN),
    )

    assert refused.status_code == 409, refused.text
    assert [entry["uuid"] for entry in refused.json()["report"]["failed"]] == ["f" * 32]
    # The mechanism, stated as the two columns a trash moves: not one record's
    # version moved, and not one is in the trash. Before the lock, the first
    # three were trashed and committed by the ``RELEASE`` of their own
    # savepoints while the response said nothing had changed.
    assert await _rows(sqlite_client.db_state) == before
    assert all(deleted is False for _, deleted in before.values())
    # And the revision a trash appends is not there either — the rollback
    # covers everything the attempt wrote, not only the document row.
    assert await _revisions(sqlite_client.db_state) == revisions_before


async def test_a_refused_publish_batch_bumps_nobody_on_sqlite(sqlite_client):
    """The other write shape: ``publish`` goes through ``update_record``, which
    bumps the version inside the savepoint."""
    await make_product(sqlite_client)
    uuids = await make_records(sqlite_client, 2)
    before = await _rows(sqlite_client.db_state)

    refused = await sqlite_client.post(
        BULK,
        json={"action": "publish", "uuids": [*uuids, "f" * 32]},
        headers=roles(ADMIN),
    )

    assert refused.status_code == 409, refused.text
    assert await _rows(sqlite_client.db_state) == before
    for uuid in uuids:
        read = await sqlite_client.get(f"{API}/{uuid}", headers=roles(ADMIN))
        assert read.json()["status"] == "draft"


async def test_a_batch_that_refuses_nothing_still_commits_on_sqlite(sqlite_client):
    """The other half of the pair: the lock must not leave the batch in a
    transaction nobody commits."""
    await make_product(sqlite_client)
    uuids = await make_records(sqlite_client, 2)

    done = await sqlite_client.post(
        BULK, json={"action": "trash", "uuids": uuids}, headers=roles(ADMIN)
    )

    assert done.status_code == 200, done.text
    assert all(deleted for _, deleted in (await _rows(sqlite_client.db_state)).values())
