"""Event cards: snapshot and refresh through ``sm_events.contracts.cards``."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from simple_module_db import finalize_session
from sm_events.core import clock
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar, Visibility
from sm_newsletter.campaigns import drafts
from sm_newsletter.content import cards
from sm_newsletter.content.blocks import EventCardProps, dump_body, parse_body
from sm_newsletter.content.event_snapshot import event_snapshot_props
from sm_newsletter.content.integrations import EventHit
from sm_newsletter.core.errors import CardSourceGone, IntegrationUnavailable, NotFound
from sm_newsletter.web.schemas.campaigns import CampaignCreate, CampaignPatch
from sqlalchemy import update

from tests.support.events_seed import change_event, seed_event
from tests.support.news_seed import seed_article
from tests.support.records_seed import seed_list

T = "default"
NOBODY: list[str] = []
APP = SimpleNamespace(state=SimpleNamespace(sm_events=object(), news=object()))
NO_EVENTS = SimpleNamespace(state=SimpleNamespace(news=object()))
WEEKLY = {
    "rrule": "FREQ=WEEKLY;BYDAY=WE",
    "starts_at": datetime(2026, 5, 6, 8, tzinfo=UTC),
    "ends_at": datetime(2026, 5, 6, 9, tzinfo=UTC),
}


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _now(monkeypatch):
    monkeypatch.setattr(clock, "now", lambda: utc(2026, 7, 1, 7))


async def _campaign(db_state, db, *blocks) -> SimpleNamespace:
    """The stored draft as plain values (the ORM row expires at the next commit)."""
    await seed_list(db_state, T)
    c = await drafts.create_draft(
        db, tenant_id=T, data=CampaignCreate(name="S", list_type_key="news"), roles=NOBODY
    )
    await finalize_session(db)
    patch = CampaignPatch(expected_revision=1, body=list(blocks))
    c = await drafts.update_draft(db, tenant_id=T, campaign_id=c.id, patch=patch, roles=NOBODY)
    await finalize_session(db)
    return SimpleNamespace(id=c.id, revision=c.revision, body=c.body)


async def _with_card(db_state, db, event_id, app=APP):
    props = await cards.snapshot(app, db, tenant_id=T, kind="event", source_id=str(event_id))
    block = {"type": "EventCard", "props": props}
    return await _campaign(db_state, db, {"type": "Divider", "props": {"id": "div"}}, block), props


async def _refresh(db, c, block_id, app=APP) -> SimpleNamespace:
    """Refresh, and return the stored draft's id, revision and body as plain values."""
    out = await cards.refresh_block(
        app,
        db,
        tenant_id=T,
        campaign_id=c.id,
        block_id=block_id,
        expected_revision=c.revision,
        roles=NOBODY,
    )
    await finalize_session(db)
    return SimpleNamespace(id=out.id, revision=out.revision, body=out.body)


async def test_snapshot_event_from_contract(db_state, db):
    eid = await seed_event(
        db_state, T, summary="Come by", venue_name="Hall 1", address="Main St 2",
        attendance_mode="hybrid", image="https://cdn.example.com/a.png",
    )  # fmt: skip
    props = await cards.snapshot(APP, db, tenant_id=T, kind="event", source_id=str(eid))
    assert len(props["id"]) == 12
    assert props["source_id"] == str(eid)
    assert (props["title"], props["excerpt"]) == ("Open day", "Come by")
    assert (props["url"], props["ics_url"]) == ("/events/open-day", "/events/open-day.ics")
    assert props["place"] == "Hall 1, Main St 2" and props["attendance_mode"] == "hybrid"
    assert props["timezone"] == "Europe/Vienna" and props["cancelled"] is False
    assert props["image_url"] == ""  # an off-site image is never carded
    EventCardProps.model_validate(props)
    other = await cards.snapshot(APP, db, tenant_id=T, kind="event", source_id=str(eid))
    assert other["id"] != props["id"]


async def test_snapshot_strips_bidi_overrides(db_state, db):
    eid = await seed_event(db_state, T, title="Ev\u202eil", summary="a\u2066b")
    props = await cards.snapshot(APP, db, tenant_id=T, kind="event", source_id=str(eid))
    assert (props["title"], props["excerpt"]) == ("Evil", "ab")


def test_snapshot_props_fit_the_block():
    hit = EventHit(
        kind="event",
        source_id=str(uuid.uuid4()),
        title="t" * 400,
        excerpt="e" * 2000,
        image_url="javascript:alert(1)",
        url="/events/x",
        ics_url="/events/x.ics",
        locale="en",
        starts_at=utc(2026, 7, 1, 8),
        ends_at=utc(2026, 7, 1, 9),
        all_day=False,
        start_date=None,
        end_date=None,
        timezone="UTC",
        attendance_mode="online",
        place="p" * 900,
        cancelled=False,
    )
    props = event_snapshot_props(hit, block_id="abc", now=utc(2026, 11, 5))
    assert (len(props["title"]), len(props["excerpt"]), len(props["place"])) == (300, 1000, 500)
    assert props["image_url"] == ""
    with pytest.raises(CardSourceGone):
        event_snapshot_props(
            dataclasses.replace(hit, ics_url="javascript:alert(1)"),
            block_id="abc",
            now=utc(2026, 11, 5),
        )


@pytest.mark.parametrize("how", ["draft", "in_review", "internal", "private", "unknown", "garbage"])
async def test_snapshot_hidden_event_404(db_state, db, how):
    """A draft can never be put into a snapshot: the lookup is the public one."""
    kinds = {
        "draft": {"status": "draft"},
        "in_review": {"status": "in_review"},
        "internal": {"visibility": Visibility.INTERNAL},
        "private": {"visibility": Visibility.PRIVATE},
    }
    if how in kinds:
        source = str(await seed_event(db_state, T, **kinds[how]))
    else:
        source = str(uuid.uuid4()) if how == "unknown" else "not-a-uuid"
    with pytest.raises(NotFound):
        await cards.snapshot(APP, db, tenant_id=T, kind="event", source_id=source)


async def test_refresh_rolls_series_forward(db_state, db, monkeypatch):
    eid = await seed_event(db_state, T, slug="weekly", **WEEKLY)
    c, props = await _with_card(db_state, db, eid)
    assert props["starts_at"].startswith("2026-07-01T08:00") and "date=2026-07-01" in props["url"]
    monkeypatch.setattr(clock, "now", lambda: utc(2026, 7, 1, 12))  # that one is over
    refreshed = await _refresh(db, c, props["id"])
    card = refreshed.body[1]["props"]
    assert card["id"] == props["id"]
    assert card["starts_at"].startswith("2026-07-08T08:00") and "date=2026-07-08" in card["url"]
    assert refreshed.revision == c.revision + 1


async def test_refresh_one_off_keeps_date(db_state, db, monkeypatch):
    eid = await seed_event(db_state, T)
    c, props = await _with_card(db_state, db, eid)
    monkeypatch.setattr(clock, "now", lambda: utc(2026, 8, 1))  # long over
    refreshed = await _refresh(db, c, props["id"])
    assert refreshed.body[1]["props"]["starts_at"] == props["starts_at"]


async def test_refresh_picks_up_a_cancellation(db_state, db):
    eid = await seed_event(db_state, T)
    c, props = await _with_card(db_state, db, eid)
    await change_event(db_state, T, eid, cancelled=True)
    refreshed = await _refresh(db, c, props["id"])
    assert refreshed.body[1]["props"]["cancelled"] is True


@pytest.mark.parametrize("how", ["internal", "trashed", "draft", "ended"])
async def test_refresh_gone_keeps_snapshot(db_state, db, monkeypatch, how):
    eid = await seed_event(db_state, T, **(WEEKLY | {"recurrence_until": utc(2026, 7, 2)}))
    c, props = await _with_card(db_state, db, eid)
    if how == "internal":
        with tenant_scope(T):
            await db.execute(update(Calendar).values(visibility=Visibility.INTERNAL))
            await finalize_session(db)
    elif how == "trashed":
        await change_event(db_state, T, eid, is_deleted=True)
    elif how == "draft":
        await change_event(db_state, T, eid, status="draft")
    else:  # the series' last occurrence is over
        monkeypatch.setattr(clock, "now", lambda: utc(2026, 9, 1))
    with pytest.raises(CardSourceGone):
        await _refresh(db, c, props["id"])
    await db.rollback()
    after = await drafts.get_campaign(db, tenant_id=T, campaign_id=c.id, roles=NOBODY)
    assert (after.revision, after.body) == (c.revision, c.body)


async def test_refresh_unavailable_without_events(db_state, db):
    eid = await seed_event(db_state, T)
    aid = await seed_article(db_state, T)
    props = await cards.snapshot(APP, db, tenant_id=T, kind="event", source_id=str(eid))
    article = await cards.snapshot(APP, db, tenant_id=T, kind="article", source_id=aid)
    c = await _campaign(
        db_state,
        db,
        {"type": "EventCard", "props": props},
        {"type": "ArticleCard", "props": article},
    )
    with pytest.raises(IntegrationUnavailable):
        await _refresh(db, c, props["id"], app=NO_EVENTS)
    await db.rollback()
    done = await _refresh(db, c, article["id"], app=NO_EVENTS)
    assert done.body[0] == c.body[0]  # the event card is untouched


async def test_snapshot_survives_privacy_change(db_state, db):
    """A stored card parses, and the draft stays valid, after the event is trashed."""
    eid = await seed_event(db_state, T)
    c, props = await _with_card(db_state, db, eid)
    await change_event(db_state, T, eid, is_deleted=True)
    got = await drafts.get_campaign(db, tenant_id=T, campaign_id=c.id, roles=NOBODY)
    assert dump_body(parse_body(got.body))[1]["props"] == props
