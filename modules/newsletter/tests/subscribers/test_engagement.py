"""One subscriber's engagement: aggregates only (PR 6, Task 8; G15)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from simple_module_db import finalize_session
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Campaign, Send
from sm_newsletter.subscribers.engagement import engagement

pytestmark = pytest.mark.unbound_tenant

UUID = "a" * 32
T = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


async def _campaign(db_state, tenant, name) -> int:
    with tenant_scope(tenant):
        async with db_state.session_factory() as s:
            c = Campaign(name=name, list_type_key="news", subject="s", body=[], status="sent")
            s.add(c)
            await finalize_session(s)
            return c.id


async def _send(db_state, tenant, campaign_id, **kw) -> None:
    with tenant_scope(tenant):
        async with db_state.session_factory() as s:
            s.add(Send(campaign_id=campaign_id, record_uuid=UUID, email="a@example.org", **kw))
            await finalize_session(s)


async def _get(db_state, tenant="default", uuid=UUID):
    async with db_state.session_factory() as s:
        return await engagement(s, tenant_id=tenant, record_uuid=uuid)


async def test_engagement_aggregates(db_state):
    one, two, three = [await _campaign(db_state, "default", n) for n in ("one", "two", "three")]
    await _send(
        db_state, "default", one, status="sent", sent_at=T, opened_at=T + timedelta(hours=1)
    )
    await _send(
        db_state,
        "default",
        two,
        status="sent",
        sent_at=T + timedelta(days=1),
        opened_at=T + timedelta(days=1, hours=1),
        first_clicked_at=T + timedelta(days=1, hours=2),
    )
    await _send(db_state, "default", three, status="failed", sent_at=T + timedelta(days=2))
    got = await _get(db_state)
    assert got.campaigns_sent == 2
    assert got.opened_campaigns == 2
    assert got.clicked_campaigns == 1
    assert got.last_campaign_name == "two"
    assert got.last_sent_at is not None and got.last_sent_at.replace(tzinfo=UTC) == T + timedelta(
        days=1
    )


async def test_engagement_empty_is_zeros(db_state):
    got = await _get(db_state)
    assert (got.campaigns_sent, got.opened_campaigns, got.clicked_campaigns) == (0, 0, 0)
    assert got.last_sent_at is None and got.last_campaign_name is None


async def test_engagement_pins_the_tenant(db_state):
    other = await _campaign(db_state, "other", "theirs")
    await _send(db_state, "other", other, status="sent", sent_at=T, opened_at=T)
    got = await _get(db_state)
    assert got.campaigns_sent == 0 and got.opened_campaigns == 0
    assert (await _get(db_state, "other")).campaigns_sent == 1
