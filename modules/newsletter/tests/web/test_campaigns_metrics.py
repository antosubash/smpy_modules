"""The campaign list's engagement fields (B5): accepted-only unique opens and clicks."""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from simple_module_db import finalize_session
from sm_newsletter.core import constants
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.tracking.record import record_click, record_open
from sm_newsletter.web.endpoints import campaigns_api

from tests.support.app import build_app
from tests.support.campaign_world import seed_campaign, set_columns
from tests.support.records_seed import seed_list
from tests.support.sending import NOW
from tests.support.tracking_world import accept, link_ids, send_row, sent_campaign, set_send

BASE = f"{constants.ROUTE_PREFIX_API}/campaigns"
VIEW = {"x-perms": constants.PERM_VIEW}


@pytest_asyncio.fixture
async def built():
    app, state = await build_app()
    await seed_list(state, "default")
    yield app, state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def client(built):
    app, _ = built
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_list_has_metrics(client, built):
    _, state = built
    cid, (accepted, unknown) = await sent_campaign(state, recipients=2)
    await set_send(state, "default", unknown, status="failed")
    await set_columns(state, "default", cid, started_at=NOW, finished_at=NOW)
    for sid in (accepted, unknown):
        with tenant_scope("default"):
            async with state.session_factory() as db:
                await record_open(db, tenant_id="default", campaign_id=cid, send_id=sid, now=NOW)
                await finalize_session(db)
    assert (await send_row(state, "default", unknown)).opened_at is not None
    (lid,) = await link_ids(state, "default", cid)
    with tenant_scope("default"):
        async with state.session_factory() as db:
            await record_click(
                db,
                tenant_id="default",
                campaign_id=cid,
                send_id=accepted,
                link_id=lid,
                now=NOW,
                count_open=True,
            )
            await finalize_session(db)
    empty = await seed_campaign(state, "default")
    items = {i["id"]: i for i in (await client.get(BASE, headers=VIEW)).json()["items"]}
    got = items[cid]
    assert (got["opens_unique_accepted"], got["clicks_unique_accepted"]) == (1, 1)
    assert got["started_at"] is not None and got["finished_at"] is not None
    assert items[empty]["opens_unique_accepted"] == 0
    assert items[empty]["started_at"] is None
    detail = (await client.get(f"{BASE}/{cid}", headers=VIEW)).json()
    assert "opens_unique_accepted" not in detail and "clicks_unique_accepted" not in detail


async def test_list_rate_pair_from_one_snapshot(tmp_path, monkeypatch):
    """A send accepted between the page read and the engagement read is in both
    ``sent_count`` and the accepted numerator, or in neither (B5)."""
    app, state = await build_app(file=tmp_path / "list.db")
    try:
        await seed_list(state, "default")
        cid, (sid,) = await sent_campaign(state)
        await set_columns(state, "default", cid, status="sending", sent_count=0)
        await set_send(state, "default", sid, status="sending")
        with tenant_scope("default"):
            async with state.session_factory() as db:
                await record_open(db, tenant_id="default", campaign_id=cid, send_id=sid, now=NOW)
                await finalize_session(db)
        original = campaigns_api.accepted_engagement

        async def interleaved(*args, **kwargs):
            await accept(state, "default", sid, NOW)
            return await original(*args, **kwargs)

        monkeypatch.setattr(campaigns_api, "accepted_engagement", interleaved)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            items = {i["id"]: i for i in (await c.get(BASE, headers=VIEW)).json()["items"]}
    finally:
        await state.engine.dispose()
    got = items[cid]
    assert got["opens_unique_accepted"] <= got["sent_count"]
    assert (got["sent_count"], got["opens_unique_accepted"]) == (1, 1)
