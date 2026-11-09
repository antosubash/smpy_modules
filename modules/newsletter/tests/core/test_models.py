"""The newsletter tables: keys, uniqueness, tenancy, and the fail-closed guard."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from simple_module_core.diagnostics._tenancy import check_tenant_unique_keys, module_tables
from sm_newsletter import models
from sm_newsletter.core.tenancy import TenantUnbound, all_tenants, install_guard
from sm_newsletter.core.tenancy._guard import owned
from sm_newsletter.models import (
    Base,
    Campaign,
    CampaignRender,
    Click,
    Link,
    Segment,
    Send,
    Suppression,
    SuppressionLift,
)
from sm_newsletter.module import NewsletterModule
from sqlalchemy import delete, insert, select, text
from sqlalchemy.exc import IntegrityError

LOCK_TABLE = "newsletter_dispatch_lock"
TABLES = {
    "newsletter_campaign",
    "newsletter_segment",
    "newsletter_send",
    "newsletter_send_attempt",
    "newsletter_campaign_render",
    "newsletter_link",
    "newsletter_click",
    "newsletter_suppression",
    "newsletter_suppression_lift",
    LOCK_TABLE,
}


async def _campaign(db) -> Campaign:
    campaign = Campaign(name="Spring", list_type_key="news")
    db.add(campaign)
    await db.flush()
    return campaign


def _suppression(reason: str, list_type_key: str) -> Suppression:
    return Suppression(
        email_hash="h" * 64, reason=reason, list_type_key=list_type_key, source="admin"
    )


async def test_one_send_per_recipient_per_campaign(db):
    c = await _campaign(db)
    db.add(Send(campaign_id=c.id, record_uuid="u1", email="a@example.com"))
    db.add(Send(campaign_id=c.id, record_uuid="u1", email="a@example.com"))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_big_ids_autoincrement(db):
    c = await _campaign(db)
    first = Send(campaign_id=c.id, record_uuid="u1", email="a@example.com")
    db.add(first)
    await db.flush()
    second = Send(campaign_id=c.id, record_uuid="u2", email="b@example.com")
    db.add(second)
    await db.flush()
    assert second.id > first.id > 0


async def test_suppression_unique_per_reason_and_list(db):
    first = _suppression("unsubscribed", "news")
    db.add_all([first, _suppression("unsubscribed", "other"), _suppression("complaint", "")])
    await db.flush()
    await db.refresh(first)
    assert first.created_at.tzinfo is not None  # Task 6 compares it with a cutoff
    db.add(_suppression("unsubscribed", "news"))
    with pytest.raises(IntegrityError):
        await db.flush()


async def _send_and_links(db, n_links=2):
    c = await _campaign(db)
    send = Send(campaign_id=c.id, record_uuid="u1", email="a@example.com")
    other = Send(campaign_id=c.id, record_uuid="u2", email="b@example.com")
    links = [Link(campaign_id=c.id, position=i, url=f"https://e.com/{i}") for i in range(n_links)]
    db.add_all([send, other, *links])
    await db.flush()
    return send, other, links


async def test_click_is_unique_per_send_and_link(db):
    from datetime import UTC, datetime

    send, other, (a, b) = await _send_and_links(db)
    now = datetime.now(UTC)
    db.add_all(
        [
            Click(send_id=send.id, link_id=a.id, clicked_at=now),
            Click(send_id=send.id, link_id=b.id, clicked_at=now),
            Click(send_id=other.id, link_id=a.id, clicked_at=now),
        ]
    )
    await db.flush()
    db.add(Click(send_id=send.id, link_id=a.id, clicked_at=now))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_click_count_defaults_to_one(db):
    from datetime import UTC, datetime

    send, _other, (a, _b) = await _send_and_links(db)
    await db.execute(
        insert(Click.__table__).values(
            tenant_id="default", send_id=send.id, link_id=a.id, clicked_at=datetime.now(UTC)
        )
    )
    count = (
        await db.execute(
            select(Click.__table__.c.click_count).where(Click.__table__.c.send_id == send.id)
        )
    ).scalar_one()
    assert count == 1


async def test_tenant_stamped_from_scope(db):
    c = await _campaign(db)
    assert c.tenant_id == "default"


def test_the_tables_are_exactly_the_ten():
    assert set(Base.metadata.tables) == TABLES


def test_only_the_lock_is_global():
    for name, table in Base.metadata.tables.items():
        assert name.startswith("newsletter_")
        assert ("tenant_id" in table.c) is (name != LOCK_TABLE), name


def test_sm024_reports_nothing():
    """Every unique key on a tenant-scoped table leads with ``tenant_id``, so
    the framework's boot diagnostic has nothing to warn about."""
    tables = module_tables(NewsletterModule())
    assert check_tenant_unique_keys(tables, "Newsletter") == []


def test_every_table_but_the_lock_is_guarded():
    classes = [getattr(models, name) for name in models.__all__ if name != "Base"]
    mapped = {cls.__tablename__: cls for cls in classes}
    assert set(mapped) == TABLES
    assert {name for name, cls in mapped.items() if not owned(cls)} == {LOCK_TABLE}


@pytest.mark.unbound_tenant
async def test_unbound_select_and_flush_raise(db_state):
    install_guard(db_state.sync_session_class)
    async with db_state.session_factory() as session:
        with pytest.raises(TenantUnbound):
            await session.execute(select(Campaign))
        await session.execute(all_tenants(select(Campaign)))
        session.add(Campaign(name="x", list_type_key="news"))
        with pytest.raises(TenantUnbound):
            await session.flush()


async def test_render_row_is_tenant_owned_and_cascades(db):
    c = await _campaign(db)
    db.add(
        CampaignRender(
            campaign_id=c.id,
            subject="Hi {{first_name}}",
            html="<p>x</p>",
            text="x",
            sender="Acme <news@example.com>",
            public_base="https://example.com",
            locale="en",
        )
    )
    await db.flush()
    render = await db.get(CampaignRender, c.id)
    assert render.tenant_id == "default"
    assert render.reply_to is None
    assert render.rendered_at is not None
    if db.bind.dialect.name == "sqlite":
        await db.execute(text("PRAGMA foreign_keys=ON"))
    await db.execute(delete(Campaign).where(Campaign.id == c.id))
    await db.flush()
    db.expunge_all()
    assert await db.get(CampaignRender, c.id) is None


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
