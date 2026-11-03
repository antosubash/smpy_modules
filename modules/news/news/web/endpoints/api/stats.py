"""``GET /stats`` — one public number, for the ``NewsStats`` block.

Anonymous and cacheable like the feed reads it sits beside, so it shares their
router (and with it the tenant binding) and their headers. ``metric`` is a
``Literal`` with a single member rather than a free string: the day a second
metric is added, a client that sends the old name keeps working and one that
sends a typo is told so with a 422 instead of being handed a number for a
question it did not ask.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from news.content import service, stats
from news.core.constants import PUBLIC_STATS_MAX_COUNT
from news.web.endpoints.api._deps import cache

router = APIRouter()


# HEAD is explicit: ``register_public_routes`` lists it for this path, and a
# prober (or a CDN revalidating) should get the headers without a body.
@router.api_route("/stats", methods=["GET", "HEAD"])
async def published_count(
    request: Request,
    response: Response,
    metric: Literal["published"] = Query(
        description="What to count. Only `published`: articles a reader can open."
    ),
    category: str | None = Query(
        None, description="Only articles in this category, by name or by slug."
    ),
    locale: str | None = Query(
        None,
        description=(
            "Only articles written in this language. Omitted counts every language "
            "the site publishes in; one it does not publish in counts nothing."
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int | bool]:
    del metric  # validated by the type; there is one answer
    # Never ``include_drafts``: the count is public whoever asks, so an editor's
    # session must not change it either.
    cache(response, request, include_drafts=False)
    # A slug is what a public link carries and a name what the editor typed;
    # the listing accepts both, so the figure beside it has to as well.
    if category:
        category = await service.resolve_category_slug(db, category) or category
    value, capped = await stats.count_published(
        db,
        category=category,
        locale=locale,
        now=datetime.now(UTC),
        cap=PUBLIC_STATS_MAX_COUNT,
    )
    return {"value": value, "capped": capped}
