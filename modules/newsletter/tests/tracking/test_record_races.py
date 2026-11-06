"""Two requests recording at once: the counters stay exact (T9, T8)."""

from __future__ import annotations

import asyncio

import pytest
from simple_module_db import finalize_session
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.tracking.record import record_click, record_open

from tests.support.sending import NOW, make_app
from tests.support.tracking_world import clicks, counters, link_ids, sent_campaign

T = "default"


@pytest.fixture
async def state(tmp_path):
    _, db_state, _ = await make_app(file=tmp_path / "track.db")
    yield db_state
    await db_state.engine.dispose()


async def _one(state, work) -> bool:
    with tenant_scope(T):
        async with state.session_factory() as db:
            ok = await work(db)
            await finalize_session(db)
            return ok


async def test_concurrent_first_opens_count_one_unique(state):
    cid, (sid,) = await sent_campaign(state)

    def open_(db):
        return record_open(db, tenant_id=T, campaign_id=cid, send_id=sid, now=NOW)

    assert await asyncio.gather(_one(state, open_), _one(state, open_)) == [True, True]
    got = await counters(state, T, cid)
    assert (got["open_unique_count"], got["open_total_count"]) == (1, 2)


async def test_concurrent_first_clicks_one_row(state):
    cid, (sid,) = await sent_campaign(state)
    (lid,) = await link_ids(state, T, cid)

    def click(db):
        return record_click(
            db,
            tenant_id=T,
            campaign_id=cid,
            send_id=sid,
            link_id=lid,
            now=NOW,
            count_open=True,
        )

    assert await asyncio.gather(_one(state, click), _one(state, click)) == [True, True]
    (row,) = await clicks(state, T)
    assert row.click_count == 2
    got = await counters(state, T, cid)
    assert (got["click_unique_count"], got["click_total_count"]) == (1, 2)
    assert (got["open_unique_count"], got["open_total_count"]) == (1, 1)
