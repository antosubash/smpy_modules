"""Restoring a snapshot taken before a page was renamed (#205).

The snapshot's page is matched to the live row by ``(translation_group,
locale)`` rather than by slug, so a rename is followed: the row is overwritten
and moved back, never inserted a second time beside itself — which used to trip
the ``(tenant, translation_group, locale)`` index and abort the restore.

Driven through ``SnapshotService`` so staging, the approval-time preflight and
the apply are the real ones.
"""

from __future__ import annotations

from pagebuilder.content.service.pages import PagesService
from pagebuilder.content.snapshots.service import SnapshotService
from pagebuilder.contracts import PageUpdate
from pagebuilder.models import Page, PageRedirect
from sqlmodel import select


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
