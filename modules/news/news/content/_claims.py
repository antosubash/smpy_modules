"""Claiming a due article, so two schedulers cannot both flip it.

:meth:`~news.content.ArticlesService.process_due` used to be a plain ``SELECT``
followed by a transition, which is correct in exactly one process and wrong in
every other deployment. The in-process loop starts in *every* process that boots
the module, so ``uvicorn -w 4``, gunicorn with workers and a Deployment with
``replicas > 1`` each run several copies of it — and two of them ticking together
found the same due row and both published it: two PUBLISH revision rows for one
article, and a flip-flop on the way back down.

The fix is a **conditional update whose own effect removes the row from the due
set**. Claiming an article for publication is one statement::

    UPDATE news_article SET publish_at = NULL
     WHERE id = :id AND deleted_at IS NULL AND status = 'draft'
       AND publish_at IS NOT NULL AND publish_at <= :now

The check and the claim are the same statement, so the *database* decides who
wins rather than this code: whichever process the engine runs second meets a row
that no longer matches and updates nothing. ``rowcount`` is the whole answer.

Chosen over the two obvious alternatives:

* ``SELECT ... FOR UPDATE SKIP LOCKED`` is the textbook answer and is
  **Postgres-only**. This repo's documented local default is SQLite, where the
  clause does not exist — so it would pass every test in this suite while
  protecting nothing in the configuration the suite actually runs, which is
  worse than the honest warning it replaced.
* A lease table with a heartbeat is portable too, but it elects one scheduler
  for the whole app rather than settling one article. That buys a new table, a
  migration, a dependence on the replicas' clocks agreeing about when a lease
  expired, and a window after a leaseholder dies in which *nothing* publishes.
  Here a dead process's transaction simply rolls back, the claim vanishes with
  it, and the next tick on any replica finds the article due again — no timeout
  to tune and no clock to compare, because ``now`` only ever decides whether a
  row is *due*, never who owns it.

What the engine still owes us is mutual exclusion between the two updates, and
both give it: Postgres blocks the second on the first's row lock and (under the
default READ COMMITTED) re-evaluates the predicate against the committed row,
and SQLite serialises writers outright. Under a stricter isolation level, or on
SQLite where the loser cannot wait, the losing tick raises instead of matching
zero rows — the scheduler logs it and tries again a tick later. Either way the
article is flipped once.

Two things that follow from the lock being held for the whole tick's
transaction, neither a correctness problem but both worth knowing. A replica
that loses a claim waits for the *winner's entire tick*, not just its one
statement, so a tick with many due articles makes the others queue behind it.
And whichever replica notices first is the one that acts, on its own clock — a
skewed one moves publication by the skew, exactly as the poll interval already
does.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ColumnElement, and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import InstrumentedAttribute

from news.models import NOT_TRASHED, ArticleStatus, NewsArticle


def due(column: InstrumentedAttribute, status: ArticleStatus, now: datetime) -> ColumnElement[bool]:
    """``column`` is set and has passed, on a live article in ``status``."""
    return and_(NOT_TRASHED, NewsArticle.status == status, column.is_not(None), column <= now)


def publish_due(now: datetime) -> ColumnElement[bool]:
    """A draft whose ``publish_at`` has passed."""
    return due(NewsArticle.publish_at, ArticleStatus.DRAFT, now)


def unpublish_due(now: datetime) -> ColumnElement[bool]:
    """A published article whose ``unpublish_at`` has passed."""
    return due(NewsArticle.unpublish_at, ArticleStatus.PUBLISHED, now)


def missed_window(now: datetime) -> ColumnElement[bool]:
    """A draft whose publish *and* unpublish times have both passed."""
    return and_(
        publish_due(now),
        NewsArticle.unpublish_at.is_not(None),
        NewsArticle.unpublish_at <= now,
    )


def any_due(now: datetime) -> ColumnElement[bool]:
    """Everything ``process_due`` would act on: the one definition of "due"."""
    return or_(publish_due(now), unpublish_due(now), missed_window(now))


async def retire_missed_windows(db: AsyncSession, now: datetime) -> int:
    """Cancel every draft whose publish *and* unpublish times have both passed.

    The window opened and closed while no scheduler was running. Publishing now
    would serve the article with nothing left to take it down: ``publish``
    clears an elapsed ``unpublish_at`` as a leftover, which is right for a
    person pressing Publish and wrong here, where the author's last word was
    that the article is off the site by now. So both times are cleared and the
    article stays a draft.

    Safe on every replica at once without a claim: the statement is idempotent,
    and the second to run finds nothing left to match. Returns the row count.
    """
    result = await db.execute(
        update(NewsArticle)
        .where(missed_window(now))
        .values(publish_at=None, unpublish_at=None)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


async def due_candidates(
    db: AsyncSession,
    *,
    column: InstrumentedAttribute,
    status: ArticleStatus,
    now: datetime,
) -> list[tuple[int, datetime | None]]:
    """Ids that look due right now, each with the timestamp that made it due.

    Only a shortlist — every row here may already have been taken by another
    process, and :func:`claim` is what settles it. The timestamp comes back
    because :func:`release` has to be able to put the original value back, and
    ``UPDATE ... RETURNING`` cannot supply it: on Postgres that returns the
    *new* row, which is precisely the value the claim just erased.
    """
    rows = await db.execute(
        select(NewsArticle.id, column)
        .where(due(column, status, now))
        # Ordered by id so that when a tick claims more than one row, every
        # replica takes its row locks in the same order. Without this, two
        # replicas whose queries happen to scan in different orders can claim
        # a shared pair of due articles in opposite sequence and deadlock —
        # Postgres aborts the loser's whole transaction, rolling back every
        # claim it already made that tick, which is a worse outcome than the
        # "loses the claim, tries again next tick" this module is built around.
        .order_by(NewsArticle.id)
    )
    return [(article_id, due_at) for article_id, due_at in rows.all() if article_id]


async def claim(
    db: AsyncSession,
    article_id: int,
    *,
    column: InstrumentedAttribute,
    status: ArticleStatus,
    now: datetime,
) -> bool:
    """Take one due article for this process. ``True`` if this caller won it.

    The predicate is deliberately the same one :func:`due_candidates` used, and
    that duplication is the point: re-checking it *inside the write* is what
    makes the gap between the shortlist and the transition harmless. Anything
    that changed in between — another replica claiming it, a human publishing
    it, an author binning it — leaves the row no longer matching, and this
    returns ``False``.

    The claim lives in the caller's transaction, so it is not a consumption: a
    process that dies mid-tick rolls back everything it held and the article is
    simply due again on somebody's next tick. There is nothing to expire.

    ``synchronize_session=False`` because the ORM's copy of the row is settled
    by the caller either way — a transition overwrites both timestamps, and
    :func:`release` puts back exactly the value that is already in memory.
    """
    result = await db.execute(
        update(NewsArticle)
        .where(
            NewsArticle.id == article_id,
            due(column, status, now),
        )
        .values({column: None})
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


async def release(
    db: AsyncSession,
    article_id: int,
    *,
    column: InstrumentedAttribute,
    when: datetime | None,
) -> None:
    """Hand a claimed article back unflipped, exactly as it was.

    A transition can still refuse after the claim is taken — the row was purged
    or binned between the two statements, and ``get_article`` 404s.

    The unclaimed code retried a refused row **by accident**: it wrote nothing
    for an article it could not flip, so the schedule was still sitting there
    for the next tick to find. Nothing named that behaviour, nothing tested it,
    and it existed by omission — which is exactly how it would have vanished
    here without anyone noticing. Claiming turns it into something that has to
    be arranged, because the claim has already cleared the timestamp: leave it
    cleared and the schedule is quietly retired, the article stays a draft, its
    ``publish_at`` reads empty on the screen as though nothing had ever been
    arranged, and no later tick tries again. So the instant goes back exactly as
    it was, and ``test_a_refused_publish_is_retried_on_the_next_tick`` holds it
    there.
    """
    await db.execute(
        update(NewsArticle)
        .where(NewsArticle.id == article_id)
        .values({column: when})
        .execution_options(synchronize_session=False)
    )
