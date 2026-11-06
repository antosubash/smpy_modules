"""Scheduling a tag or segment audience: its terms snapshotted, records' refusals."""

from __future__ import annotations

import pytest
from simple_module_db import finalize_session
from sm_newsletter.core.errors import NewsletterError
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Segment
from sm_records.contracts.newsletter import SubscriberFilterError

from tests.campaigns.test_lifecycle import _schedule
from tests.support.campaign_world import campaign_row, render_row, set_columns
from tests.support.records_seed import TAGS, seed_list
from tests.support.sending import T


async def _segment_audience(state, cid) -> list[str]:
    """``cid`` moved to a tagged list, its audience a segment of it; the segment's terms."""
    await seed_list(state, T, "vips", fields=[TAGS])
    filters = ["tags:in:vip"]
    with tenant_scope(T):
        async with state.session_factory() as db:
            seg = Segment(tenant_id=T, name="VIPs", list_type_key="vips", filters=filters)
            db.add(seg)
            await finalize_session(db)
    await set_columns(state, T, cid, list_type_key="vips", audience=f"segment:{seg.id}")
    return filters


async def test_schedule_snapshots_audience_filters(built):
    app, state, cid = built
    filters = await _segment_audience(state, cid)
    assert (await _schedule(app, state, cid)).status == "scheduled"
    assert (await render_row(state, T, cid)).audience_filters == filters


async def test_schedule_refuses_filter_records_cannot_answer(built, monkeypatch):
    app, state, cid = built
    await _segment_audience(state, cid)

    async def refuse(*_args, **_kwargs):
        raise SubscriberFilterError("not_indexed")

    monkeypatch.setattr("sm_newsletter.segments.store.count_subscribers", refuse)
    with pytest.raises(NewsletterError) as err:
        await _schedule(app, state, cid)
    assert (err.value.status, err.value.code) == (422, "invalid_segment")
    assert (await campaign_row(state, T, cid)).status == "draft"
    assert await render_row(state, T, cid) is None


@pytest.mark.parametrize("audience", ["tag:", "segment:"])
async def test_schedule_refuses_half_set_audience(built, audience):
    """Codex P1: even a half-set audience written behind the PATCH's back is
    never scheduled (it would not mean the whole list)."""
    app, state, cid = built
    await set_columns(state, T, cid, audience=audience)
    with pytest.raises(NewsletterError) as err:
        await _schedule(app, state, cid)
    assert (err.value.status, err.value.code) == (422, "invalid_audience")
    assert (await campaign_row(state, T, cid)).status == "draft"
    assert await render_row(state, T, cid) is None
