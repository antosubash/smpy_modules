"""The move's locking protocol on Postgres, with the wait *observed* (#82).

Each test holds one operation's transaction open, starts the other on its own
connection, and waits until ``pg_stat_activity`` reports that backend waiting
on a lock — so "the second operation blocked" is a fact the test read, not a
sleep it hoped was long enough. Then the first commits and the test checks
what the second did: refused with a ``409`` when the move went first, carried
out in full when the move went second, and never a deadlock either way.

The cascades are the cases a per-row lock order got wrong: a trash used to
write the rows of every type it reached without those types' locks, so a move
holding its rows in id order and a cascade writing them in graph order could
each wait for the other. Every writer now takes the type locks first, in id
order (``services._lock.lock_types``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from sm_records.models import RecordType
from sm_records.services import _lifecycle
from sm_records.services._empty_trash import empty_trash
from sm_records.services._lock import lock_types
from sm_records.services.errors import Conflict
from sm_records.services.records import create_record, get_deleted_record, get_record
from sqlalchemy import text

from tests.collections_harness import EVENTS  # noqa: F401 - declares the collections
from tests.move_race_support import SETTINGS, count, move, seed
from tests.pg_support import USING_POSTGRES

pytestmark = pytest.mark.skipif(
    not USING_POSTGRES, reason="two blocking transactions need Postgres; set RECORDS_TEST_URL"
)

MOVED = "moved to another collection"


def _relation(key: str, target: str) -> dict:
    return {
        "key": key,
        "type": "relation",
        "label": key.title(),
        "indexed": True,
        "options": {"target_type": target, "on_delete": "cascade"},
    }


async def _blocked(state: Any, pid: int) -> None:
    """Return once backend ``pid`` is waiting on a lock; fail after 10 s.

    A fresh connection per poll: ``pg_stat_activity`` is a per-transaction
    snapshot, so polling inside one transaction would read the same row
    forever."""
    for _ in range(400):
        async with state.engine.connect() as conn:
            wait = await conn.scalar(
                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": pid},
            )
        if wait == "Lock":
            return
        await asyncio.sleep(0.025)
    raise AssertionError(f"backend {pid} never waited on a lock")


Action = Callable[[Any], Awaitable[Any]]


async def _second_waits_for_first(state: Any, first: Action, second: Action) -> Any:
    """Run ``first`` and hold it uncommitted; run ``second`` until it is seen
    waiting; commit ``first``; return what ``second`` returned or raised (and
    commit it if it returned)."""
    async with state.session_factory() as one, state.session_factory() as two:
        await first(one)
        pid = int(await two.scalar(text("SELECT pg_backend_pid()")))

        async def run() -> Any:
            try:
                result = await second(two)
            except Conflict as exc:
                await two.rollback()
                return exc
            await two.commit()
            return result

        task = asyncio.create_task(run())
        await _blocked(state, pid)
        assert not task.done()
        await one.commit()
        return await asyncio.wait_for(task, timeout=30)


async def _stale(session: Any, type_id: int) -> RecordType:
    return await session.get(RecordType, type_id)


async def test_a_write_blocked_behind_a_move_is_refused_once_it_commits(db_state):
    type_id, _ = await seed(db_state)

    async def second(session):
        # Read while the move is uncommitted: the committed row, pre-move.
        stale = await _stale(session, type_id)
        assert stale.collection is None
        return await create_record(session, stale, data={"name": "late"}, settings=SETTINGS)

    outcome = await _second_waits_for_first(db_state, lambda s: move(s, type_id), second)
    assert isinstance(outcome, Conflict) and MOVED in str(outcome)
    assert await count(db_state, None, type_id) == 0
    assert await count(db_state, "events", type_id) == 3


@pytest.mark.parametrize("operation", ["trash", "restore", "purge", "empty_trash"])
async def test_a_lifecycle_operation_blocked_behind_a_move_is_refused(db_state, operation):
    type_id, uuids = await seed(db_state)

    async def second(session):
        rtype = await _stale(session, type_id)  # read before the move commits
        if operation == "trash":
            live = await get_record(session, rtype, uuids["live-0"])
            return await _lifecycle.soft_delete_record(session, rtype, live, settings=SETTINGS)
        if operation == "empty_trash":
            return await empty_trash(session, rtype)
        binned = await get_deleted_record(session, rtype, uuids["binned"])
        if operation == "restore":
            return await _lifecycle.restore_record(session, rtype, binned, settings=SETTINGS)
        return await _lifecycle.hard_delete_record(session, rtype, binned)

    outcome = await _second_waits_for_first(db_state, lambda s: move(s, type_id), second)
    assert isinstance(outcome, Conflict) and MOVED in str(outcome)
    assert await count(db_state, None, type_id) == 0
    assert await count(db_state, "events", type_id) == 3
    assert await count(db_state, "events", type_id, trashed=True) == 1


async def _cascade_graph(state: Any) -> tuple[int, int, str]:
    """``author`` and ``book`` (cascade → author); returns the type ids and
    the uuid of the author whose trash cascades into a book."""
    author_id, authors = await seed(state)
    book_id, _ = await seed(state, "book", [*_fields(), _relation("author", "author")])
    async with state.session_factory() as session:
        book = await session.get(RecordType, book_id)
        target = {"type": "author", "uuid": authors["live-0"]}
        await create_record(
            session, book, data={"name": "dune", "author": target}, settings=SETTINGS
        )
        await session.commit()
    return author_id, book_id, authors["live-0"]


def _fields() -> list[dict]:
    return [{"key": "name", "type": "text", "label": "Name", "indexed": True}]


async def _trash(session: Any, type_id: int, uuid: str) -> None:
    rtype = await _stale(session, type_id)
    record = await get_record(session, rtype, uuid)
    await _lifecycle.soft_delete_record(session, rtype, record, settings=SETTINGS)


async def test_a_move_waits_for_a_cascade_into_its_type_and_moves_the_result(db_state):
    author_id, book_id, author = await _cascade_graph(db_state)
    outcome = await _second_waits_for_first(
        db_state, lambda s: _trash(s, author_id, author), lambda s: move(s, book_id)
    )
    assert not isinstance(outcome, Conflict)
    assert await count(db_state, None, book_id) == 0
    assert await count(db_state, "events", book_id) == 4
    assert await count(db_state, "events", book_id, trashed=True) == 2  # seed's + the cascade


async def test_a_cascade_into_a_moving_type_waits_and_is_refused(db_state):
    author_id, book_id, author = await _cascade_graph(db_state)
    outcome = await _second_waits_for_first(
        db_state, lambda s: move(s, book_id), lambda s: _trash(s, author_id, author)
    )
    assert isinstance(outcome, Conflict)
    assert await count(db_state, None, author_id, trashed=True) == 1  # only the seed's
    assert await count(db_state, "events", book_id, trashed=True) == 1


async def test_a_self_cascade_and_a_move_of_the_type_serialise(db_state):
    """Codex's case: a same-type cascade wrote child then parent while the move
    locked rows in id order. Both now queue on the one type lock."""
    type_id, uuids = await seed(db_state, "node", [*_fields(), _relation("parent", "node")])
    async with db_state.session_factory() as session:
        node = await session.get(RecordType, type_id)
        parent = {"type": "node", "uuid": uuids["live-0"]}
        await create_record(
            session, node, data={"name": "child", "parent": parent}, settings=SETTINGS
        )
        await session.commit()
    outcome = await _second_waits_for_first(
        db_state, lambda s: _trash(s, type_id, uuids["live-0"]), lambda s: move(s, type_id)
    )
    assert not isinstance(outcome, Conflict)
    assert await count(db_state, "events", type_id) == 4
    assert await count(db_state, "events", type_id, trashed=True) == 3


async def test_a_lock_wanted_out_of_order_is_refused_rather_than_awaited(db_state):
    """A holds the higher id and asks for the lower one B holds: ``NOWAIT``
    makes that a ``409`` at once, where waiting would have been a deadlock
    the moment B asked for A's."""
    low_id, _ = await seed(db_state, "low")
    high_id, _ = await seed(db_state, "high")
    async with db_state.session_factory() as a, db_state.session_factory() as b:
        low_a, high_a = await a.get(RecordType, low_id), await a.get(RecordType, high_id)
        low_b, high_b = await b.get(RecordType, low_id), await b.get(RecordType, high_id)
        await lock_types(a, [high_a])
        await lock_types(b, [low_b])
        with pytest.raises(Conflict, match="being written by another request"):
            await asyncio.wait_for(lock_types(a, [low_a]), timeout=5)
        await a.rollback()
        await asyncio.wait_for(lock_types(b, [high_b]), timeout=5)
        await b.commit()
