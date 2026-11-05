"""A rate's two halves come from one snapshot (B5): a send accepted while the
report is being read is in both ``sent`` and the accepted numerator, or in neither.

The relay's acceptance is interleaved just before the engagement read, in its
own committed transaction (a file database on SQLite, so it commits apart).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from simple_module_db import finalize_session
from sm_newsletter.core.settings import NewsletterSettings
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Campaign
from sm_newsletter.tracking import report as report_mod
from sm_newsletter.tracking.record import record_open

from tests.support.campaign_world import set_columns
from tests.support.sending import NOW, make_app
from tests.support.tracking_world import accept, sent_campaign, set_send

T = "default"


@pytest.fixture
async def state(tmp_path):
    _, db_state, _ = await make_app(file=tmp_path / "report.db")
    yield db_state
    await db_state.engine.dispose()


async def test_acceptance_between_reads_keeps_rate_consistent(state, monkeypatch):
    cid, (sid,) = await sent_campaign(state)
    await set_columns(state, T, cid, started_at=NOW, status="sending", sent_count=0)
    await set_send(state, T, sid, status="sending")
    with tenant_scope(T):
        async with state.session_factory() as db:
            await record_open(db, tenant_id=T, campaign_id=cid, send_id=sid, now=NOW)
            await finalize_session(db)
    original = report_mod.accepted_engagement

    async def interleaved(*args, **kwargs):
        await accept(state, T, sid, NOW)
        return await original(*args, **kwargs)

    monkeypatch.setattr(report_mod, "accepted_engagement", interleaved)
    with tenant_scope(T):
        async with state.session_factory() as db:
            campaign = await db.get(Campaign, cid)
            got = await report_mod.campaign_report(
                db,
                NewsletterSettings(),
                tenant_id=T,
                campaign=campaign,
                now=NOW + timedelta(hours=1),
            )
    assert got.opens_unique_accepted <= got.sent
    assert (got.sent, got.opens_unique_accepted) == (1, 1)
