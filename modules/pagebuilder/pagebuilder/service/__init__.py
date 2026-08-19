"""Business logic for pagebuilder pages.

Service is constructed per-request from the injected ``AsyncSession``;
the DB session's commit-on-write behavior is provided by the framework's
``get_db`` dependency.

``PagesService`` is composed from two mixins so no single file carries the
whole surface: :mod:`._workflow` holds the status transitions and
:mod:`._revisions` the revision history. Page CRUD and queries stay here.
"""

from __future__ import annotations

from datetime import datetime
from typing import NamedTuple

from copy import deepcopy

from fastapi import HTTPException
from simple_module_core.events import EventBus
from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder import redirects
from pagebuilder.contracts.events import PageDeleted
from pagebuilder.contracts.schemas import PageCreate, PageUpdate
from pagebuilder.models import NOT_TRASHED, Page, PageRevision, PageStatus
from pagebuilder.service._common import _UNSET, _normalize_to_utc
from pagebuilder.service._revisions import RevisionsMixin
from pagebuilder.service._trash import TrashMixin
from pagebuilder.service._workflow import WorkflowMixin

# _UNSET is re-exported: endpoints import it to express "field absent".
__all__ = ["_UNSET", "PagesService", "SitemapEntry"]


class SitemapEntry(NamedTuple):
    """The two fields a sitemap URL needs — deliberately not a ``Page``."""

    slug: str
    updated_at: datetime | None


class PagesService(WorkflowMixin, RevisionsMixin, TrashMixin):
    def __init__(self, db: AsyncSession, event_bus: EventBus | None = None) -> None:
        self.db = db
        # Optional so every existing caller — and every test — keeps working;
        # only the delete path uses it.
        self.event_bus = event_bus

    async def list_pages(
        self,
        *,
        search: str | None = None,
        status: PageStatus | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[Page], int]:
        """Pages newest-first, plus how many match before paging.

        ``limit=None`` means "every match", which is what
        ``GET /api/pagebuilder/pages`` still defaults to: a seed builds its
        slug-to-id map from that response, and silently truncating it would
        make the seed recreate pages it already has. The admin list asks for a
        page at a time instead.
        """
        filters = [NOT_TRASHED]
        if search and search.strip():
            # Escape the wildcards so a title containing "%" or "_" is searched
            # for literally rather than matching everything.
            term = search.strip().translate(str.maketrans({"%": r"\%", "_": r"\_", "\\": "\\\\"}))
            pattern = f"%{term}%"
            filters.append(
                Page.title.ilike(pattern, escape="\\") | Page.slug.ilike(pattern, escape="\\")
            )
        if status is not None:
            filters.append(Page.status == status)

        total = await self.db.scalar(
            select(func.count()).select_from(Page).where(*filters)
        )

        query = select(Page).where(*filters).order_by(Page.id.desc()).offset(offset)
        if limit is not None:
            query = query.limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all()), int(total or 0)

    async def list_templates(self) -> list[Page]:
        """Pages flagged as templates — the New page dialog's starting points.

        Ordinary pages with a flag, so the set grows without a developer.
        """
        result = await self.db.execute(
            select(Page).where(NOT_TRASHED, Page.is_template.is_(True)).order_by(Page.title)
        )
        return list(result.scalars().all())

    async def list_pending(self) -> list[Page]:
        """Pages in ``submitted_for_review`` — the approver queue."""
        result = await self.db.execute(
            select(Page)
            .where(NOT_TRASHED, Page.status == PageStatus.SUBMITTED_FOR_REVIEW)
            .order_by(Page.id.desc())
        )
        return list(result.scalars().all())

    async def get_page(self, page_id: int, *, include_trashed: bool = False) -> Page:
        """One page by id.

        A trashed page is a 404 here, not a row with a flag on it: every caller
        of this method is an ordinary read or write, and letting one through
        would mean editing or publishing something the author believes they
        deleted. Restore and purge pass ``include_trashed`` because they are the
        two operations that are *about* trashed pages.
        """
        page = await self.db.get(Page, page_id)
        if page is None or (page.deleted_at is not None and not include_trashed):
            raise HTTPException(status_code=404, detail="Page not found")
        return page

    async def get_by_slug_published(self, slug: str) -> Page | None:
        result = await self.db.execute(
            select(Page).where(
                NOT_TRASHED,
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
        only reads the head of the list. Loads full entities — the sitemap
        itself uses :meth:`list_sitemap_entries`, which skips the block
        JSON.
        """
        result = await self.db.execute(
            select(Page)
            .where(
                NOT_TRASHED,
                Page.status == PageStatus.PUBLISHED,
                Page.index_in_search.is_(True),  # type: ignore[union-attr]
            )
            .order_by(Page.updated_at.desc())
        )
        return list(result.scalars().all())

    async def list_sitemap_entries(self) -> list[SitemapEntry]:
        """Slug + last-modified of published, indexable pages — nothing else.

        The sitemap needs two columns; loading full entities dragged both
        block-JSON columns through the ORM on every crawl, which at a few
        thousand pages meant tens of MB per request and multi-second
        responses under concurrent crawlers (issue #11).
        """
        result = await self.db.execute(
            select(Page.slug, Page.updated_at)
            .where(
                NOT_TRASHED,
                Page.status == PageStatus.PUBLISHED,
                Page.index_in_search.is_(True),  # type: ignore[union-attr]
            )
            .order_by(Page.updated_at.desc())
        )
        return [SitemapEntry(slug, updated_at) for slug, updated_at in result.all()]

    async def create(self, data: PageCreate) -> Page:
        draft_data = data.draft_data
        if data.copy_from_page_id is not None:
            # "Start from" in the New page dialog: a template and "copy a page"
            # are the same operation, because a template *is* a page carrying a
            # flag. The source's draft is copied — not its published data, since
            # what a starting point offers is the work in progress, and not by
            # reference, so editing the copy never touches the original.
            source = await self.get_page(data.copy_from_page_id)
            draft_data = deepcopy(source.draft_data or {})

        page = Page(
            title=data.title,
            slug=data.slug,
            meta_description=data.meta_description,
            og_image=data.og_image,
            canonical_url=data.canonical_url,
            index_in_search=data.index_in_search,
            json_ld=data.json_ld,
            draft_data=draft_data,
            publish_at=_normalize_to_utc(data.publish_at),
            unpublish_at=_normalize_to_utc(data.unpublish_at),
            parent_id=data.parent_id,
            is_template=data.is_template,
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
        # Captured before the loop: once the slug is overwritten there is
        # nothing left to redirect *from*.
        previous_slug = page.slug
        for field, value in update.items():
            setattr(page, field, value)
        self.db.add(page)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(status_code=409, detail="Slug already in use") from exc
        # Recorded after the flush, so a rename the database rejected leaves no
        # redirect pointing at an address the page never took.
        await redirects.record(
            self.db, page_id=page_id, old_slug=previous_slug, new_slug=page.slug
        )
        await self.db.refresh(page)
        return page

