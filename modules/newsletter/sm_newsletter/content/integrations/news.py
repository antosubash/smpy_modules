"""Article cards through ``news.contracts.articles`` (the ``news`` extra).

The tenant is the caller's bound one, passed explicitly; the contract pins it.
"""

from __future__ import annotations

import importlib
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.content.integrations.hits import (
    MAX_SOURCE_ID,
    SEARCH_LIMIT,
    CardHit,
    like_pattern,
)
from sm_newsletter.core.errors import IntegrationUnavailable

_CONTRACT = "news.contracts.articles"
_STATE = "news"


def _contract() -> Any | None:
    # `import_module`, not `from news.contracts import articles`: the latter
    # finds an attribute left on the package and would ignore a blocked import.
    try:
        return importlib.import_module(_CONTRACT)
    except ImportError:
        return None


def available(app: Any) -> bool:
    """The contract imports and news is mounted on ``app``."""
    mounted = getattr(getattr(app, "state", None), _STATE, None) is not None
    return mounted and _contract() is not None


def _require(app: Any) -> Any:
    contract = _contract()
    if contract is None or getattr(getattr(app, "state", None), _STATE, None) is None:
        raise IntegrationUnavailable()
    return contract


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
