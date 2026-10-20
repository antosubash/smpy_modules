"""What stops two schedulers publishing the same page twice (#108).

The in-process loop starts in *every* process that boots the module, so
``uvicorn -w 4`` or a Deployment with ``replicas > 1`` runs several copies of
it. ``process_due`` used to be a plain ``SELECT`` followed by a transition, and
two of those overlapping published one page twice — two PUBLISH revision rows,
and a flip-flop on the way back down. Each row is now claimed by a single
conditional ``UPDATE`` first; see :mod:`pagebuilder.service._claims`.

**What this file proves, and what it cannot.** The mutual exclusion itself
belongs to the database: two processes issue the same ``UPDATE``, one is
serialised behind the other's write, and the loser re-reads the row the winner
left behind. This suite shares one database across sessions, so it cannot stage
two genuinely concurrent transactions. The races below are staged at the
statement boundary instead — both replicas take their shortlist, one claims and
flips, then the other claims — which establishes the half that is ours: winning
a claim makes the row stop matching, a loser flips nothing, an abandoned claim
goes back with its transaction, and a refused transition hands its claim back.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from page_helpers import EARLIER, NOW, PUBLISH_CLAIM, make_page, publish_revisions
from pagebuilder.models import Page, PageStatus
from pagebuilder.service import PagesService
from pagebuilder.service._claims import claim, due_candidates, release
from pagebuilder.service._common import _normalize_to_utc
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


UNPUBLISH_CLAIM = {"column": Page.unpublish_at, "status": PageStatus.PUBLISHED}


async def _due_draft(db, slug: str) -> Page:
    return await make_page(db, slug, publish_at=EARLIER)


async def _stored_publish_at(db, page_id: int) -> datetime | None:
    """``publish_at`` as the *row* holds it, not as the session remembers it."""
    stored = await db.execute(select(Page.publish_at).where(Page.id == page_id))
    return _normalize_to_utc(stored.scalar_one())


class TestTheClaim:
    async def test_only_the_first_caller_wins_it(self, db) -> None:
        """The claim's ``WHERE`` and ``SET`` are one statement, so taking it
        makes the row stop matching and the second caller gets nothing."""
        page = await _due_draft(db, "contested")

        assert await claim(db, page.id, now=NOW, **PUBLISH_CLAIM) is True
        assert await claim(db, page.id, now=NOW, **PUBLISH_CLAIM) is False

    async def test_winning_it_clears_the_timestamp(self, db) -> None:
        """Which is *why* the second caller finds nothing. Read back with a
        query: the claim is a Core ``UPDATE`` with ``synchronize_session=False``,
        so the session's copy still holds the old instant."""
        page = await _due_draft(db, "taken")

        await claim(db, page.id, now=NOW, **PUBLISH_CLAIM)

        assert await _stored_publish_at(db, page.id) is None

    async def test_a_row_binned_in_the_gap_cannot_be_claimed(self, db) -> None:
        page = await _due_draft(db, "binned-in-the-gap")
        shortlist = await due_candidates(db, now=NOW, **PUBLISH_CLAIM)
        assert [row[0] for row in shortlist] == [page.id]

        await PagesService(db).delete(page.id)

        assert await claim(db, page.id, now=NOW, **PUBLISH_CLAIM) is False

    async def test_a_row_published_by_hand_in_the_gap_cannot_be_claimed(self, db) -> None:
        page = await _due_draft(db, "beaten-by-a-human")
        await due_candidates(db, now=NOW, **PUBLISH_CLAIM)

        await PagesService(db).publish(page.id)

        assert await claim(db, page.id, now=NOW, **PUBLISH_CLAIM) is False

    async def test_a_schedule_still_in_the_future_is_not_claimable(self, db) -> None:
        """The claim carries the due check, not just the identity — otherwise
        it would be a lock that publishes things early."""
        page = await make_page(db, "next-week", publish_at=NOW + timedelta(days=7))

        assert await claim(db, page.id, now=NOW, **PUBLISH_CLAIM) is False


class TestTwoReplicas:
    """The interleaving that used to double-publish, staged step by step."""

    async def test_the_loser_publishes_nothing(self, db) -> None:
        page = await _due_draft(db, "one-flip-only")

        first = await due_candidates(db, now=NOW, **PUBLISH_CLAIM)
        second = await due_candidates(db, now=NOW, **PUBLISH_CLAIM)
        assert [r[0] for r in first] == [r[0] for r in second] == [page.id]

        assert await claim(db, page.id, now=NOW, **PUBLISH_CLAIM) is True
        await PagesService(db).publish(page.id)

        # Without the claim the second replica went on to publish too.
        assert await claim(db, page.id, now=NOW, **PUBLISH_CLAIM) is False
        assert await publish_revisions(db, page.id) == 1

    async def test_the_loser_does_not_take_a_published_page_back_down(self, db) -> None:
        page = await make_page(
            db,
            "expiring",
            status=PageStatus.PUBLISHED,
            published_data={"content": []},
            unpublish_at=EARLIER,
        )

        assert await claim(db, page.id, now=NOW, **UNPUBLISH_CLAIM) is True
        await PagesService(db).unpublish(page.id)

        assert await claim(db, page.id, now=NOW, **UNPUBLISH_CLAIM) is False
        row = await db.get(Page, page.id)
        assert row.status is PageStatus.DRAFT

    async def test_each_replica_gets_a_different_page(self, db) -> None:
        """Claiming is per row, not a lock over the scheduler: both processes
        do useful work in the same tick."""
        first = await _due_draft(db, "first-due")
        second = await _due_draft(db, "second-due")

        assert await claim(db, first.id, now=NOW, **PUBLISH_CLAIM) is True
        assert await claim(db, second.id, now=NOW, **PUBLISH_CLAIM) is True
        assert await claim(db, first.id, now=NOW, **PUBLISH_CLAIM) is False

    async def test_a_second_tick_at_the_same_instant_writes_no_second_revision(
        self, db
    ) -> None:
        """End to end through ``process_due``: the second tick flips nothing."""
        page = await _due_draft(db, "end-to-end")

        assert [p.id for p in await PagesService(db).process_due(NOW)] == [page.id]
        assert await PagesService(db).process_due(NOW) == []
        assert await publish_revisions(db, page.id) == 1


class TestAnAbandonedClaim:
    async def test_a_rolled_back_tick_leaves_the_schedule_intact(self, db) -> None:
        """A process that dies holding a claim must not wedge the page — the
        reason the claim lives in the tick's transaction, not a lease row."""
        page_id = (await _due_draft(db, "orphaned")).id
        await db.commit()

        assert await claim(db, page_id, now=NOW, **PUBLISH_CLAIM) is True
        await db.rollback()

        row = await db.get(Page, page_id)
        assert _normalize_to_utc(row.publish_at) == EARLIER
        assert row.status is PageStatus.DRAFT
        candidates = await due_candidates(db, now=NOW, **PUBLISH_CLAIM)
        assert [r[0] for r in candidates] == [page_id]


class TestAReleasedClaim:
    """A transition can still refuse after the claim is taken. Keeping the
    claim would quietly retire the schedule."""

    async def test_release_puts_the_original_instant_back(self, db) -> None:
        page = await _due_draft(db, "handed-back")
        await claim(db, page.id, now=NOW, **PUBLISH_CLAIM)

        await release(db, page.id, column=Page.publish_at, when=EARLIER)

        assert await _stored_publish_at(db, page.id) == EARLIER

    async def test_a_refused_publish_is_retried_on_the_next_tick(
        self, db, monkeypatch
    ) -> None:
        page = await _due_draft(db, "flaky")
        service = PagesService(db)
        real = PagesService.publish
        attempts: list[int] = []

        async def flaky(self, target_id: int, note: str | None = None, **kw):
            attempts.append(target_id)
            if len(attempts) == 1:
                raise HTTPException(status_code=409, detail="not this time")
            return await real(self, target_id, note=note, **kw)

        monkeypatch.setattr(PagesService, "publish", flaky)

        assert await service.process_due(NOW) == []
        assert await _stored_publish_at(db, page.id) == EARLIER

        flipped = await service.process_due(NOW)

        assert [p.id for p in flipped] == [page.id]
        assert attempts == [page.id, page.id]
