"""The per-type lock, on the database whose branch of it has never been run.

:func:`sm_records.records.services._claims.lock_type` has two implementations — a
no-op ``UPDATE records_type SET version = version`` that takes SQLite's
``RESERVED`` lock, and ``SELECT … FOR UPDATE`` everywhere else. Until this
file, only the first was ever executed: ``tests/test_unique_concurrency.py``
races eight writers against a SQLite *file*, and
``test_lock_type_is_a_write_on_sqlite_and_a_row_lock_elsewhere`` pins the
Postgres branch by compiling it, which proves the statement is emitted and
nothing about whether it holds.

This file runs the same claims against Postgres, and only against Postgres:
every test here skips unless ``RECORDS_TEST_URL`` names one (see
:mod:`tests.pg_support`). Twenty writers rather than the other file's eight,
because ``FOR UPDATE`` queues every waiter on one row and twenty is enough for
a lock that does not actually block to show up as several winners rather than
as an unlucky two.

**Through the service layer, on a session per writer.** The lock serialises
transactions, so each writer needs its own connection — an ``AsyncClient``
would give them that too, but through a request pipeline whose own commit
ordering is a second thing that could explain a pass.
"""

from __future__ import annotations

import pytest

from tests.pg_support import USING_POSTGRES
from tests.support.postgres_lock_cases import (
    WRITERS,
    _field,
    _race,
    _seed_type,
    _stored,
)

pytestmark = pytest.mark.skipif(
    not USING_POSTGRES,
    reason="the FOR UPDATE branch of lock_type only exists on Postgres; "
    "set RECORDS_TEST_URL=postgresql+asyncpg://…",
)
# The tests take ``conftest``'s ``db_state``: a truncated Postgres database on
# the pooled engine. Not ``StaticPool`` and not a shared session, so
# ``session_factory()`` inside a task gets a connection of its own and twenty
# of them are twenty transactions.

"""Wide enough that a lock which does not hold loses visibly. Eight — the
number ``test_unique_concurrency`` uses — was chosen for SQLite's write queue;
nothing here waits on one."""


async def test_twenty_concurrent_creates_of_one_unique_value_store_exactly_one(db_state):
    """``FOR UPDATE`` closes the check-then-act window of design §7.8.

    ``email`` is ``unique`` and is *not* the ``slug_field``, so no database
    constraint covers it — the index tables are shared across every field of a
    kind, which is the reason §7.8 gives for the rule being application-level.
    Twenty writers pass ``ensure_unique`` only if the row lock did not hold.
    """
    type_id = await _seed_type(
        db_state,
        "contact",
        [_field("name"), _field("email", unique=True)],
        display_field="name",
    )

    outcomes = await _race(db_state, type_id, {"name": "Ada", "email": "ada@example.com"})

    assert outcomes["integrity-error"] == 0, f"an IntegrityError escaped: {dict(outcomes)}"
    assert outcomes["created"] == 1, f"expected one winner, got {dict(outcomes)}"
    assert outcomes["conflict"] == WRITERS - 1, dict(outcomes)
    assert await _stored(db_state, type_id) == 1


async def test_twenty_concurrent_slug_claims_leave_one_winner(db_state):
    """§5's slug claim, where a real constraint *does* back the check.

    ``ix_records_record_type_slug`` is a partial unique index, so the losers
    can be refused by either half — ``ensure_slug_free`` before the flush or
    the index during it. Both must arrive as ``Conflict``: an ``IntegrityError``
    reaching the caller is the 500 :func:`flush_write` was written to stop, and
    on Postgres it would additionally poison the transaction.
    """
    type_id = await _seed_type(
        db_state,
        "product",
        [_field("name"), _field("sku")],
        display_field="name",
        slug_field="sku",
    )

    outcomes = await _race(db_state, type_id, {"name": "Widget", "sku": "W-1"})

    assert outcomes["integrity-error"] == 0, f"an IntegrityError escaped: {dict(outcomes)}"
    assert outcomes["created"] == 1, dict(outcomes)
    assert set(outcomes) <= {"created", "conflict"}, dict(outcomes)
    assert await _stored(db_state, type_id) == 1
