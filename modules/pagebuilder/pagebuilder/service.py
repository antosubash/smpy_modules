"""Business logic for pagebuilder pages.

Service is constructed per-request from the injected ``AsyncSession``;
the DB session's commit-on-write behavior is provided by the framework's
``get_db`` dependency.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete as sa_delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder.diff import revision_diff
from pagebuilder.models import Page, PageRevision, PageStatus, RevisionEvent
from pagebuilder.schemas import PageCreate, PageUpdate


class _Unset:
    """Sentinel separating ``field=None`` (clear) from "field not provided"."""


_UNSET = _Unset()


def _normalize_to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class PagesService:
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

    async def publish(self, page_id: int, note: str | None = None) -> Page:
        page = await self.get_page(page_id)
        page.published_data = page.draft_data
        page.status = PageStatus.PUBLISHED
        page.rejection_note = None
        # A manual publish supersedes any pending auto-publish for the
        # same page; clearing it stops the scheduler from re-firing on
        # the next tick.
        page.publish_at = None
        self.db.add(page)
        self._record_revision(page, event=RevisionEvent.PUBLISH, note=note)
        await self.db.flush()
        await self.db.refresh(page)
        return page

    async def unpublish(self, page_id: int, note: str | None = None) -> Page:
        page = await self.get_page(page_id)
        page.status = PageStatus.DRAFT
        # Same reasoning as ``publish``: a manual unpublish wipes any
        # pending auto-unpublish so the scheduler doesn't re-fire.
        page.unpublish_at = None
        self.db.add(page)
        self._record_revision(page, event=RevisionEvent.UNPUBLISH, note=note)
        await self.db.flush()
        await self.db.refresh(page)
        return page

    async def schedule(
        self,
        page_id: int,
        *,
        publish_at: datetime | _Unset | None = _UNSET,
        unpublish_at: datetime | _Unset | None = _UNSET,
    ) -> Page:
        """Set or clear a page's scheduled flip timestamps.

        Each field is independently optional: pass a ``datetime`` to set,
        pass ``None`` to clear, omit (sentinel ``_UNSET``) to leave the
        existing value alone. Aware datetimes are normalized to UTC;
        naive ones are assumed UTC. Rejects ``publish_at >= unpublish_at``
        with a 422 since that would auto-unpublish before the auto-publish
        could fire.
        """
        page = await self.get_page(page_id)
        # Normalize both the incoming values and any already-stored values:
        # SQLite drops tz info on round-trip, so a naive existing column
        # would otherwise break the cross-field comparison below.
        new_publish = (
            _normalize_to_utc(publish_at)
            if not isinstance(publish_at, _Unset)
            else _normalize_to_utc(page.publish_at)
        )
        new_unpublish = (
            _normalize_to_utc(unpublish_at)
            if not isinstance(unpublish_at, _Unset)
            else _normalize_to_utc(page.unpublish_at)
        )
        if (
            new_publish is not None
            and new_unpublish is not None
            and new_publish >= new_unpublish
        ):
            raise HTTPException(
                status_code=422,
                detail="publish_at must be strictly before unpublish_at",
            )
        page.publish_at = new_publish
        page.unpublish_at = new_unpublish
        self.db.add(page)
        await self.db.flush()
        await self.db.refresh(page)
        return page

    async def process_due(self, now: datetime) -> list[Page]:
        """Flip every page whose scheduled time has elapsed.

        Drafts with ``publish_at <= now`` go live (clearing ``publish_at``);
        published pages with ``unpublish_at <= now`` go back to draft
        (clearing ``unpublish_at``). Returns the flipped pages so callers
        can log / emit metrics.

        Idempotent: each tick re-queries the table, so a missed wakeup
        catches up on the next one. Failures on a single page are caught
        and skipped so one bad row doesn't poison the whole tick.
        """
        flipped: list[Page] = []

        pub_due = await self.db.execute(
            select(Page).where(
                Page.status == PageStatus.DRAFT,
                Page.publish_at.is_not(None),  # type: ignore[union-attr]
                Page.publish_at <= now,  # type: ignore[operator]
            )
        )
        for page in pub_due.scalars().all():
            try:
                await self.publish(page.id or 0, note="Auto-published on schedule")
                flipped.append(page)
            except HTTPException:
                continue

        unpub_due = await self.db.execute(
            select(Page).where(
                Page.status == PageStatus.PUBLISHED,
                Page.unpublish_at.is_not(None),  # type: ignore[union-attr]
                Page.unpublish_at <= now,  # type: ignore[operator]
            )
        )
        for page in unpub_due.scalars().all():
            try:
                await self.unpublish(page.id or 0, note="Auto-unpublished on schedule")
                flipped.append(page)
            except HTTPException:
                continue

        return flipped

    async def submit_for_review(self, page_id: int, note: str | None = None) -> Page:
        """Editor flow: hand a draft off to an approver.

        Allowed transitions: ``DRAFT → SUBMITTED_FOR_REVIEW``. Re-submitting
        an already-submitted page is a 409 — the approver still owns it.
        Re-submission *after* a rejection is fine because the page was sent
        back to ``DRAFT`` with a ``rejection_note`` that's now cleared.
        """
        page = await self.get_page(page_id)
        if page.status != PageStatus.DRAFT:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot submit a page in '{page.status.value}' status",
            )
        page.status = PageStatus.SUBMITTED_FOR_REVIEW
        page.rejection_note = None
        self.db.add(page)
        self._record_revision(page, event=RevisionEvent.SUBMIT, note=note)
        await self.db.flush()
        await self.db.refresh(page)
        return page

    async def approve(self, page_id: int, note: str | None = None) -> Page:
        """Approver flow: take a submission live.

        One audit row tagged ``APPROVE``; the row's ``data`` snapshot is
        what ``/p/{slug}`` will serve, so it doubles as a restorable
        revision the editor history offers alongside plain publishes.
        """
        page = await self.get_page(page_id)
        if page.status != PageStatus.SUBMITTED_FOR_REVIEW:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot approve a page in '{page.status.value}' status",
            )
        page.published_data = page.draft_data
        page.status = PageStatus.PUBLISHED
        page.rejection_note = None
        self.db.add(page)
        self._record_revision(page, event=RevisionEvent.APPROVE, note=note)
        await self.db.flush()
        await self.db.refresh(page)
        return page

    async def reject(self, page_id: int, note: str) -> Page:
        """Approver flow: send a submission back to draft with feedback.

        ``note`` is captured on the page row (so the editor banner sees
        the latest one without joining the revision table) *and* on the
        revision row (so older notes stay queryable from the history).
        """
        page = await self.get_page(page_id)
        if page.status != PageStatus.SUBMITTED_FOR_REVIEW:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot reject a page in '{page.status.value}' status",
            )
        page.status = PageStatus.DRAFT
        page.rejection_note = note
        self.db.add(page)
        self._record_revision(page, event=RevisionEvent.REJECT, note=note)
        await self.db.flush()
        await self.db.refresh(page)
        return page

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
