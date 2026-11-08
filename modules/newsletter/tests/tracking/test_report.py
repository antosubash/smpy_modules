"""The campaign report service (T14, B5): counters, link stats, accepted engagement."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sm_newsletter.core.settings import NewsletterSettings
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Campaign
from sm_newsletter.tracking.report import accepted_engagement, campaign_report, link_stats

from tests.support.campaign_world import campaign_row, seed_campaign, seed_sends, set_columns
from tests.support.sending import NOW, make_app
from tests.support.tracking_world import accept, clicked, link_ids, opened, sent_campaign, set_send

T = "default"
SETTINGS = NewsletterSettings()


@pytest.fixture
async def state():
    _, db_state, _ = await make_app()
    yield db_state
    await db_state.engine.dispose()


async def _report(state, cid, tenant=T, settings=SETTINGS):
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            campaign = await db.get(Campaign, cid)
            return await campaign_report(
                db, settings, tenant_id=tenant, campaign=campaign, now=NOW + timedelta(hours=2)
            )


async def test_report_counts(state):
    cid, (s1, s2, _s3) = await sent_campaign(state, recipients=3)
    (lid,) = await link_ids(state, T, cid)
    await seed_sends(state, T, cid, ["skipped_unsubscribed", "skipped_unsubscribed", "queued"])
    await set_columns(
        state,
        T,
        cid,
        started_at=NOW,
        recipient_count=6,
        sent_count=3,
        failed_count=1,
        bounced_count=2,
        suppressed_count=4,
        unsubscribe_count=5,
    )
    await opened(state, cid, s1)
    await opened(state, cid, s1)
    await clicked(state, cid, s2, lid)
    await clicked(state, cid, s2, lid)
    report = await _report(state, cid)
    got = (
        report.recipients,
        report.sent,
        report.failed,
        report.bounced,
        report.suppressed,
        report.skipped,
        report.unsubscribed,
    )
    assert got == (6, 3, 1, 2, 4, 2, 5)
    assert (report.opens_unique, report.opens_total) == (2, 3)
    assert (report.clicks_unique, report.clicks_total) == (1, 2)
    assert (report.opens_unique_accepted, report.clicks_unique_accepted) == (2, 1)
    assert report.tracking_opens and report.tracking_clicks
    assert report.status == "sent" and report.started_at is not None
    assert [(p.opens, p.clicks) for p in report.timeline] == [(2, 1), (0, 0)]


async def test_link_stats_order_and_zero_links(state):
    urls = ("https://e.org/a", "https://e.org/b", "https://e.org/c", "https://e.org/d")
    cid, (s1, s2) = await sent_campaign(state, links=urls, recipients=2)
    a, b, c, _d = await link_ids(state, T, cid)
    await clicked(state, cid, s1, b)
    await clicked(state, cid, s1, b)
    await clicked(state, cid, s1, c)
    await clicked(state, cid, s2, c)
    await clicked(state, cid, s2, a)
    with tenant_scope(T):
        async with state.session_factory() as db:
            stats = await link_stats(db, tenant_id=T, campaign_id=cid)
    # unique desc (c=2, a=1, b=1, d=0), then total desc (b=2 before a=1), then position.
    assert [(s.position, s.unique, s.total) for s in stats] == [
        (3, 2, 2),
        (2, 1, 2),
        (1, 1, 1),
        (4, 0, 0),
    ]
    assert stats[-1].url == "https://e.org/d"


@pytest.mark.unbound_tenant
async def test_report_pins_tenant(state):
    a, _ = await sent_campaign(state, "A")
    b, (sb,) = await sent_campaign(state, "B")
    (lb,) = await link_ids(state, "B", b)
    await clicked(state, b, sb, lb, tenant="B")
    await clicked(state, b, sb, lb, tenant="B")
    with tenant_scope("A"):
        async with state.session_factory() as db:
            stats_a = await link_stats(db, tenant_id="A", campaign_id=a)
            cross = await link_stats(db, tenant_id="A", campaign_id=b)
            accepted = await accepted_engagement(db, tenant_id="A", campaign_ids=[a, b])
    assert [(s.unique, s.total) for s in stats_a] == [(0, 0)]
    assert cross == []
    assert accepted == {a: (0, 0, 0), b: (0, 0, 0)}
    assert (await _report(state, b, tenant="B")).clicks_unique == 1


async def test_report_not_started_has_empty_timeline(state):
    cid = await seed_campaign(state, T, status="draft")
    report = await _report(state, cid)
    assert report.started_at is None and report.timeline == [] and report.links == []


async def test_unknown_outcome_engagement_not_in_rate(state):
    cid, (s1, s2) = await sent_campaign(state, recipients=2)
    (lid,) = await link_ids(state, T, cid)
    await set_send(state, T, s2, status="failed", error_kind="outcome_unknown")
    await set_columns(state, T, cid, started_at=NOW, sent_count=1, failed_count=1)
    for sid in (s1, s2):
        await clicked(state, cid, sid, lid)
    report = await _report(state, cid)
    assert (report.opens_unique, report.clicks_unique) == (2, 2)
    assert (report.opens_unique_accepted, report.clicks_unique_accepted) == (1, 1)
    assert report.opens_unique_accepted <= report.sent
    assert report.clicks_unique_accepted <= report.sent


async def test_engagement_before_acceptance_joins_later(state):
    cid, (sid,) = await sent_campaign(state)
    await set_columns(state, T, cid, started_at=NOW, status="sending")
    await set_send(state, T, sid, status="sending")
    await opened(state, cid, sid)
    before = await _report(state, cid)
    assert before.opens_unique == 1 and before.opens_unique_accepted == 0
    await accept(state, T, sid, NOW)
    after = await _report(state, cid)
    assert after.sent == 1 and after.opens_unique_accepted == 1
    assert after.opens_unique_accepted <= after.sent
    assert (await campaign_row(state, T, cid)).sent_count == 1


@pytest.mark.unbound_tenant
async def test_accepted_engagement_for_a_page(state):
    one, (s1,) = await sent_campaign(state, "A")
    two, (s2, _s3) = await sent_campaign(state, "A", recipients=2)
    none = await seed_campaign(state, "A", status="draft")
    other, (so,) = await sent_campaign(state, "B")
    await set_columns(state, "A", one, sent_count=1)
    await set_columns(state, "A", two, sent_count=2)
    (l1,) = await link_ids(state, "A", one)
    await clicked(state, one, s1, l1, tenant="A")
    await opened(state, two, s2, tenant="A")
    await opened(state, other, so, tenant="B")
    with tenant_scope("A"):
        async with state.session_factory() as db:
            got = await accepted_engagement(db, tenant_id="A", campaign_ids=[one, two, none, other])
            empty = await accepted_engagement(db, tenant_id="A", campaign_ids=[])
    assert got == {one: (1, 1, 1), two: (2, 1, 0), none: (0, 0, 0), other: (0, 0, 0)}
    assert empty == {}
