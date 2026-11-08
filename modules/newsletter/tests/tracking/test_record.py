"""Recording opens and clicks (Task 5): counters, tenancy, the stored-URL guard."""

from __future__ import annotations

from datetime import timedelta

import pytest
from simple_module_db import finalize_session
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Link
from sm_newsletter.tracking.record import link_url

from tests.support.sending import NOW
from tests.support.tracking_world import (
    clicked,
    clicks,
    counters,
    link_ids,
    opened,
    send_row,
    sent_campaign,
    set_send,
)

T = "default"


async def test_first_open_counts_unique_and_total(state):
    cid, (sid,) = await sent_campaign(state)
    assert await opened(state, cid, sid)
    row = await send_row(state, T, sid)
    assert (row.opened_at, row.open_count) == (NOW.replace(tzinfo=row.opened_at.tzinfo), 1)
    got = await counters(state, T, cid)
    assert (got["open_unique_count"], got["open_total_count"]) == (1, 1)


async def test_second_open_counts_total_only(state):
    cid, (sid,) = await sent_campaign(state)
    await opened(state, cid, sid)
    first = (await send_row(state, T, sid)).opened_at
    assert await opened(state, cid, sid, now=NOW + timedelta(hours=1))
    row = await send_row(state, T, sid)
    assert row.opened_at == first and row.open_count == 2
    got = await counters(state, T, cid)
    assert (got["open_unique_count"], got["open_total_count"]) == (1, 2)


async def test_open_for_missing_send_writes_nothing(state):
    cid, _ = await sent_campaign(state)
    assert not await opened(state, cid, 99999)
    assert set((await counters(state, T, cid)).values()) == {0}


@pytest.mark.unbound_tenant
async def test_open_pins_tenant(state):
    cid, (sid,) = await sent_campaign(state, "B")
    assert not await opened(state, cid, sid, tenant="A")
    assert (await send_row(state, "B", sid)).open_count == 0
    assert set((await counters(state, "B", cid)).values()) == {0}


async def test_open_pins_campaign(state):
    _cid, (sid,) = await sent_campaign(state)
    other, _ = await sent_campaign(state)
    assert not await opened(state, other, sid)
    assert (await send_row(state, T, sid)).open_count == 0


async def test_click_implies_open(state):
    cid, (sid,) = await sent_campaign(state)
    (lid,) = await link_ids(state, T, cid)
    assert await clicked(state, cid, sid, lid)
    row = await send_row(state, T, sid)
    assert row.opened_at is not None and row.open_count == 1
    got = await counters(state, T, cid)
    assert (got["open_unique_count"], got["open_total_count"]) == (1, 1)


async def test_click_after_open_does_not_count_open(state):
    cid, (sid,) = await sent_campaign(state)
    (lid,) = await link_ids(state, T, cid)
    await opened(state, cid, sid)
    await clicked(state, cid, sid, lid)
    got = await counters(state, T, cid)
    assert (got["open_unique_count"], got["open_total_count"]) == (1, 1)
    assert (await send_row(state, T, sid)).open_count == 1


async def test_click_without_count_open_leaves_opens(state):
    cid, (sid,) = await sent_campaign(state)
    (lid,) = await link_ids(state, T, cid)
    assert await clicked(state, cid, sid, lid, count_open=False)
    row = await send_row(state, T, sid)
    assert row.opened_at is None and row.open_count == 0
    got = await counters(state, T, cid)
    assert (got["open_unique_count"], got["open_total_count"]) == (0, 0)
    assert (got["click_unique_count"], got["click_total_count"]) == (1, 1)


async def test_click_for_missing_send_writes_nothing(state):
    cid, _ = await sent_campaign(state)
    (lid,) = await link_ids(state, T, cid)
    assert not await clicked(state, cid, 99999, lid)
    assert await clicks(state, T) == []
    assert set((await counters(state, T, cid)).values()) == {0}


async def test_repeat_click_same_link_one_unique(state):
    cid, (sid,) = await sent_campaign(state)
    (lid,) = await link_ids(state, T, cid)
    await clicked(state, cid, sid, lid)
    first = (await send_row(state, T, sid)).first_clicked_at
    await clicked(state, cid, sid, lid)
    (row,) = await clicks(state, T)
    assert row.click_count == 2
    got = await counters(state, T, cid)
    assert (got["click_unique_count"], got["click_total_count"]) == (1, 2)
    assert (await send_row(state, T, sid)).first_clicked_at == first


async def test_click_two_links_one_unique_recipient(state):
    cid, (sid,) = await sent_campaign(state, links=("https://e.org/a", "https://e.org/b"))
    a, b = await link_ids(state, T, cid)
    await clicked(state, cid, sid, a)
    await clicked(state, cid, sid, b)
    assert len(await clicks(state, T)) == 2
    got = await counters(state, T, cid)
    assert (got["click_unique_count"], got["click_total_count"]) == (1, 2)


async def test_link_url_resolves_and_pins(state):
    cid, _ = await sent_campaign(state)
    (lid,) = await link_ids(state, T, cid)
    with tenant_scope(T):
        async with state.session_factory() as db:
            args = {"tenant_id": T, "campaign_id": cid}
            assert await link_url(db, **args, position=1) == (lid, "https://e.org/a")
            assert await link_url(db, tenant_id="other", campaign_id=cid, position=1) is None


async def test_link_url_missing_or_foreign_campaign(state):
    cid, _ = await sent_campaign(state)
    other, _ = await sent_campaign(state, links=("https://e.org/x", "https://e.org/y"))
    with tenant_scope(T):
        async with state.session_factory() as db:
            assert await link_url(db, tenant_id=T, campaign_id=cid, position=2) is None
            assert await link_url(db, tenant_id=T, campaign_id=other, position=2) is not None


async def test_link_url_refuses_non_http_stored_value(state):
    cid, _ = await sent_campaign(state)
    with tenant_scope(T):
        async with state.session_factory() as db:
            db.add(Link(tenant_id=T, campaign_id=cid, position=2, url="javascript:x"))
            await finalize_session(db)
        async with state.session_factory() as db:
            assert await link_url(db, tenant_id=T, campaign_id=cid, position=2) is None


async def test_set_send_helper(state):
    _cid, (sid,) = await sent_campaign(state)
    await set_send(state, T, sid, status="failed")
    assert (await send_row(state, T, sid)).status == "failed"
