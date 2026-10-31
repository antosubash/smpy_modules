"""Page-creating helpers shared across tests.

A plain module rather than a conftest addition: ``conftest.py`` sits exactly on
the repo's 300-line cap, and ``tests`` is on ``pythonpath`` (see the module's
``[tool.pytest.ini_options]``), so ``from page_helpers import create_draft``
works from any test file.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from pagebuilder.models import Page, PageRevision, PageStatus, RevisionEvent
from sqlalchemy import func, select

NOW = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(hours=1)

PUBLISH_CLAIM = {"column": Page.publish_at, "status": PageStatus.DRAFT}


async def create_draft(
    client: AsyncClient,
    *,
    slug: str = "post",
    title: str = "Draft",
    draft_data: dict | None = None,
) -> dict:
    """POST a fresh draft page and return the API body."""
    response = await client.post(
        "/api/pagebuilder/pages",
        json={
            "title": title,
            "slug": slug,
            "draft_data": draft_data
            if draft_data is not None
            else {"content": ["hello"]},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def make_page(db, slug: str, **fields) -> Page:
    """Flush a bare page row (a draft unless ``fields`` say otherwise)."""
    page = Page(title=slug, slug=slug, draft_data={"content": [slug]}, **fields)
    db.add(page)
    await db.flush()
    await db.refresh(page)
    return page


async def publish_revisions(db, page_id: int) -> int:
    """How many PUBLISH revisions the page has."""
    total = await db.execute(
        select(func.count())
        .select_from(PageRevision)
        .where(PageRevision.page_id == page_id, PageRevision.event == RevisionEvent.PUBLISH)
    )
    return total.scalar_one()
