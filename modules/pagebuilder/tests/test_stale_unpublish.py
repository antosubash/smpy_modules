"""Schedules whose ``unpublish_at`` elapsed before anyone acted on them (#108).

Two shapes. A draft whose publish *and* unpublish times both passed while no
scheduler ran used to be published and unpublished in one tick — the second
query saw the first's flushed state — writing two revisions and overwriting
``published_data`` for a page nobody saw. It is now retired: both times
cleared, the page left a draft.

And a page published, approved or rejected by hand while carrying an
``unpublish_at`` that has already passed: that leftover would take the page
straight back down on the very next tick, so those transitions spend it. A
genuinely future ``unpublish_at`` is a real "take it down later" instruction
and survives.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pagebuilder import scheduler
from pagebuilder.models import Page, PageRevision, PageStatus
from pagebuilder.service import PagesService
from pagebuilder.service._common import _normalize_to_utc
from pg_support import make_db_state
from sqlalchemy import func, select

pytestmark = pytest.mark.asyncio


async def _draft(db, slug: str, **fields) -> Page:
    page = Page(title=slug, slug=slug, draft_data={"content": [slug]}, **fields)
    db.add(page)
    await db.flush()
    await db.refresh(page)
    return page


def _ago(hours: int) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours)


async def test_publishing_by_hand_clears_an_elapsed_unpublish_at(db) -> None:
    page = await _draft(db, "stale-unpublish", unpublish_at=_ago(1))

    await PagesService(db).publish(page.id)

    await db.refresh(page)
    assert page.unpublish_at is None


async def test_publishing_by_hand_keeps_a_future_unpublish_at(db) -> None:
    future = datetime.now(UTC) + timedelta(days=1)
    page = await _draft(db, "future-unpublish", unpublish_at=future)

    await PagesService(db).publish(page.id)

    await db.refresh(page)
    assert _normalize_to_utc(page.unpublish_at) == future


async def test_approving_clears_an_elapsed_unpublish_at(db) -> None:
    page = await _draft(db, "approve-stale", unpublish_at=_ago(1))
    service = PagesService(db)
    await service.submit_for_review(page.id)

    await service.approve(page.id)

    await db.refresh(page)
    assert page.unpublish_at is None


async def test_rejecting_clears_an_elapsed_unpublish_at_and_any_publish_at(db) -> None:
    """A rejected page is a draft again — exactly what ``process_due`` looks
    for — so a ``publish_at`` set before submission would auto-publish the very
    page a reviewer just turned back."""
    page = await _draft(db, "reject-stale", publish_at=_ago(2), unpublish_at=_ago(1))
    service = PagesService(db)
    await service.submit_for_review(page.id)

    await service.reject(page.id, note="not yet")

    await db.refresh(page)
    assert page.publish_at is None and page.unpublish_at is None


async def test_a_window_that_passed_unseen_is_retired_not_published(db) -> None:
    now = datetime.now(UTC)
    missed = await _draft(db, "missed", publish_at=_ago(3), unpublish_at=_ago(1))
    still_open = await _draft(
        db, "still-open", publish_at=_ago(3), unpublish_at=now + timedelta(hours=1)
    )

    flipped = await PagesService(db).process_due(now)

    assert [p.id for p in flipped] == [still_open.id]
    await db.refresh(missed)
    assert missed.status is PageStatus.DRAFT
    assert missed.publish_at is None and missed.unpublish_at is None
    assert missed.published_data is None
    revisions = await db.execute(
        select(func.count()).select_from(PageRevision).where(PageRevision.page_id == missed.id)
    )
    assert revisions.scalar_one() == 0


async def test_a_tick_that_flips_nothing_still_persists_a_retired_window() -> None:
    """The tick used to roll back unless something flipped or purged, which
    would discard ``retire_missed_windows``' write: the row found, warned about
    and rolled back again on every interval."""
    state = await make_db_state()
    factory = state.session_factory
    try:
        async with factory() as db:
            page_id = (
                await _draft(db, "missed-tick", publish_at=_ago(3), unpublish_at=_ago(1))
            ).id
            await db.commit()

        await scheduler._tick(factory)

        async with factory() as db:
            row = await db.get(Page, page_id)
            assert row.status is PageStatus.DRAFT
            assert row.publish_at is None and row.unpublish_at is None
    finally:
        await state.engine.dispose()


async def test_a_deadline_closing_during_a_slow_tick_survives_the_scheduled_publish(
    db,
) -> None:
    """The window was still open at the tick's ``now`` but has closed by the
    wall clock when ``publish`` runs — a slow tick, or one queued behind another
    replica's locks. Judged against the wall clock, the deadline read as a
    leftover and was wiped, so the page stayed live forever. Judged against the
    tick it survives, and the next tick takes the page down."""
    tick_now = datetime.now(UTC) - timedelta(minutes=10)
    deadline = tick_now + timedelta(minutes=5)
    page = await _draft(
        db, "slow-tick", publish_at=tick_now - timedelta(hours=1), unpublish_at=deadline
    )
    service = PagesService(db)

    assert [p.id for p in await service.process_due(tick_now)] == [page.id]
    await db.refresh(page)
    assert page.status is PageStatus.PUBLISHED
    assert _normalize_to_utc(page.unpublish_at) == deadline

    assert [p.id for p in await service.process_due(datetime.now(UTC))] == [page.id]
    await db.refresh(page)
    assert page.status is PageStatus.DRAFT
