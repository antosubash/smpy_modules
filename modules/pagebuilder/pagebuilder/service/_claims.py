"""Claiming a due page, so two schedulers cannot both flip it.

:meth:`~pagebuilder.service.PagesService.process_due` used to be a plain
``SELECT`` followed by ``publish``/``unpublish``. The in-process loop starts in
*every* process that boots the module — ``uvicorn -w 4``, gunicorn workers, a
Deployment with ``replicas > 1`` — and two of them ticking together found the
same due row and both flipped it: two PUBLISH revisions for one page, and a
flip-flop on the way back down.

The fix is the one :mod:`news.content._claims` made, ported rather than shared
because neither module depends on the other: a **conditional update whose own
effect removes the row from the due set**::

    UPDATE pagebuilder_pages SET publish_at = NULL
     WHERE id = :id AND deleted_at IS NULL AND status = 'draft'
       AND publish_at IS NOT NULL AND publish_at <= :now

The check and the claim are one statement, so the *database* decides who wins:
whichever process runs second meets a row that no longer matches and updates
nothing. ``rowcount`` is the whole answer. Portable, unlike ``FOR UPDATE SKIP
LOCKED`` (Postgres-only, and this repo's local default is SQLite); and per row,
unlike a lease table, which elects one scheduler, needs a migration and a clock
agreement, and leaves a window after a leaseholder dies in which nothing
publishes. Here a dead process's transaction rolls back, its claim vanishes
with it, and the next tick on any replica finds the page due again.

Postgres blocks the second update on the first's row lock and re-evaluates the
predicate under READ COMMITTED; SQLite serialises writers outright. Where the
loser cannot wait it raises instead of matching zero rows, the scheduler logs
the tenant's tick and tries again on the next one. Either way the page flips
once. News' module docstring has the longer argument.

Every statement here is ORM-enabled against a :class:`MultiTenantMixin` table,
so it is filtered to the tenant the scheduler bound (#38) like any other read.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.models import NOT_TRASHED, Page, PageStatus


def due(column: Any, status: PageStatus, now: datetime) -> ColumnElement[bool]:
    """``column`` is set and has passed, on a live page in ``status``."""
    return and_(NOT_TRASHED, Page.status == status, column.is_not(None), column <= now)


def publish_due(now: datetime) -> ColumnElement[bool]:
    """A draft whose ``publish_at`` has passed.

    Trashed pages are excluded: a binned page must not flip itself live on a
    schedule it was carrying when it was binned.
    """
    return due(Page.publish_at, PageStatus.DRAFT, now)


def unpublish_due(now: datetime) -> ColumnElement[bool]:
    """A published page whose ``unpublish_at`` has passed."""
    return due(Page.unpublish_at, PageStatus.PUBLISHED, now)


def missed_window(now: datetime) -> ColumnElement[bool]:
    """A draft whose publish *and* unpublish times have both passed."""
    return and_(
        publish_due(now),
        Page.unpublish_at.is_not(None),  # type: ignore[union-attr]
        Page.unpublish_at <= now,  # type: ignore[operator]
    )


def any_due(now: datetime) -> ColumnElement[bool]:
    """Everything ``process_due`` acts on: the scheduler's tenant scan uses it,
    so what it looks for cannot drift from what gets flipped. ``missed_window``
    is subsumed by ``publish_due``; it is listed so the three cases read off."""
    return or_(publish_due(now), unpublish_due(now), missed_window(now))


async def retire_missed_windows(db: AsyncSession, now: datetime) -> int:
    """Cancel every draft whose publish *and* unpublish times have both passed.

    The window opened and closed while no scheduler ran. Flipping it would
    publish the page and take it down again in one tick — two revisions and an
    overwritten ``published_data`` for a page nobody saw — and ``publish`` clears
    an elapsed ``unpublish_at`` as a leftover, so in fact it would publish and
    *stay* up, against the author's last word that it is off the site by now.
    Both times are cleared and the page stays a draft.

    Safe on every replica at once without a claim: the statement is idempotent,
    and the second to run finds nothing left to match. Returns the row count.
    """
    result = await db.execute(
        update(Page)
        .where(missed_window(now))
        .values(publish_at=None, unpublish_at=None)
        .execution_options(synchronize_session=False)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def due_candidates(
    db: AsyncSession, *, column: Any, status: PageStatus, now: datetime
) -> list[tuple[int, datetime | None]]:
    """Ids that look due right now, each with the timestamp that made it due.

    Only a shortlist — any row may already be taken, and :func:`claim` settles
    it. The timestamp comes back because :func:`release` has to put the original
    value back, and ``UPDATE ... RETURNING`` on Postgres returns the *new* row,
    the very value the claim erased.
    """
    rows = await db.execute(
        select(Page.id, column)
        .where(due(column, status, now))
        # Ordered by id so every replica takes its row locks in the same order;
        # two scanning in opposite orders can deadlock on a shared pair, and
        # Postgres then aborts the loser's whole tick rather than one claim.
        .order_by(Page.id)  # type: ignore[arg-type]
    )
    return [(page_id, due_at) for page_id, due_at in rows.all() if page_id]


async def claim(
    db: AsyncSession, page_id: int, *, column: Any, status: PageStatus, now: datetime
) -> bool:
    """Take one due page for this process. ``True`` if this caller won it.

    Re-checks the same predicate :func:`due_candidates` used, *inside the
    write*: anything that changed in between — another replica, a person
    publishing by hand, a bin — leaves the row not matching, and this returns
    ``False``. The claim lives in the caller's transaction, so a process that
    dies mid-tick rolls it back and the page is simply due again. Nothing to
    expire.

    ``synchronize_session=False`` because the caller settles the ORM's copy
    either way: a transition overwrites the timestamp, and :func:`release`
    puts back exactly the value already in memory.
    """
    result = await db.execute(
        update(Page)
        .where(Page.id == page_id, due(column, status, now))  # type: ignore[arg-type]
        .values({column: None})
        .execution_options(synchronize_session=False)
    )
    return getattr(result, "rowcount", 0) == 1


async def release(db: AsyncSession, page_id: int, *, column: Any, when: datetime | None) -> None:
    """Hand a claimed page back unflipped, exactly as it was.

    A transition can still refuse after the claim — the row was purged between
    the two statements and ``get_page`` 404s. The unclaimed code retried such a
    row by accident, because it wrote nothing for it. The claim has already
    cleared the timestamp, so without this the schedule would be silently
    retired: the page stays a draft, its ``publish_at`` reads empty, and no
    later tick tries again.
    """
    await db.execute(
        update(Page)
        .where(Page.id == page_id)  # type: ignore[arg-type]
        .values({column: when})
        .execution_options(synchronize_session=False)
    )
