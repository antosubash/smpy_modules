"""Trash: soft delete, restore, and permanent purge.

Mixed into :class:`~pagebuilder.service.PagesService`. Deleting a page moves it
here rather than removing the row, so a mistake is recoverable for the retention
window — which is what lets the confirmation dialogs promise an undo.

Two operations, deliberately kept apart:

* ``delete`` is reversible. Nothing is removed, no event is published, and every
  listing simply stops seeing the row because they all filter on
  ``NOT_TRASHED``.
* ``purge`` is not. It removes the row, its revisions, and announces
  ``PageDeleted`` so other modules can drop what they keyed to it.

Publishing ``PageDeleted`` on the *soft* delete would be wrong: the news module
drops its article row on that event, so a restore would bring back a page with
its category and date gone.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder.contracts.events import PageDeleted
from pagebuilder.models import Page, PageRevision, PageStatus

#: How long a trashed page is recoverable before the sweep removes it.
RETENTION_DAYS = 30


class TrashMixin:
    """Soft-delete behaviour for :class:`PagesService`."""

    db: AsyncSession

    async def delete(self, page_id: int) -> None:
        """Move the page to trash. Reversible for ``RETENTION_DAYS``.

        Children keep pointing at it. Nulling them here would mean a restore
        brought the page back without its children — and a child referencing a
        trashed parent is harmless, because ``get_page`` refuses to return one,
        so a breadcrumb lookup simply finds nothing.
        """
        page = await self.get_page(page_id)
        page.deleted_at = datetime.now(UTC)
        self.db.add(page)
        await self.db.flush()

    async def restore(self, page_id: int) -> Page:
        """Bring a page back out of the trash, as a draft.

        Never straight back to published: the page has been invisible, its
        slug may have been linked from nowhere for weeks, and silently
        returning it to the live site is not a decision restore should make on
        someone's behalf. Publishing it again is one click.
        """
        page = await self.get_page(page_id, include_trashed=True)
        page.deleted_at = None
        # `published_data` is left intact, so republishing is one click — what
        # changes is only that the decision to be live is taken again, by a
        # person, rather than inherited from before the page was binned.
        page.status = PageStatus.DRAFT
        self.db.add(page)
        await self.db.flush()
        await self.db.refresh(page)
        return page

    async def list_trash(self) -> list[Page]:
        """Trashed pages, most recently binned first."""
        result = await self.db.execute(
            select(Page)
            .where(Page.deleted_at.is_not(None))  # type: ignore[union-attr]
            .order_by(Page.deleted_at.desc())
        )
        return list(result.scalars().all())

    async def purge(self, page_id: int) -> None:
        """Remove the page for good. Not reversible.

        Children are orphaned explicitly rather than by ``ON DELETE SET NULL``:
        SQLite does not enforce foreign keys unless ``PRAGMA foreign_keys=ON``
        is set on every connection, and a ``parent_id`` left pointing at a
        removed page is not inert — SQLite reuses the id, so the child would
        silently re-parent itself under whatever page is created next.
        """
        page = await self.get_page(page_id, include_trashed=True)
        slug = page.slug
        await self.db.execute(
            sa_delete(PageRevision).where(PageRevision.page_id == page_id)
        )
        await self.db.execute(
            sa_update(Page).where(Page.parent_id == page_id).values(parent_id=None)
        )
        await self.db.delete(page)
        await self.db.flush()
        if self.event_bus is None:
            return
        # Commit *before* publishing. A subscriber runs on its own session, so
        # on SQLite it would hit "database is locked" against this request's
        # still-open write transaction — and the bus swallows a handler error
        # into a log line, so the row would quietly survive.
        await self.db.commit()
        # Announce it so modules keying their own rows to this page can drop
        # them. Without this a stale row does not merely dangle — SQLite reuses
        # the id, so it re-attaches to the next page created.
        await self.event_bus.publish(PageDeleted(page_id=page_id, slug=slug))

    async def purge_expired(self, *, now: datetime | None = None) -> int:
        """Remove everything past the retention window. Returns how many.

        Called from the scheduler tick, beside the scheduled publish flips —
        the trash screen promises it empties itself after the window, and a
        sweep that only ran at boot would leave that promise unkept on a process
        that stays up for months. Each page goes through ``purge``, so the
        cascade and the ``PageDeleted`` event are identical to a manual one.
        """
        cutoff = (now or datetime.now(UTC)) - timedelta(days=RETENTION_DAYS)
        result = await self.db.execute(
            select(Page.id).where(
                Page.deleted_at.is_not(None),  # type: ignore[union-attr]
                Page.deleted_at < cutoff,  # type: ignore[operator]
            )
        )
        expired = list(result.scalars().all())
        for page_id in expired:
            await self.purge(page_id)
        return len(expired)
