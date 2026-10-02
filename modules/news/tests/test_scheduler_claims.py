"""What stops two schedulers publishing the same article twice.

The in-process loop starts in *every* process that boots the module, so
``uvicorn -w 4`` or a Deployment with ``replicas > 1`` runs several copies of it.
``process_due`` used to be a plain ``SELECT`` followed by a transition, and two
of those overlapping published one article twice — two PUBLISH revision rows, and
a flip-flop on the way back down. Each row is now claimed by a single conditional
``UPDATE`` first; see :mod:`news.content._claims`.

**What this file proves, and what it cannot.** The mutual exclusion itself
belongs to the database: two processes issue the same ``UPDATE``, one is
serialised behind the other's write, and the loser re-reads the row the winner
left behind. This suite runs on one in-memory SQLite database shared by every
session through ``StaticPool``, so it cannot stage two genuinely concurrent
transactions — and a test that "passed" only because SQLite took a write lock
would have established nothing about *this* code anyway.

So the races below are staged at the one place the outcome is actually decided:
the statement boundary. Both replicas take their shortlist, then one claims and
flips, then the other claims. What that establishes is the half that is ours —
that winning a claim makes the row stop matching, that a caller who loses does
not flip anything, that a claim abandoned by a dying process goes back with its
transaction rather than wedging the article, and that a refused transition hands
its claim back so a later tick retries. What it does not establish is that the
engine serialises the two writes; that is Postgres' row lock and SQLite's writer
lock, and it is asserted in the module docstring, not here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from factories import make_article
from fastapi import HTTPException
from news.content import ArticlesService
from news.content._claims import claim, due_candidates, release
from news.models import ArticleStatus, NewsArticle, NewsArticleRevision, RevisionEvent
from news.naive_utc import as_utc
from sqlalchemy import func, select

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(hours=1)

PUBLISH_CLAIM = {"column": NewsArticle.publish_at, "status": ArticleStatus.DRAFT}
UNPUBLISH_CLAIM = {
    "column": NewsArticle.unpublish_at,
    "status": ArticleStatus.PUBLISHED,
}


async def _due_draft(db, slug: str) -> NewsArticle:
    article = await make_article(
        db, slug=slug, status=ArticleStatus.DRAFT, publish_body=False
    )
    await ArticlesService(db).schedule(article.id, publish_at=EARLIER)
    return article


async def _stored_publish_at(db, article_id: int) -> datetime | None:
    """``publish_at`` as the *row* holds it, not as the session remembers it."""
    stored = await db.execute(
        select(NewsArticle.publish_at).where(NewsArticle.id == article_id)
    )
    return stored.scalar_one()


async def _publish_revisions(db, article_id: int) -> int:
    total = await db.execute(
        select(func.count())
        .select_from(NewsArticleRevision)
        .where(
            NewsArticleRevision.article_id == article_id,
            NewsArticleRevision.event == RevisionEvent.PUBLISH,
        )
    )
    return total.scalar_one()


class TestTheClaim:
    async def test_only_the_first_caller_wins_it(self, db) -> None:
        """The whole guarantee, in one assertion.

        The claim's ``WHERE`` and its ``SET`` are one statement, so taking it
        makes the row stop matching. Whichever process the engine happens to run
        second is therefore looking at a row that no longer qualifies, and gets
        nothing.
        """
        article = await _due_draft(db, "contested")

        assert await claim(db, article.id, now=NOW, **PUBLISH_CLAIM) is True
        assert await claim(db, article.id, now=NOW, **PUBLISH_CLAIM) is False

    async def test_winning_it_clears_the_timestamp(self, db) -> None:
        """Which is *why* the second caller finds nothing — the claim is not a
        flag beside the schedule, it is the schedule being taken.

        Read back with a query rather than off the loaded object: the claim is a
        Core ``UPDATE`` with ``synchronize_session=False``, so the session's copy
        of the row still holds the old instant until something refreshes it. That
        is harmless in ``process_due`` — the transition overwrites the field
        anyway — but it means the *row* is what this has to assert on.
        """
        article = await _due_draft(db, "taken")

        await claim(db, article.id, now=NOW, **PUBLISH_CLAIM)

        assert await _stored_publish_at(db, article.id) is None

    async def test_a_row_binned_in_the_gap_cannot_be_claimed(self, db) -> None:
        # The predicate is deliberately re-checked inside the write. Anything
        # that changed between the shortlist and the claim — a bin, a hand
        # publish, another replica — leaves the row not matching.
        article = await _due_draft(db, "binned-in-the-gap")
        shortlist = await due_candidates(db, now=NOW, **PUBLISH_CLAIM)
        assert [row[0] for row in shortlist] == [article.id]

        await ArticlesService(db).trash(article.id)

        assert await claim(db, article.id, now=NOW, **PUBLISH_CLAIM) is False

    async def test_a_row_published_by_hand_in_the_gap_cannot_be_claimed(
        self, db
    ) -> None:
        article = await _due_draft(db, "beaten-by-a-human")
        await due_candidates(db, now=NOW, **PUBLISH_CLAIM)

        await ArticlesService(db).publish(article.id)

        assert await claim(db, article.id, now=NOW, **PUBLISH_CLAIM) is False

    async def test_a_schedule_still_in_the_future_is_not_claimable(self, db) -> None:
        """The claim carries the due check, not just the identity — otherwise it
        would be a lock that publishes things early."""
        article = await make_article(
            db, slug="next-week", status=ArticleStatus.DRAFT, publish_body=False
        )
        await ArticlesService(db).schedule(article.id, publish_at=NOW + timedelta(days=7))

        assert await claim(db, article.id, now=NOW, **PUBLISH_CLAIM) is False


class TestTwoReplicas:
    """The interleaving that used to double-publish, staged step by step."""

    async def test_the_loser_publishes_nothing(self, db) -> None:
        article = await _due_draft(db, "one-flip-only")

        # Both replicas take their shortlist before either has written.
        first = await due_candidates(db, now=NOW, **PUBLISH_CLAIM)
        second = await due_candidates(db, now=NOW, **PUBLISH_CLAIM)
        assert [row[0] for row in first] == [row[0] for row in second] == [article.id]

        # One of them claims and flips.
        assert await claim(db, article.id, now=NOW, **PUBLISH_CLAIM) is True
        await ArticlesService(db).publish(article.id)

        # The other, holding an identical shortlist, comes away with nothing —
        # which is the point: without the claim it went on to publish, leaving
        # a second PUBLISH revision row for one editorial decision.
        assert await claim(db, article.id, now=NOW, **PUBLISH_CLAIM) is False
        assert await _publish_revisions(db, article.id) == 1

    async def test_the_loser_does_not_take_a_published_article_back_down(
        self, db
    ) -> None:
        # The unpublish half is the worse failure of the two: two replicas
        # racing it flip-flop the article rather than merely duplicating a row.
        article = await make_article(db, slug="expiring")
        await ArticlesService(db).schedule(article.id, unpublish_at=EARLIER)

        assert await claim(db, article.id, now=NOW, **UNPUBLISH_CLAIM) is True
        await ArticlesService(db).unpublish(article.id)

        assert await claim(db, article.id, now=NOW, **UNPUBLISH_CLAIM) is False
        row = await db.get(NewsArticle, article.id)
        assert row.status is ArticleStatus.DRAFT

    async def test_each_replica_gets_a_different_article(self, db) -> None:
        """Claiming is per row, not a lock over the scheduler.

        A leader-election design would have idled one of these processes
        entirely; here both do useful work in the same tick.
        """
        first = await _due_draft(db, "first-due")
        second = await _due_draft(db, "second-due")

        assert await claim(db, first.id, now=NOW, **PUBLISH_CLAIM) is True
        assert await claim(db, second.id, now=NOW, **PUBLISH_CLAIM) is True
        assert await claim(db, first.id, now=NOW, **PUBLISH_CLAIM) is False


class TestAnAbandonedClaim:
    """A process that dies holding one must not wedge the article.

    This is the reason the claim lives in the tick's transaction rather than in
    a lease row with an expiry: there is no timeout to tune, and no window in
    which a dead holder keeps an article off the site.
    """

    async def test_a_rolled_back_tick_leaves_the_schedule_intact(self, db) -> None:
        # Committed first, so the rollback below discards the claim and nothing
        # else — otherwise the article itself goes with it and the test proves
        # only that an uncommitted row can be thrown away.
        article_id = (await _due_draft(db, "orphaned")).id
        await db.commit()

        assert await claim(db, article_id, now=NOW, **PUBLISH_CLAIM) is True
        # The process dies here. Its transaction goes with it.
        await db.rollback()

        row = await db.get(NewsArticle, article_id)
        assert as_utc(row.publish_at) == EARLIER
        assert row.status is ArticleStatus.DRAFT
        # And the next tick, on any replica, simply finds it due again.
        assert [r[0] for r in await due_candidates(db, now=NOW, **PUBLISH_CLAIM)] == [
            article_id
        ]


class TestAReleasedClaim:
    """A transition can still refuse after the claim is taken.

    Keeping the claim would quietly retire the schedule — the article stays a
    draft, its ``publish_at`` reads empty on the screen as though nothing had
    ever been arranged, and no later tick tries again.
    """

    async def test_release_puts_the_original_instant_back(self, db) -> None:
        article = await _due_draft(db, "handed-back")
        await claim(db, article.id, now=NOW, **PUBLISH_CLAIM)

        await release(db, article.id, column=NewsArticle.publish_at, when=EARLIER)

        assert as_utc(await _stored_publish_at(db, article.id)) == EARLIER

    async def test_a_refused_publish_is_retried_on_the_next_tick(
        self, db, monkeypatch
    ) -> None:
        """End to end through ``process_due``: fail once, succeed after.

        The unclaimed code retried by accident — it never wrote anything for a
        row it could not flip. Claiming makes the retry something that has to be
        arranged, so it gets a test.
        """
        article = await _due_draft(db, "flaky")
        service = ArticlesService(db)
        real = ArticlesService.publish
        attempts: list[int] = []

        async def flaky(self, target_id: int):
            attempts.append(target_id)
            if len(attempts) == 1:
                raise HTTPException(status_code=409, detail="not this time")
            return await real(self, target_id)

        monkeypatch.setattr(ArticlesService, "publish", flaky)

        assert await service.process_due(NOW) == []
        assert as_utc(await _stored_publish_at(db, article.id)) == EARLIER

        flipped = await service.process_due(NOW)

        assert [a.id for a in flipped] == [article.id]
        assert attempts == [article.id, article.id]
