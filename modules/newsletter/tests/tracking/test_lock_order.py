"""Cancel and the tracking counters take their locks in one order (M4).

Tracking locks the send row, then the campaign row; ``cancel`` must do the
same. Each round holds the trackers' send-row locks until cancel has issued
its send ``UPDATE``, then lets them on to the campaign row: with cancel's old
order (campaign row first) Postgres reports a deadlock. On SQLite one writer
holds the whole database, so the round only checks the outcome.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest
from simple_module_db import finalize_session
from sm_newsletter.campaigns import lifecycle
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Link
from sm_newsletter.tracking import record
from sqlalchemy import event

from tests.pg_support import USING_POSTGRES
from tests.support.campaign_world import campaign_row, seed_campaign, seed_sends, send_rows
from tests.support.sending import NOW, T, make_app
from tests.support.tracking_world import counters, link_ids

ROUNDS = 10
WAIT_S = 5.0
# On SQLite the second tracker's first write waits for the first's commit.
TRACKERS_AT_GATE = 2 if USING_POSTGRES else 1


class _Gate:
    """Trackers wait at the campaign bump until cancel's send ``UPDATE`` is issued."""

    def __init__(self) -> None:
        self.reached = 0
        self.trackers_in = asyncio.Event()
        self.cancel_started = asyncio.Event()

    def arrived(self) -> None:
        self.reached += 1
        if self.reached >= TRACKERS_AT_GATE:
            self.trackers_in.set()


@pytest.fixture
async def state(tmp_path):
    _, db_state, _ = await make_app(file=tmp_path / "lock.db")
    yield db_state
    await db_state.engine.dispose()


async def _committed(state: Any, work: Any) -> Any:
    with tenant_scope(T):
        async with state.session_factory() as db:
            out = await work(db)
            await finalize_session(db)
            return out


async def _round(state: Any, gate: _Gate) -> None:
    cid = await seed_campaign(state, T, status="sending", started_at=NOW)
    await _committed(state, lambda db: _add_link(db, cid))
    (lid,) = await link_ids(state, T, cid)
    clicked, opened, _sent = await seed_sends(state, T, cid, ["queued", "queued", "sent"])

    def click(db):
        return record.record_click(
            db, tenant_id=T, campaign_id=cid, send_id=clicked, link_id=lid, now=NOW, count_open=True
        )

    def open_(db):
        return record.record_open(db, tenant_id=T, campaign_id=cid, send_id=opened, now=NOW)

    async def cancel() -> Any:
        await asyncio.wait_for(gate.trackers_in.wait(), WAIT_S)
        return await _committed(
            state,
            lambda db: lifecycle.cancel(db, tenant_id=T, campaign_id=cid, roles=[], now=NOW),
        )

    outcomes = await asyncio.gather(
        _committed(state, click), _committed(state, open_), cancel(), return_exceptions=True
    )
    errors = [o for o in outcomes if isinstance(o, BaseException)]
    assert not errors, f"a transaction failed: {errors!r}"
    assert outcomes[:2] == [True, True]
    assert (await campaign_row(state, T, cid)).status == "cancelled"
    rows = await send_rows(state, T, cid)
    assert [r.status for r in rows] == ["cancelled", "cancelled", "sent"]
    assert (rows[0].first_clicked_at, rows[0].open_count) == (NOW, 1)
    assert rows[1].open_count == 1
    assert await counters(state, T, cid) == {
        "open_unique_count": 2,
        "open_total_count": 2,
        "click_unique_count": 1,
        "click_total_count": 1,
    }


async def _add_link(db, cid: int) -> None:
    db.add(Link(tenant_id=T, campaign_id=cid, position=1, url="https://e.org/a"))


async def test_cancel_and_tracking_never_deadlock(state, monkeypatch):
    gate = _Gate()
    real_bump = record._bump_campaign

    async def gated_bump(session, **kw):
        gate.arrived()  # this tracker holds its send-row lock
        # Cancel never reaching its send UPDATE: go on, the asserts tell.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(gate.cancel_started.wait(), WAIT_S)
        await real_bump(session, **kw)

    def on_execute(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE NEWSLETTER_SEND SET STATUS"):
            gate.cancel_started.set()

    monkeypatch.setattr(record, "_bump_campaign", gated_bump)
    sync_engine = state.engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", on_execute)
    try:
        for _ in range(ROUNDS):
            gate.__init__()
            await _round(state, gate)
            assert gate.cancel_started.is_set(), "cancel never reached its send UPDATE"
    finally:
        event.remove(sync_engine, "before_cursor_execute", on_execute)
