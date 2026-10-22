"""Restoring a snapshot taken before a page was renamed (#205).

The snapshot's page is matched to the live row by ``(translation_group,
locale)`` rather than by slug, so a rename is followed: the row is overwritten
and moved back, never inserted a second time beside itself — which used to trip
the ``(tenant, translation_group, locale)`` index and abort the restore.

Driven through ``SnapshotService`` so staging, the approval-time preflight and
the apply are the real ones.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pagebuilder.contracts import PageUpdate
from pagebuilder.models import ContentSnapshot, Page, PageRedirect, SnapshotSource
from pagebuilder.service import PagesService
from pagebuilder.snapshots.service import SnapshotService
from sqlmodel import select

pytestmark = pytest.mark.asyncio


async def _page(session, slug: str, **fields) -> Page:
    fields.setdefault("title", slug.title())
    page = Page(slug=slug, draft_data={"content": [slug]}, **fields)
    session.add(page)
    await session.flush()
    return page


async def _rename(session, page: Page, slug: str) -> None:
    await PagesService(session).update(page.id, PageUpdate(slug=slug))


async def _pages(session) -> list[Page]:
    result = await session.execute(select(Page).order_by(Page.id))
    return list(result.scalars().all())


async def _redirects(session) -> dict[tuple[str, str], int]:
    result = await session.execute(select(PageRedirect))
    return {(r.locale, r.from_slug): r.page_id for r in result.scalars().all()}


def _service(snapshot_db) -> SnapshotService:
    return SnapshotService(snapshot_db.session, snapshot_db.settings)


async def _snapshot(snapshot_db) -> int:
    return (await _service(snapshot_db).take("before")).id


async def _restore(snapshot_db, snapshot_id: int) -> tuple[dict, dict]:
    service = _service(snapshot_db)
    staged = await service.request_restore(snapshot_id)
    result = await service.approve(staged.id, "tester")
    # The staged plan, now carrying what the apply recorded under "applied".
    return staged.plan, result


# --- plan --------------------------------------------------------------------


async def test_the_plan_follows_a_renamed_page(snapshot_db):
    session = snapshot_db.session
    page = await _page(session, "old")
    snapshot_id = await _snapshot(snapshot_db)
    await _rename(session, page, "newer")

    plan = (await _service(snapshot_db).request_restore(snapshot_id)).plan

    assert plan["pages"]["new"] == []
    [entry] = plan["pages"]["overwritten"]
    assert (entry["slug"], entry["renamed_from"]) == ("old", "newer")
    # The renamed row is the page being restored, not a bystander.
    assert plan["pages"]["untouched"] == []
    assert plan["redirects"]["added"] == ["newer"]


async def test_the_plan_follows_a_renamed_page_into_the_trash(snapshot_db):
    session = snapshot_db.session
    page = await _page(session, "old")
    snapshot_id = await _snapshot(snapshot_db)
    await _rename(session, page, "newer")
    await PagesService(session).delete(page.id)

    plan = (await _service(snapshot_db).request_restore(snapshot_id)).plan

    assert plan["pages"]["new"] == []
    [entry] = plan["pages"]["overwritten"]
    assert entry["revived"] is True
    assert entry["renamed_from"] == "newer"


# --- apply -------------------------------------------------------------------


async def test_restore_moves_the_renamed_page_back(snapshot_db):
    session = snapshot_db.session
    page = await _page(session, "old")
    group = page.translation_group
    snapshot_id = await _snapshot(snapshot_db)
    await _rename(session, page, "newer")
    assert await _redirects(session) == {("en", "old"): page.id}

    _, result = await _restore(snapshot_db, snapshot_id)

    assert (result["pages_created"], result["pages_updated"]) == (0, 1)
    [restored] = await _pages(session)
    assert (restored.id, restored.slug, restored.locale) == (page.id, "old", "en")
    assert restored.translation_group == group
    # The old address is a page again; the newer one now forwards to it.
    assert await _redirects(session) == {("en", "newer"): page.id}


async def test_restoring_twice_creates_nothing(snapshot_db):
    session = snapshot_db.session
    page = await _page(session, "old")
    snapshot_id = await _snapshot(snapshot_db)
    await _rename(session, page, "newer")
    await _restore(snapshot_db, snapshot_id)

    plan, result = await _restore(snapshot_db, snapshot_id)

    assert [e["slug"] for e in plan["pages"]["unchanged"]] == ["old"]
    assert plan["pages"]["new"] == plan["pages"]["overwritten"] == []
    assert (result["pages_created"], plan["applied"]["overwritten"]) == (0, [])
    assert [p.id for p in await _pages(session)] == [page.id]


async def test_a_purged_original_is_recreated_where_its_slug_is_free(snapshot_db):
    session = snapshot_db.session
    page = await _page(session, "old")
    group = page.translation_group
    snapshot_id = await _snapshot(snapshot_db)
    await _rename(session, page, "newer")
    await PagesService(session).delete(page.id)
    await PagesService(session).purge(page.id)

    _, result = await _restore(snapshot_db, snapshot_id)

    assert result["pages_created"] == 1
    [recreated] = await _pages(session)
    assert (recreated.slug, recreated.translation_group) == ("old", group)


async def test_a_hand_made_page_reusing_a_purged_id_is_left_alone(snapshot_db):
    """SQLite hands a purged id to the next insert; ids are not identity."""
    session = snapshot_db.session
    page = await _page(session, "old")
    snapshot_id = await _snapshot(snapshot_db)
    await PagesService(session).delete(page.id)
    await PagesService(session).purge(page.id)
    other = await _page(session, "other")

    _, result = await _restore(snapshot_db, snapshot_id)

    assert result["pages_created"] == 1
    await session.refresh(other)
    assert (other.slug, other.title) == ("other", "Other")
    assert sorted(p.slug for p in await _pages(session)) == ["old", "other"]


# --- conflicts ---------------------------------------------------------------


@pytest.mark.parametrize("trashed", [False, True])
async def test_another_page_on_the_old_slug_refuses_the_restore(snapshot_db, trashed):
    session = snapshot_db.session
    page = await _page(session, "old")
    snapshot_id = await _snapshot(snapshot_db)
    await _rename(session, page, "newer")
    squatter = await _page(session, "old")
    if trashed:
        await PagesService(session).delete(squatter.id)

    with pytest.raises(HTTPException) as caught:
        await _service(snapshot_db).request_restore(snapshot_id)

    assert caught.value.status_code == 409
    assert "/old (en)" in caught.value.detail
    await session.refresh(page)
    assert page.slug == "newer"


async def test_the_preflight_runs_again_at_approval(snapshot_db):
    """Staged while the restore could land; refused once it no longer can."""
    session = snapshot_db.session
    page = await _page(session, "old")
    snapshot_id = await _snapshot(snapshot_db)
    service = _service(snapshot_db)
    staged = await service.request_restore(snapshot_id)

    await _rename(session, page, "newer")
    squatter = await _page(session, "old", title="Squatter")

    with pytest.raises(HTTPException) as caught:
        await service.approve(staged.id, "tester")

    assert caught.value.status_code == 409
    # Refused before the pre-restore snapshot and before any page write.
    pre = await session.execute(
        select(ContentSnapshot).where(ContentSnapshot.source == SnapshotSource.PRE_RESTORE)
    )
    assert pre.scalars().all() == []
    await session.refresh(page)
    await session.refresh(squatter)
    assert (page.slug, squatter.slug, squatter.title) == ("newer", "old", "Squatter")
