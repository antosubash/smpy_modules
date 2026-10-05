"""Status transitions: publish, unpublish, schedule, submit, approve, reject.

Mixed into :class:`~pagebuilder.service.PagesService`. Split out to keep each
file focused; the methods are unchanged and still rely on ``self.db``,
``self.get_page``, and ``self._record_revision`` from the composing class.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import ColumnElement, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder.models import NOT_TRASHED, Page, PageStatus, RevisionEvent
from pagebuilder.service._common import _UNSET, _normalize_to_utc, _Unset
from pagebuilder.service._revisions import RevisionsMixin


def publish_due(now: datetime) -> ColumnElement[bool]:
    """Drafts whose ``publish_at`` has elapsed.

    Shared with the scheduler's tenant scan so what it looks for cannot drift
    from what :meth:`WorkflowMixin.process_due` flips. Trashed pages are
    excluded: a binned page must not flip itself live on a schedule it was
    carrying when it was binned.
    """
    return and_(
        NOT_TRASHED,
        Page.status == PageStatus.DRAFT,
        Page.publish_at.is_not(None),  # type: ignore[union-attr]
        Page.publish_at <= now,  # type: ignore[operator]
    )


def unpublish_due(now: datetime) -> ColumnElement[bool]:
    """Published pages whose ``unpublish_at`` has elapsed."""
    return and_(
        NOT_TRASHED,
        Page.status == PageStatus.PUBLISHED,
        Page.unpublish_at.is_not(None),  # type: ignore[union-attr]
        Page.unpublish_at <= now,  # type: ignore[operator]
    )


class WorkflowMixin(RevisionsMixin):
    """Status-transition behaviour for :class:`PagesService`."""

    db: AsyncSession

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
            select(Page).where(publish_due(now))
        )
        for page in pub_due.scalars().all():
            try:
                await self.publish(page.id or 0, note="Auto-published on schedule")
                flipped.append(page)
            except HTTPException:
                continue

        unpub_due = await self.db.execute(
            select(Page).where(unpublish_due(now))
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

