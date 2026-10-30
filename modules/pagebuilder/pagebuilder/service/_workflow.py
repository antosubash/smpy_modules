"""Status transitions: publish, unpublish, schedule, submit, approve, reject.

Mixed into :class:`~pagebuilder.service.PagesService`. What it needs from the
composing class is declared by :class:`~pagebuilder.service._host.PagesHost`;
``_record_revision`` comes from :class:`RevisionsMixin`, which it extends.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from functools import partial

from fastapi import HTTPException

from pagebuilder.models import Page, PageStatus, RevisionEvent
from pagebuilder.service._claims import claim, due_candidates, release, retire_missed_windows
from pagebuilder.service._common import _UNSET, _normalize_to_utc, _spend_schedule, _Unset
from pagebuilder.service._revisions import RevisionsMixin

logger = logging.getLogger(__name__)


class WorkflowMixin(RevisionsMixin):
    """Status-transition behaviour for :class:`PagesService`."""

    async def publish(
        self, page_id: int, note: str | None = None, *, now: datetime | None = None
    ) -> Page:
        """Snapshot the draft and serve it.

        ``now`` is the instant an elapsed ``unpublish_at`` is judged against:
        the wall clock for a person pressing Publish, the tick's own ``now``
        from :meth:`process_due`. The tick has already retired every window
        that closed by its ``now``, so judging against the tick leaves any
        other ``unpublish_at`` alone. Judged against the wall clock instead,
        a deadline falling between the two (a slow tick, one queued behind
        another replica's locks) would be wiped as a leftover and the page
        would stay live forever.
        """
        page = await self.get_page(page_id)
        page.published_data = page.draft_data
        page.status = PageStatus.PUBLISHED
        page.rejection_note = None
        # A manual publish supersedes any pending auto-publish for the
        # same page; clearing it stops the scheduler from re-firing on
        # the next tick.
        # A genuinely future ``unpublish_at`` is a real "take it down later"
        # instruction and survives. One that has already elapsed is a leftover
        # from a schedule this publish did not go through, and would take the
        # page straight back down on the next tick.
        _spend_schedule(page, now or datetime.now(UTC))
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
        existing value alone. The API takes only offset-aware times
        (``AwareInstant``); a naive value here is a stored one SQLite handed
        back without its offset, and is read as UTC. Rejects ``publish_at >= unpublish_at``
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
        if new_publish is not None and new_unpublish is not None and new_publish >= new_unpublish:
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

        Drafts with ``publish_at <= now`` go live; published pages with
        ``unpublish_at <= now`` go back to draft. Returns the flipped pages
        so callers can log / emit metrics.

        Safe to run in more than one process. Each row is *claimed* first — one
        conditional ``UPDATE`` that clears the timestamp it acts on, whose
        affected-row count says whether this caller won it — so two replicas
        ticking at once flip a due page exactly once. :mod:`._claims` has the
        reasoning; the two steps are spelt out here because the gap between
        them is the whole subject.

        Idempotent: each tick re-queries, so a missed wakeup catches up on the
        next — unless the whole window passed unseen, which is retired
        unpublished rather than flipped twice (``retire_missed_windows``). One
        bad row is skipped rather than poisoning the tick, its claim handed
        back so a later tick retries, and logged with the page's id: a
        schedule that quietly never fires leaves no other trace.
        """
        # Aware UTC, as ``publish`` compares it against stored timestamps.
        now = _normalize_to_utc(now) or datetime.now(UTC)
        if missed := await retire_missed_windows(self.db, now):
            logger.warning("pagebuilder.scheduler.window_missed count=%s", missed)
        flipped: list[Page] = []
        for label, column, status, act, note in (
            (
                "publish",
                Page.publish_at,
                PageStatus.DRAFT,
                # The tick's ``now``, not the wall clock: see ``publish``.
                partial(self.publish, now=now),
                "Auto-published on schedule",
            ),
            (
                "unpublish",
                Page.unpublish_at,
                PageStatus.PUBLISHED,
                self.unpublish,
                "Auto-unpublished on schedule",
            ),
        ):
            for page_id, due_at in await due_candidates(
                self.db, column=column, status=status, now=now
            ):
                if not await claim(self.db, page_id, column=column, status=status, now=now):
                    # Another replica got there first, or a person did. Not a
                    # failure: the page is being flipped, just not by us.
                    continue
                try:
                    flipped.append(await act(page_id, note=note))
                except HTTPException as exc:
                    await release(self.db, page_id, column=column, when=due_at)
                    logger.warning(
                        "pagebuilder.scheduler.%s_failed page_id=%s: %s",
                        label,
                        page_id,
                        exc.detail,
                        extra={"page_id": page_id, "status_code": exc.status_code},
                    )
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
        # Spent, exactly as in ``publish``: approving *is* publishing, so a
        # stale ``unpublish_at`` must not take the page straight back down.
        _spend_schedule(page, datetime.now(UTC))
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
        # A schedule set before submission must not survive the rejection: the
        # page is a draft again, which is exactly what ``process_due`` looks
        # for, so a stale ``publish_at`` would auto-publish the very page a
        # reviewer just turned back. An elapsed ``unpublish_at`` would sit
        # inert until a later publish, then take the page straight back down.
        _spend_schedule(page, datetime.now(UTC))
        self.db.add(page)
        self._record_revision(page, event=RevisionEvent.REJECT, note=note)
        await self.db.flush()
        await self.db.refresh(page)
        return page
