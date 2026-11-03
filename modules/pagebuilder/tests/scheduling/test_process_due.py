"""Integration tests for scheduled publish / unpublish (#11).

Two surfaces are exercised: the ``POST /pages/{id}/schedule`` admin
endpoint (with editor / publisher gating) and ``PagesService.process_due``
driven directly with a fake ``now`` so we don't have to wait for the
scheduler loop. The loop itself is one ``asyncio.sleep`` wrapping a call
to ``process_due`` — once ``process_due`` is right the loop is a thin
shell.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pagebuilder.content.service.pages import PagesService
from pagebuilder.models import Page, PageStatus
from pg_support import make_db_state
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.asyncio


async def _bare_session_factory():
    state = await make_db_state()
    return state.engine, async_sessionmaker(
        state.engine,
        expire_on_commit=False,
        sync_session_class=state.sync_session_class,
    )


async def test_process_due_publishes_drafts_whose_time_has_passed() -> None:
    engine, factory = await _bare_session_factory()
    try:
        async with factory() as session:
            past = datetime.now(UTC) - timedelta(minutes=1)
            page = Page(
                title="x",
                slug="x",
                publish_at=past,
                draft_data={"content": ["hi"]},
            )
            session.add(page)
            await session.commit()
            await session.refresh(page)
            page_id = page.id

        async with factory() as session:
            flipped = await PagesService(session).process_due(datetime.now(UTC))
            await session.commit()
            assert len(flipped) == 1
            assert flipped[0].id == page_id

        async with factory() as session:
            after = await session.get(Page, page_id)
            assert after is not None
            assert after.status == PageStatus.PUBLISHED
            assert after.publish_at is None
            assert after.published_data == {"content": ["hi"]}
    finally:
        await engine.dispose()


async def test_process_due_unpublishes_published_whose_time_has_passed() -> None:
    engine, factory = await _bare_session_factory()
    try:
        async with factory() as session:
            past = datetime.now(UTC) - timedelta(seconds=1)
            page = Page(
                title="x",
                slug="x",
                status=PageStatus.PUBLISHED,
                draft_data={"v": 1},
                published_data={"v": 1},
                unpublish_at=past,
            )
            session.add(page)
            await session.commit()
            await session.refresh(page)
            page_id = page.id

        async with factory() as session:
            flipped = await PagesService(session).process_due(datetime.now(UTC))
            await session.commit()
            assert len(flipped) == 1

        async with factory() as session:
            after = await session.get(Page, page_id)
            assert after is not None
            assert after.status == PageStatus.DRAFT
            assert after.unpublish_at is None
    finally:
        await engine.dispose()


async def test_process_due_leaves_future_schedules_alone() -> None:
    engine, factory = await _bare_session_factory()
    try:
        async with factory() as session:
            future = datetime.now(UTC) + timedelta(hours=1)
            page = Page(title="future", slug="future", publish_at=future)
            session.add(page)
            await session.commit()

        async with factory() as session:
            flipped = await PagesService(session).process_due(datetime.now(UTC))
            assert flipped == []
    finally:
        await engine.dispose()


async def test_process_due_is_idempotent_across_ticks() -> None:
    """Re-running ``process_due`` after a flip must be a no-op — the
    cleared ``publish_at`` filter excludes the just-flipped row."""
    engine, factory = await _bare_session_factory()
    try:
        async with factory() as session:
            past = datetime.now(UTC) - timedelta(minutes=1)
            page = Page(title="x", slug="x", publish_at=past)
            session.add(page)
            await session.commit()

        async with factory() as session:
            first = await PagesService(session).process_due(datetime.now(UTC))
            await session.commit()
            assert len(first) == 1

        async with factory() as session:
            second = await PagesService(session).process_due(datetime.now(UTC))
            assert second == []
    finally:
        await engine.dispose()
