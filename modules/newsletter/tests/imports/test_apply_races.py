"""Admission against a concurrent opt-out (Codex finding 1): the refusal read holds.

An import admits a subscribed row only when the address is suppressed nowhere and
unsubscribed on none of the tenant's lists (D1). An unsubscribe on list ``other`` that
commits after that read but before the create on ``news`` would leave the address mailable
on ``news`` whenever the mirror is slow or fails. So the batch takes records' per-address
opt-out lock (and then the list's type lock) before it reads anything it admits from.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest
import pytest_asyncio
from sm_newsletter.core.suppression.hashing import email_hash
from sm_newsletter.imports import apply
from sm_records.contracts.newsletter import unsubscribe
from sm_records.contracts.newsletter_import import address_lock_key, address_lock_key_from_hash
from sm_records.core import events
from sqlalchemy import event

from tests.imports.world import FIELDS, upload
from tests.pg_support import USING_POSTGRES
from tests.support.app import build_app
from tests.support.import_world import (
    SETTINGS,
    SUB,
    counts,
    job_row,
    queued,
    records_of,
    run,
    suppression_rows,
)
from tests.support.records_seed import seed_list, seed_subscriber

pytestmark = pytest.mark.unbound_tenant

ADA = "ada@example.org"


@pytest_asyncio.fixture
async def state(tmp_path):
    _app, st = await build_app(file=tmp_path / "races.db")
    await seed_list(st, "default", fields=FIELDS)
    await seed_list(st, "default", "other")
    yield st
    await st.engine.dispose()


def test_lock_key_agrees_with_the_suppression_hash():
    """Records derives the opt-out lock key from newsletter's own ``email_hash``."""
    messy = "  Ada@Example.ORG "
    key = address_lock_key("default", messy)
    assert address_lock_key_from_hash("default", email_hash(messy)) == key
    assert address_lock_key("default", ADA) == key


@pytest.mark.skipif(not USING_POSTGRES, reason="two real transactions need Postgres")
async def test_unsubscribe_elsewhere_during_admission_is_honoured(state, monkeypatch):
    """Ada unsubscribes from ``other`` (held open, the mirror withheld: no bus) while the
    import of her into ``news`` runs. Whichever way the two would have interleaved, the
    import reads her opt-out only once it has committed, so she is skipped, not created."""
    uuid = await seed_subscriber(state, "default", ADA, "confirmed", "other")
    jid = await queued(state, upload(SUB, [[ADA, "Ada", "", ""]]))
    checked, committed = asyncio.Event(), asyncio.Event()
    real = apply._refused

    async def gated(*args, **kw):
        found = await real(*args, **kw)
        checked.set()
        await committed.wait()
        return found

    monkeypatch.setattr(apply, "_refused", gated)
    async with state.session_factory() as first:
        assert await unsubscribe(
            first,
            tenant_id="default",
            type_key="other",
            uuid=uuid,
            unless_confirmed_after=None,
            settings=SETTINGS,
        )
        task = asyncio.create_task(run(state.session_factory, jid))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(checked.wait(), 1)
        read_before_commit = checked.is_set()
        await events.commit(first)
    committed.set()
    assert await asyncio.wait_for(task, 10) == "done"
    assert ADA not in await records_of(state)
    assert counts(await job_row(state, jid)) == (0, 0, 1, 0, 0)  # skipped_suppressed
    assert await suppression_rows(state) == []  # refused from records' state, not the mirror
    assert not read_before_commit  # the import waited for the opt-out's address lock


async def test_batch_locks_before_the_refusal_read(state):
    """Both backends: the batch's first lock (Postgres' address lock, SQLite's type-lock
    ``UPDATE``, the database's write lock) precedes its first suppression read."""
    jid = await queued(state, upload(SUB, [[ADA, "Ada", "", ""]]))
    seen: list[str] = []

    def note(_conn, _cursor, statement, *_args):
        seen.append(" ".join(statement.split()).lower())

    engine = state.engine.sync_engine
    event.listen(engine, "before_cursor_execute", note)
    try:
        assert await run(state.session_factory, jid) == "done"
    finally:
        event.remove(engine, "before_cursor_execute", note)
    lock = "pg_advisory_xact_lock" if USING_POSTGRES else "update records_type"
    first_lock = next((i for i, s in enumerate(seen) if lock in s), len(seen))
    first_read = next(i for i, s in enumerate(seen) if "from newsletter_suppression" in s)
    assert first_lock < first_read
