"""The claim's edges: what changes in the gap, which windows retire, which
tenant a claim can reach, and — on Postgres — two genuinely concurrent ticks.

Split from ``test_scheduler_claims.py`` to keep both under the line cap.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pagebuilder.models import Page, PageRevision, PageStatus, RevisionEvent
from pagebuilder.service import PagesService
from pagebuilder.service._claims import claim, due_candidates
from pg_support import USING_POSTGRES, make_db_state
from simple_module_db import tenant_context
from sqlalchemy import func, select

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(hours=1)
PUBLISH_CLAIM = {"column": Page.publish_at, "status": PageStatus.DRAFT}


async def _page(db, slug: str, **fields) -> Page:
    page = Page(title=slug, slug=slug, draft_data={"content": [slug]}, **fields)
    db.add(page)
    await db.flush()
    await db.refresh(page)
    return page


class TestChangedInTheGap:
    async def test_a_row_submitted_for_review_cannot_be_claimed(self, db) -> None:
        """Only a DRAFT auto-publishes; a submission belongs to the reviewer."""
        page = await _page(db, "submitted", publish_at=EARLIER)
        await due_candidates(db, now=NOW, **PUBLISH_CLAIM)

        await PagesService(db).submit_for_review(page.id)

        assert await claim(db, page.id, now=NOW, **PUBLISH_CLAIM) is False

    async def test_a_row_rescheduled_into_the_future_cannot_be_claimed(self, db) -> None:
        page = await _page(db, "postponed", publish_at=EARLIER)
        await due_candidates(db, now=NOW, **PUBLISH_CLAIM)

        await PagesService(db).schedule(page.id, publish_at=NOW + timedelta(days=1))

        assert await claim(db, page.id, now=NOW, **PUBLISH_CLAIM) is False

    async def test_a_draft_edited_in_the_gap_publishes_the_edit(self, db) -> None:
        """``publish`` reads the row after the claim, so it serves what the
        draft holds at that moment rather than what the shortlist saw."""
        page = await _page(db, "edited", publish_at=EARLIER)
        page.draft_data = {"content": ["edited"]}
        db.add(page)
        await db.flush()

        await PagesService(db).process_due(NOW)

        await db.refresh(page)
        assert page.published_data == {"content": ["edited"]}


class TestRetirement:
    async def test_a_window_closing_exactly_now_is_retired(self, db) -> None:
        page = await _page(db, "exact", publish_at=EARLIER, unpublish_at=NOW)

        assert await PagesService(db).process_due(NOW) == []

        await db.refresh(page)
        assert page.status is PageStatus.DRAFT
        assert page.publish_at is None and page.unpublish_at is None

    async def test_trashed_and_submitted_pages_are_left_alone(self, db) -> None:
        """Retirement is a statement about drafts the scheduler would have
        published; a binned page and a submission were never going live."""
        service = PagesService(db)
        binned = await _page(db, "binned", publish_at=EARLIER, unpublish_at=EARLIER)
        submitted = await _page(db, "pending", publish_at=EARLIER, unpublish_at=EARLIER)
        await service.delete(binned.id)
        await service.submit_for_review(submitted.id)

        await service.process_due(NOW + timedelta(minutes=1))

        for page_id in (binned.id, submitted.id):
            stored = await db.execute(
                select(Page.publish_at, Page.unpublish_at).where(Page.id == page_id)
            )
            publish_at, unpublish_at = stored.one()
            assert publish_at is not None and unpublish_at is not None


@pytest.mark.unbound_tenant
async def test_a_claim_cannot_reach_another_tenants_page() -> None:
    """The claim is an ORM ``UPDATE`` on a tenant-filtered table (#38): a tick
    bound to one tenant must not clear another tenant's schedule."""
    state = await make_db_state()
    state.tenant_strict = True
    try:
        with tenant_context("acme"):
            async with state.session_factory() as db:
                page_id = (await _page(db, "theirs", publish_at=EARLIER)).id
                await db.commit()
        with tenant_context("globex"):
            async with state.session_factory() as db:
                assert await claim(db, page_id, now=NOW, **PUBLISH_CLAIM) is False
                assert await due_candidates(db, now=NOW, **PUBLISH_CLAIM) == []
                await db.commit()
        with tenant_context("acme"):
            async with state.session_factory() as db:
                assert (await db.get(Page, page_id)).publish_at is not None
    finally:
        await state.engine.dispose()


@pytest.mark.skipif(
    not USING_POSTGRES,
    reason="SQLite's StaticPool shares one connection, so two ticks are not two "
    "transactions; set SM_TEST_DATABASE_URL=postgresql+asyncpg://…",
)
async def test_two_concurrent_ticks_publish_once() -> None:
    """The half the staged tests cannot prove: the engine serialising the two
    claims. Each tick is its own session and connection, committing at the end,
    and the loser blocks on the winner's row lock then matches nothing."""
    state = await make_db_state()
    factory = state.session_factory
    try:
        async with factory() as db:
            page_id = (await _page(db, "stampede", publish_at=EARLIER)).id
            await db.commit()

        async def tick() -> int:
            async with factory() as db:
                flipped = await PagesService(db).process_due(NOW)
                await db.commit()
                return len(flipped)

        assert sorted(await asyncio.gather(tick(), tick(), tick())) == [0, 0, 1]
        async with factory() as db:
            total = await db.execute(
                select(func.count())
                .select_from(PageRevision)
                .where(
                    PageRevision.page_id == page_id,
                    PageRevision.event == RevisionEvent.PUBLISH,
                )
            )
            assert total.scalar_one() == 1
    finally:
        await state.engine.dispose()
