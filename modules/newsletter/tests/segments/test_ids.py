"""A segment id is never handed out twice (QA BUG-001).

A campaign names its segment as ``segment:<id>``. On SQLite a plain ``INTEGER
PRIMARY KEY`` reuses the highest id once its row is deleted, so a draft whose
segment was deleted would silently re-bind to the next segment created.
"""

from __future__ import annotations

import pytest
from simple_module_db import finalize_session
from sm_newsletter.campaigns.audience import audience_filters
from sm_newsletter.core.errors_audience import UnknownSegment
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Campaign
from sm_newsletter.segments import store
from sm_newsletter.segments.rules import Rule
from sqlalchemy import select, update

from tests.support.campaign_world import seed_campaign
from tests.support.records_seed import TAGS, seed_list

T = "default"
NOBODY: list[str] = []


async def _create(db, name: str, tag: str = "vip"):
    with tenant_scope(T):
        seg = await store.create_segment(
            db,
            tenant_id=T,
            roles=NOBODY,
            name=name,
            list_type_key="news",
            rules=[Rule(field="tags", op="any", value=[tag])],
        )
        await finalize_session(db)
        return seg.id


async def _delete(db, segment_id: int) -> None:
    with tenant_scope(T):
        await store.delete_segment(db, tenant_id=T, segment_id=segment_id, roles=NOBODY)
        await finalize_session(db)


async def _set_campaign(state, cid: int, **values) -> None:
    with tenant_scope(T):
        async with state.session_factory() as s, s.begin():
            await s.execute(
                update(Campaign).where(Campaign.id == cid, Campaign.tenant_id == T).values(**values)
            )


async def test_deleting_the_newest_segment_does_not_free_its_id(db_state, db):
    await seed_list(db_state, T, fields=[TAGS])
    first = await _create(db, "first")
    newest = await _create(db, "newest")
    await _delete(db, newest)
    again = await _create(db, "again")
    assert again > max(first, newest)


async def test_unscheduled_draft_does_not_rebind_to_a_new_segment(db_state, db):
    await seed_list(db_state, T, fields=[TAGS])
    linz = await _create(db, "Linz", tag="vip")
    cid = await seed_campaign(db_state, T, status="scheduled")
    await _set_campaign(db_state, cid, audience=f"segment:{linz}")
    await _delete(db, linz)  # allowed: scheduling snapshotted the audience
    await _set_campaign(db_state, cid, status="draft")  # unscheduled
    vienna = await _create(db, "Vienna", tag="events")
    assert vienna != linz
    with tenant_scope(T):
        audience = (
            await db.execute(select(Campaign.audience).where(Campaign.id == cid))
        ).scalar_one()
        with pytest.raises(UnknownSegment):
            await audience_filters(
                db, tenant_id=T, list_type_key="news", audience=audience, roles=NOBODY
            )
    # The new segment is not held by the old draft: it can still be deleted.
    await _delete(db, vienna)
