"""Business logic for pagebuilder pages.

Service is constructed per-request from the injected ``AsyncSession``;
the DB session's commit-on-write behavior is provided by the framework's
``get_db`` dependency.

``PagesService`` is composed from two mixins so no single file carries the
whole surface: :mod:`._workflow` holds the status transitions and
:mod:`._revisions` the revision history. Page CRUD and queries stay here.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import delete as sa_delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder.contracts.schemas import PageCreate, PageUpdate
from pagebuilder.models import Page, PageRevision, PageStatus
from pagebuilder.service._common import _UNSET, _normalize_to_utc
from pagebuilder.service._revisions import RevisionsMixin
from pagebuilder.service._workflow import WorkflowMixin

# _UNSET is re-exported: endpoints import it to express "field absent".
__all__ = ["_UNSET", "PagesService"]


class PagesService(WorkflowMixin, RevisionsMixin):
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_pages(self) -> list[Page]:
        result = await self.db.execute(select(Page).order_by(Page.id.desc()))
        return list(result.scalars().all())

    async def list_pending(self) -> list[Page]:
        """Pages in ``submitted_for_review`` — the approver queue."""
        result = await self.db.execute(
            select(Page)
            .where(Page.status == PageStatus.SUBMITTED_FOR_REVIEW)
            .order_by(Page.id.desc())
        )
        return list(result.scalars().all())

    async def get_page(self, page_id: int) -> Page:
        page = await self.db.get(Page, page_id)
        if page is None:
            raise HTTPException(status_code=404, detail="Page not found")
        return page

    async def get_by_slug_published(self, slug: str) -> Page | None:
        result = await self.db.execute(
            select(Page).where(
                Page.slug == slug,
                Page.status == PageStatus.PUBLISHED,
            )
        )
        return result.scalars().first()

    async def list_indexable_published(self) -> list[Page]:
        """Published pages eligible for sitemap inclusion.

        Excludes ``index_in_search=False`` (used both by the sitemap
        generator and any external indexing job). Ordered by ``updated_at``
        descending so the freshest content surfaces first when a consumer
        only reads the head of the list.
        """
        result = await self.db.execute(
            select(Page)
            .where(
                Page.status == PageStatus.PUBLISHED,
                Page.index_in_search.is_(True),  # type: ignore[union-attr]
            )
            .order_by(Page.updated_at.desc())
        )
        return list(result.scalars().all())

    async def create(self, data: PageCreate) -> Page:
        page = Page(
            title=data.title,
            slug=data.slug,
            meta_description=data.meta_description,
            og_image=data.og_image,
            canonical_url=data.canonical_url,
            index_in_search=data.index_in_search,
            json_ld=data.json_ld,
            draft_data=data.draft_data,
            publish_at=_normalize_to_utc(data.publish_at),
            unpublish_at=_normalize_to_utc(data.unpublish_at),
            status=PageStatus.DRAFT,
        )
        self.db.add(page)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(status_code=409, detail="Slug already in use") from exc
        await self.db.refresh(page)
        return page

    async def update(self, page_id: int, data: PageUpdate) -> Page:
        page = await self.get_page(page_id)
        update = data.model_dump(exclude_unset=True)
        for field, value in update.items():
            setattr(page, field, value)
        self.db.add(page)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(status_code=409, detail="Slug already in use") from exc
        await self.db.refresh(page)
        return page

    async def delete(self, page_id: int) -> None:
        page = await self.get_page(page_id)
        await self.db.execute(
            sa_delete(PageRevision).where(PageRevision.page_id == page_id)
        )
        await self.db.delete(page)
        await self.db.flush()

