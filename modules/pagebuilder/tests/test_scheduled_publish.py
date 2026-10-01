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
from httpx import AsyncClient
from pagebuilder.models import Page, PageStatus
from pagebuilder.service import PagesService
from pg_support import make_db_state
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.asyncio


async def _create_draft(client: AsyncClient, *, slug: str = "post") -> dict:
    response = await client.post(
        "/api/pagebuilder/pages",
        json={
            "title": "Draft",
            "slug": slug,
            "draft_data": {"content": ["hello"]},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_schedule_endpoint_sets_publish_at(authed_client: AsyncClient) -> None:
    page = await _create_draft(authed_client)
    when = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    response = await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/schedule",
        json={"publish_at": when},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["publish_at"] is not None
    assert body["unpublish_at"] is None


async def test_schedule_endpoint_sets_unpublish_at(authed_client: AsyncClient) -> None:
    page = await _create_draft(authed_client)
    await authed_client.post(f"/api/pagebuilder/pages/{page['id']}/publish")
    when = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    response = await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/schedule",
        json={"unpublish_at": when},
    )
    assert response.status_code == 200, response.text
    assert response.json()["unpublish_at"] is not None


async def test_schedule_clears_with_null(authed_client: AsyncClient) -> None:
    page = await _create_draft(authed_client)
    when = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/schedule",
        json={"publish_at": when},
    )
    response = await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/schedule",
        json={"publish_at": None},
    )
    assert response.status_code == 200
    assert response.json()["publish_at"] is None


async def test_schedule_only_touches_provided_fields(
    authed_client: AsyncClient,
) -> None:
    """Omitting a key must leave that side of the schedule alone — the
    editor sends one field at a time as the user edits each picker."""
    page = await _create_draft(authed_client)
    publish_when = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    unpublish_when = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    # First call sets both.
    await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/schedule",
        json={"publish_at": publish_when, "unpublish_at": unpublish_when},
    )
    # Second call only touches ``publish_at``; ``unpublish_at`` survives.
    new_publish = (datetime.now(UTC) + timedelta(hours=3)).isoformat()
    response = await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/schedule",
        json={"publish_at": new_publish},
    )
    body = response.json()
    assert body["publish_at"] is not None
    assert body["unpublish_at"] is not None


async def test_schedule_rejects_reversed_order(authed_client: AsyncClient) -> None:
    page = await _create_draft(authed_client)
    later = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    earlier = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    response = await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/schedule",
        json={"publish_at": later, "unpublish_at": earlier},
    )
    assert response.status_code == 422


async def test_schedule_requires_publish_permission(
    editor_client: AsyncClient,
) -> None:
    """The schedule endpoint moves a page across the publish boundary —
    gate it the same way ``publish`` is gated."""
    page = await _create_draft(editor_client)
    when = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    response = await editor_client.post(
        f"/api/pagebuilder/pages/{page['id']}/schedule",
        json={"publish_at": when},
    )
    assert response.status_code == 403


async def test_publish_clears_pending_publish_at(authed_client: AsyncClient) -> None:
    """Manually publishing should clear ``publish_at`` so the scheduler
    doesn't keep firing on the now-already-published page."""
    page = await _create_draft(authed_client)
    when = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/schedule",
        json={"publish_at": when},
    )
    response = await authed_client.post(f"/api/pagebuilder/pages/{page['id']}/publish")
    assert response.status_code == 200
    detail = await authed_client.get(f"/api/pagebuilder/pages/{page['id']}")
    assert detail.json()["publish_at"] is None


async def test_unpublish_clears_pending_unpublish_at(
    authed_client: AsyncClient,
) -> None:
    page = await _create_draft(authed_client)
    await authed_client.post(f"/api/pagebuilder/pages/{page['id']}/publish")
    when = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/schedule",
        json={"unpublish_at": when},
    )
    response = await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/unpublish"
    )
    assert response.status_code == 200
    detail = await authed_client.get(f"/api/pagebuilder/pages/{page['id']}")
    assert detail.json()["unpublish_at"] is None


# ── Service-layer process_due tests ───────────────────────────────────
#
# These spin up a bare session (no app) so we can drive process_due
# with a fake ``now`` without involving the scheduler loop.


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
