"""A plugin call runs on its own connection: a timeout, a cancelled statement or bad SQL can
only break that connection, never the request's session. Needs real connections (file SQLite,
or Postgres): the in-memory test engine shares one."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import pytest
from sm_events.calendar import source_entries
from sm_events.calendar.plugin_runner import Call, run_sources
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar
from sqlalchemy import select, text

from tests.pg_support import USING_POSTGRES, make_db_state
from tests.support.sources import FakeSource, item, ok

START, END = datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 8, 1, tzinfo=UTC)
SLOW_SQL = (
    "SELECT pg_sleep(30)"
    if USING_POSTGRES
    else "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 6000000) "
    "SELECT count(*) FROM n"
)


@pytest.fixture
async def state(tmp_path):
    st = await make_db_state(file=None if USING_POSTGRES else tmp_path / "plugins.db")
    yield st
    await st.engine.dispose()


async def seeded(state):
    with tenant_scope("default"):
        async with state.session_factory() as s:
            s.add(Calendar(slug="c", name="C", owner_id="o", visibility="public"))
            await s.commit()


async def call_for(session):
    cal = (await session.execute(select(Calendar))).scalars().one()
    return Call(source_entries.source_calendar(cal), source_entries.SourceEntry("acme:x", {}), None)


def run(session, source, call, **kw):
    call = Call(call.calendar, call.entry, source)
    return run_sources(
        session,
        [call],
        tenant_id="default",
        viewer=None,
        start=START,
        end=END,
        locale="en",
        default_locale="en",
        **kw,
    )


def pool_out(state) -> int:
    return state.engine.pool.checkedout()


async def slow_query(ctx, start, end):
    await ctx.db.execute(text(SLOW_SQL))
    return []


async def test_the_plugin_gets_its_own_session(state):
    await seeded(state)
    seen = {}

    async def look(ctx, start, end):
        seen["db"] = ctx.db
        seen["calendars"] = (await ctx.db.execute(select(Calendar))).scalars().all()
        return []

    with tenant_scope("default"):
        async with state.session_factory() as host:
            await run(host, FakeSource("acme:x", look), await call_for(host))
            assert seen["db"] is not host and len(seen["calendars"]) == 1


async def test_a_timeout_inside_a_query_leaves_the_host_session_usable(state, monkeypatch):
    from sm_events.core import constants

    monkeypatch.setattr(constants, "SOURCE_TIMEOUT_SECONDS", 0.3)
    monkeypatch.setattr(constants, "SOURCE_MIN_SLICE_SECONDS", 0.01)
    await seeded(state)
    with tenant_scope("default"):
        async with state.session_factory() as host:
            call = await call_for(host)
            began = time.monotonic()
            result = await run(host, FakeSource("acme:x", slow_query), call)
            if USING_POSTGRES:
                assert time.monotonic() - began < 3  # the database stops the statement
            assert result.statuses[0].status == "timeout"
            # the host's own session is intact: its next statements work
            assert len((await host.execute(select(Calendar))).scalars().all()) == 1
            again = await run(host, FakeSource("acme:x", ok(item("a"))), call)
            assert again.statuses[0].status == "ok"
    assert pool_out(state) == 0


async def test_bad_sql_leaves_the_host_session_usable(state):
    from tests.support.sources import bad_sql

    await seeded(state)
    with tenant_scope("default"):
        async with state.session_factory() as host:
            result = await run(host, FakeSource("acme:x", bad_sql), await call_for(host))
            assert (result.statuses[0].status, result.statuses[0].code) == ("failed", "raised")
            assert len((await host.execute(select(Calendar))).scalars().all()) == 1
    assert pool_out(state) == 0


async def test_a_cancelled_request_mid_plugin_leaves_no_connection_checked_out(state):
    await seeded(state)
    started = asyncio.Event()

    async def hang(ctx, start, end):
        await ctx.db.execute(text("SELECT 1"))
        started.set()
        await asyncio.sleep(30)
        return []

    with tenant_scope("default"):
        async with state.session_factory() as host:
            call = await call_for(host)
            baseline = pool_out(state)
            task = asyncio.ensure_future(run(host, FakeSource("acme:x", hang), call))
            await asyncio.wait_for(started.wait(), 5)
            assert pool_out(state) == baseline + 1  # the plugin's own connection
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.sleep(0.1)
            assert pool_out(state) == baseline
            assert len((await host.execute(select(Calendar))).scalars().all()) == 1


async def test_a_write_by_the_plugin_is_refused_and_not_kept(state):
    from tests.support.sources import writes_and_flushes

    await seeded(state)
    with tenant_scope("default"):
        async with state.session_factory() as host:
            result = await run(host, FakeSource("acme:x", writes_and_flushes), await call_for(host))
            assert (result.statuses[0].status, result.statuses[0].code) == ("failed", "wrote")
            from sm_events.models import Category

            assert (await host.execute(select(Category))).scalars().all() == []
    assert pool_out(state) == 0


async def test_a_real_engine_never_takes_the_shared_fallback(state, monkeypatch):
    """The savepoint fallback is only for engines that share one connection (the in-memory test
    engine); a file or Postgres engine always gets a connection of its own."""
    from sm_events.calendar import plugin_isolation

    async def refuse(*_a, **_k):
        raise AssertionError("the shared fallback was used")

    monkeypatch.setattr(plugin_isolation, "_run_shared", refuse)
    await seeded(state)
    with tenant_scope("default"):
        async with state.session_factory() as host:
            assert plugin_isolation._own_session(host) is not None
            result = await run(host, FakeSource("acme:x", ok(item("a"))), await call_for(host))
            assert result.statuses[0].status == "ok"
