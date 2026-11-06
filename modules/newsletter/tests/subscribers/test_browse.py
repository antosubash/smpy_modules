"""The subscriber browse and detail through the records contract (PR 6, Task 8)."""

from __future__ import annotations

import pytest
from simple_module_db import finalize_session
from sm_newsletter.core.errors import NotFound
from sm_newsletter.core.errors_audience import InvalidSegment
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Segment
from sm_newsletter.subscribers.browse import browse, detail

from tests.support.lift_world import seed_row
from tests.support.records_seed import (
    TAGS,
    restrict_list,
    seed_list,
    seed_subscriber,
    set_list_kind,
)

pytestmark = pytest.mark.unbound_tenant

ADA, BOB, CY, DI = "ada@example.org", "bob@example.org", "cy@example.org", "di@example.org"


async def _browse(db_state, tenant="default", key="news", roles=None, **kw):
    args = {"status": None, "q": None, "tag": None, "segment_id": None, "offset": 0, "limit": 50}
    async with db_state.session_factory() as s:
        return await browse(s, tenant_id=tenant, list_type_key=key, roles=roles, **{**args, **kw})


async def _world(db_state):
    await seed_list(db_state, "default", fields=[TAGS])
    return {
        "ada": await seed_subscriber(db_state, "default", ADA, "confirmed", data={"tags": ["vip"]}),
        "bob": await seed_subscriber(db_state, "default", BOB, "confirmed", data={"tags": ["vip"]}),
        "cy": await seed_subscriber(db_state, "default", CY, "pending", data={"tags": []}),
        "di": await seed_subscriber(db_state, "default", DI, "unsubscribed", data={"tags": []}),
    }


async def test_browse_counts_and_status_filter(db_state):
    await _world(db_state)
    res = await _browse(db_state)
    assert res.total == 4
    assert res.counts == {"pending": 1, "confirmed": 2, "unsubscribed": 1}
    only = await _browse(db_state, status="pending")
    assert [r.hit.email for r in only.rows] == [CY] and only.total == 1
    assert only.counts["confirmed"] == 2  # counts ignore the status filter
    found = await _browse(db_state, q="ADA@")
    assert [r.hit.email for r in found.rows] == [ADA]
    assert found.counts == {"pending": 0, "confirmed": 1, "unsubscribed": 0}


async def test_search_tag_and_segment_combine(db_state):
    await _world(db_state)
    with tenant_scope("default"):
        async with db_state.session_factory() as s:
            seg = Segment(
                name="s", list_type_key="news", filters=["sm_email:contains:ada"], rules=[]
            )
            s.add(seg)
            await finalize_session(s)
            sid = seg.id
    both = await _browse(db_state, tag="vip", segment_id=sid)
    assert [r.hit.email for r in both.rows] == [ADA]
    assert both.counts["confirmed"] == 1
    vip = await _browse(db_state, tag="vip")
    assert {r.hit.email for r in vip.rows} == {ADA, BOB}
    with pytest.raises(InvalidSegment):
        await _bad_segment(db_state)


async def _bad_segment(db_state):
    with tenant_scope("default"):
        async with db_state.session_factory() as s:
            seg = Segment(name="bad", list_type_key="news", filters=["bogus"], rules=[])
            s.add(seg)
            await finalize_session(s)
            sid = seg.id
    await _browse(db_state, segment_id=sid)


async def test_suppressed_flag(db_state):
    await _world(db_state)
    await seed_row(db_state, "default", ADA, "hard_bounce")
    await seed_row(db_state, "default", BOB, "unsubscribed", key="other")  # another list
    res = await _browse(db_state)
    flags = {r.hit.email: r.suppressed for r in res.rows}
    assert flags == {ADA: True, BOB: False, CY: False, DI: False}


async def test_unreadable_or_non_list_is_404(db_state):
    await _world(db_state)
    with pytest.raises(NotFound):
        await _browse(db_state, key="nope")
    await restrict_list(db_state, "default", "news", ["editor"])
    with pytest.raises(NotFound):
        await _browse(db_state, roles=["viewer"])
    assert (await _browse(db_state, roles=["editor"])).total == 4
    await set_list_kind(db_state, "default", "news", "form")
    with pytest.raises(NotFound):
        await _browse(db_state, roles=["editor"])


async def test_detail_lists_suppressions_with_block(db_state):
    ids = await _world(db_state)
    await seed_row(db_state, "default", ADA, "hard_bounce")
    await seed_row(db_state, "default", DI, "unsubscribed", key="news")
    async with db_state.session_factory() as s:
        got = await detail(
            s, tenant_id="default", list_type_key="news", uuid=ids["ada"], roles=None
        )
        di = await detail(s, tenant_id="default", list_type_key="news", uuid=ids["di"], roles=None)
    assert [(r.reason, block) for r, block in got.suppressions] == [("hard_bounce", None)]
    assert got.hit.email == ADA and got.records_url.endswith(ids["ada"])
    assert [(r.reason, block) for r, block in di.suppressions] == [
        ("unsubscribed", "opt_out_stands")
    ]


async def test_detail_other_tenants_uuid_404(db_state):
    await _world(db_state)
    await seed_list(db_state, "other", fields=[TAGS])
    theirs = await seed_subscriber(db_state, "other", "x@example.org", "confirmed")
    async with db_state.session_factory() as s:
        with pytest.raises(NotFound):
            await detail(s, tenant_id="default", list_type_key="news", uuid=theirs, roles=None)
