"""The claim's edges: what changes in the gap, which windows retire, which
tenant a claim can reach, and two genuinely concurrent ticks.

Split from ``test_scheduler_claims.py`` to keep both under the line cap.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from page_helpers import EARLIER, NOW, PUBLISH_CLAIM, make_page, publish_revisions
from pagebuilder.models import Page, PageStatus
from pagebuilder.service import PagesService, _workflow
from pagebuilder.service._claims import claim, due_candidates
from pg_support import make_db_state
from simple_module_db import tenant_context
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


class TestChangedInTheGap:
    async def test_a_row_submitted_for_review_cannot_be_claimed(self, db) -> None:
        """Only a DRAFT auto-publishes; a submission belongs to the reviewer."""
        page = await make_page(db, "submitted", publish_at=EARLIER)
        await due_candidates(db, now=NOW, **PUBLISH_CLAIM)

        await PagesService(db).submit_for_review(page.id)

        assert await claim(db, page.id, now=NOW, **PUBLISH_CLAIM) is False

    async def test_a_row_rescheduled_into_the_future_cannot_be_claimed(self, db) -> None:
        page = await make_page(db, "postponed", publish_at=EARLIER)
        await due_candidates(db, now=NOW, **PUBLISH_CLAIM)

        await PagesService(db).schedule(page.id, publish_at=NOW + timedelta(days=1))

        assert await claim(db, page.id, now=NOW, **PUBLISH_CLAIM) is False

    async def test_a_draft_edited_in_the_gap_publishes_the_edit(self, db) -> None:
        """``publish`` reads the row after the claim, so it serves what the
        draft holds at that moment rather than what the shortlist saw."""
        page = await make_page(db, "edited", publish_at=EARLIER)
        page.draft_data = {"content": ["edited"]}
        db.add(page)
        await db.flush()

        await PagesService(db).process_due(NOW)

        await db.refresh(page)
        assert page.published_data == {"content": ["edited"]}


class TestRetirement:
    async def test_a_window_closing_exactly_now_is_retired(self, db) -> None:
        page = await make_page(db, "exact", publish_at=EARLIER, unpublish_at=NOW)

        assert await PagesService(db).process_due(NOW) == []

        await db.refresh(page)
        assert page.status is PageStatus.DRAFT
        assert page.publish_at is None and page.unpublish_at is None

    async def test_trashed_and_submitted_pages_are_left_alone(self, db) -> None:
        """Retirement is a statement about drafts the scheduler would have
        published; a binned page and a submission were never going live."""
        service = PagesService(db)
        binned = await make_page(db, "binned", publish_at=EARLIER, unpublish_at=EARLIER)
        submitted = await make_page(db, "pending", publish_at=EARLIER, unpublish_at=EARLIER)
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
                page_id = (await make_page(db, "theirs", publish_at=EARLIER)).id
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


async def test_two_concurrent_ticks_publish_once(tmp_path) -> None:
    """The half the staged tests cannot prove: the engine serialising the two
    claims. Each tick is its own session and connection, committing at the end,
    and the loser blocks on the winner's lock — the row lock on Postgres,
    SQLite's write lock on a file database (#209) — then matches nothing."""
    state = await make_db_state(file=tmp_path / "ticks.db")
    factory = state.session_factory
    try:
        async with factory() as db:
            page_id = (await make_page(db, "stampede", publish_at=EARLIER)).id
            await db.commit()

        async def tick() -> int:
            async with factory() as db:
                flipped = await PagesService(db).process_due(NOW)
                await db.commit()
                return len(flipped)

        assert sorted(await asyncio.gather(tick(), tick(), tick())) == [0, 0, 1]
        async with factory() as db:
            assert await publish_revisions(db, page_id) == 1
    finally:
        await state.engine.dispose()


async def test_ticks_that_all_shortlisted_the_row_publish_it_once(tmp_path, monkeypatch) -> None:
    """The claim itself, with every tick past the shortlist before any claims.

    On SQLite the test above never reaches the claim: each tick's first
    statement, ``retire_missed_windows``, is an ``UPDATE``, so it takes the
    database's write lock and the next tick waits for the whole first tick to
    commit, then shortlists nothing. Here the retire step is skipped (it has
    nothing to retire) and the ticks wait at a barrier once each has read its
    shortlist, so three ticks hold the same due row and the conditional
    ``UPDATE`` alone decides who flips it — on either backend.
    """
    state = await make_db_state(file=tmp_path / "claims.db")
    factory = state.session_factory
    barrier = asyncio.Barrier(3)

    async def nothing_to_retire(*_args, **_kwargs) -> int:
        return 0

    async def shortlist_then_wait(db, *, column, **kwargs):
        rows = await due_candidates(db, column=column, **kwargs)
        if column is Page.publish_at:
            await asyncio.wait_for(barrier.wait(), timeout=10)
        return rows

    monkeypatch.setattr(_workflow, "retire_missed_windows", nothing_to_retire)
    monkeypatch.setattr(_workflow, "due_candidates", shortlist_then_wait)
    try:
        async with factory() as db:
            page_id = (await make_page(db, "shortlisted", publish_at=EARLIER)).id
            await db.commit()

        async def tick() -> int:
            async with factory() as db:
                flipped = await PagesService(db).process_due(NOW)
                await db.commit()
                return len(flipped)

        assert sorted(await asyncio.gather(tick(), tick(), tick())) == [0, 0, 1]
        async with factory() as db:
            assert await publish_revisions(db, page_id) == 1
    finally:
        await state.engine.dispose()
