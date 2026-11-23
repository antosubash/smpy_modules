"""Article cards through ``news.contracts.articles`` (the ``news`` extra).

The tenant is the caller's bound one, passed explicitly; the contract pins it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.content.integrations._guard import Guard
from sm_newsletter.content.integrations.hits import (
    MAX_SOURCE_ID,
    SEARCH_LIMIT,
    CardHit,
    like_pattern,
)

_GUARD = Guard("news.contracts.articles")


def available(app: Any) -> bool:
    """The contract imports and news is mounted on ``app``."""
    return _GUARD.available(app)


_require = _GUARD.require


def _hit(card: Any) -> CardHit:
    return CardHit(
        kind="article",
        source_id=card.id,
        title=card.title,
        excerpt=card.excerpt,
        image_url=card.image_url,
        url=card.path,
        locale=card.locale,
    )


async def search(
    app: Any, session: AsyncSession, *, tenant_id: str, q: str, locale: str | None
) -> list[CardHit]:
    """Published articles of ``tenant_id`` whose title contains ``q``."""
    contract = _require(app)
    cards = await contract.search_articles(
        session, tenant_id=tenant_id, pattern=like_pattern(q), limit=SEARCH_LIMIT, locale=locale
    )
    return [_hit(c) for c in cards]


async def card(
    app: Any, session: AsyncSession, *, tenant_id: str, source_id: int
) -> CardHit | None:
    """The published article ``source_id`` of ``tenant_id``, or ``None``."""
    contract = _require(app)
    if not 0 < source_id <= MAX_SOURCE_ID:
        return None
    found = await contract.get_article_card(session, tenant_id=tenant_id, article_id=source_id)
    return None if found is None else _hit(found)
