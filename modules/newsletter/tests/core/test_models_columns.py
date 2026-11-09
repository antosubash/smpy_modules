"""Columns and rows the later PRs added: send retry, freeze, segment rules, lifts, pause codes."""

from __future__ import annotations

from datetime import UTC, datetime

from sm_newsletter.core.tenancy._guard import owned
from sm_newsletter.models import Base, Campaign, CampaignRender, Segment, Send, SuppressionLift
from sqlalchemy import insert


async def _campaign(db) -> Campaign:
    campaign = Campaign(name="Spring", list_type_key="news")
    db.add(campaign)
    await db.flush()
    return campaign


async def test_send_has_first_name_and_retry_at(db):
    c = await _campaign(db)
    s = Send(campaign_id=c.id, record_uuid="u1", email="a@example.com")
    db.add(s)
    await db.flush()
    assert s.first_name is None
    assert s.retry_at is None
    cols = Base.metadata.tables["newsletter_send"].c
    assert cols.first_name.nullable and cols.retry_at.nullable


def test_freeze_columns():
    tables = Base.metadata.tables
    for name in ("newsletter_send", "newsletter_campaign"):
        col = tables[name].c.freeze_gen
        assert not col.nullable
        assert str(col.server_default.arg) == "0"
    campaign = tables["newsletter_campaign"].c
    assert campaign.freeze_owner.nullable and campaign.freeze_until.nullable
    assert campaign.freeze_owner.type.length == 64


async def test_segment_has_rules_and_filters(db):
    seg = Segment(name="VIPs", list_type_key="news", filters=["tag:vip"])
    db.add(seg)
    await db.flush()
    assert seg.rules == []
    assert seg.filters == ["tag:vip"]
    seg.rules = [{"field": "tags", "op": "any", "value": ["vip"]}]
    await db.flush()
    cols = Base.metadata.tables["newsletter_segment"].c
    assert not cols.rules.nullable
    assert str(cols.rules.server_default.arg) == "'[]'"


async def test_render_has_audience_filters_default_empty(db):
    c = await _campaign(db)
    await db.execute(
        insert(CampaignRender.__table__).values(
            tenant_id="default",
            campaign_id=c.id,
            subject="s",
            html="h",
            text="t",
            sender="A <a@example.com>",
            public_base="https://example.com",
            locale="en",
            rendered_at=datetime.now(UTC),
        )
    )
    render = await db.get(CampaignRender, c.id)
    assert render.audience_filters == []


async def test_lift_row_is_tenant_owned(db):
    now = datetime.now(UTC)
    lift = SuppressionLift(
        email_hash="h" * 64,
        reason="hard_bounce",
        source="admin",
        suppressed_at=now,
        lifted_at=now,
        note="fixed mailbox",
    )
    db.add(lift)
    await db.flush()
    assert lift.tenant_id == "default"
    assert lift.id > 0
    assert lift.list_type_key == ""
    assert lift.lifted_by is None
    assert owned(SuppressionLift)


def test_pause_codes_include_audience_unavailable():
    from sm_newsletter.core import constants as k

    assert k.PAUSE_AUDIENCE_UNAVAILABLE == "audience_unavailable"
    assert k.PAUSE_AUDIENCE_UNAVAILABLE in k.PAUSE_CODES
    assert k.PERM_RECORDS_VIEW == "records.view"
    assert k.TAGS_FIELD == "tags"
    assert k.LIFTABLE == (k.REASON_HARD_BOUNCE, k.REASON_IMPORTED_CLEANED, k.REASON_UNSUBSCRIBED)
    assert k.SOURCE_ADMIN == "admin"
    assert k.SOURCE_ADMIN in k.SOURCES
