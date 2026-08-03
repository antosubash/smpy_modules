"""Revision recording, history, diffing, and restore.

Mixed into :class:`~pagebuilder.service.PagesService`. Split out to keep each
file focused; the methods are unchanged and still rely on ``self.db`` and
``self.get_page`` from the composing class.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder.diff import revision_diff
from pagebuilder.models import Page, PageRevision, RevisionEvent


class RevisionsMixin:
    """Revision behaviour for :class:`PagesService`."""

    db: AsyncSession

    async def get_page(self, page_id: int) -> Page:  # pragma: no cover - provided by PagesService
        raise NotImplementedError

    def _record_revision(
        self,
        page: Page,
        *,
        event: RevisionEvent,
        note: str | None = None,
    ) -> PageRevision:
        """Append an audit row mirroring *page*'s current draft state.

        Publish / approve callers overwrite ``published_data`` with
        ``draft_data`` before recording, so ``draft_data`` is the single
        snapshot source every event needs. Caller owns the flush so the
        page row + revision land in one transaction.
        """
        revision = PageRevision(
            page_id=page.id or 0,
            title=page.title,
            meta_description=page.meta_description,
            og_image=page.og_image,
            data=page.draft_data,
            event=event,
            note=note,
        )
        self.db.add(revision)
        return revision


    async def list_revisions(self, page_id: int) -> list[PageRevision]:
        result = await self.db.execute(
            select(PageRevision)
            .where(PageRevision.page_id == page_id)
            .order_by(PageRevision.id.desc())
        )
        return list(result.scalars().all())

    async def get_revision(self, page_id: int, revision_id: int) -> PageRevision:
        revision = await self.db.get(PageRevision, revision_id)
        if revision is None or revision.page_id != page_id:
            raise HTTPException(status_code=404, detail="Revision not found")
        return revision

    async def diff_revisions(self, page_id: int, before_id: int, after_id: int) -> dict:
        """Block-level diff between two revisions of the same page.

        Both revisions are validated to belong to ``page_id`` via
        :meth:`get_revision`, so a cross-page id pair surfaces as a 404
        rather than silently diffing across pages.
        """
        before = await self.get_revision(page_id, before_id)
        after = await self.get_revision(page_id, after_id)
        result = revision_diff(before, after)
        result["before_id"] = before.id
        result["after_id"] = after.id
        return result

    async def restore_revision(self, page_id: int, revision_id: int) -> Page:
        """Copy a revision's payload into the page's draft (does not publish)."""
        page = await self.get_page(page_id)
        revision = await self.get_revision(page_id, revision_id)
        page.title = revision.title
        page.meta_description = revision.meta_description
        page.og_image = revision.og_image
        page.draft_data = revision.data
        self.db.add(page)
        await self.db.flush()
        await self.db.refresh(page)
        return page
