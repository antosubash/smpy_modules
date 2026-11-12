"""Page cards and the image picker through ``pagebuilder.contracts.cards``
(the ``pagebuilder`` extra).

The tenant is the caller's bound one, passed explicitly; the contract pins it.
Media are raster images only (the contract drops SVG).
"""

from __future__ import annotations

import importlib
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.content.integrations.hits import (
    MAX_SOURCE_ID,
    SEARCH_LIMIT,
    CardHit,
    MediaHit,
    like_pattern,
)
from sm_newsletter.core.errors import IntegrationUnavailable

_CONTRACT = "pagebuilder.contracts.cards"


def _contract() -> Any | None:
    # `import_module`, not `from ... import cards`: see `integrations.news`.
    try:
        return importlib.import_module(_CONTRACT)
    except ImportError:
        return None


def available(app: Any) -> bool:
    """The contract imports and pagebuilder is mounted on ``app``."""
    contract = _contract()
    return contract is not None and contract.mounted(app)


def _require(app: Any) -> Any:
    contract = _contract()
    if contract is None or not contract.mounted(app):
        raise IntegrationUnavailable()
    return contract


def _hit(card: Any) -> CardHit:
    return CardHit(
        kind="page",
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
    """Published pages of ``tenant_id`` whose title or slug contains ``q``."""
    contract = _require(app)
    cards = await contract.search_page_cards(
        app,
        session,
        tenant_id=tenant_id,
        pattern=like_pattern(q),
        limit=SEARCH_LIMIT,
        locale=locale,
    )
    return [_hit(c) for c in cards]


async def card(
    app: Any, session: AsyncSession, *, tenant_id: str, source_id: int
) -> CardHit | None:
    """The published page ``source_id`` of ``tenant_id``, or ``None``."""
    contract = _require(app)
    if not 0 < source_id <= MAX_SOURCE_ID:
        return None
    found = await contract.get_page_card(app, session, tenant_id=tenant_id, page_id=source_id)
    return None if found is None else _hit(found)


async def search_media(
    app: Any, session: AsyncSession, *, tenant_id: str, q: str
) -> list[MediaHit]:
    """Raster images of ``tenant_id`` whose name contains ``q``."""
    contract = _require(app)
    found = await contract.search_media_cards(
        app, session, tenant_id=tenant_id, pattern=like_pattern(q), limit=SEARCH_LIMIT
    )
    return [MediaHit(id=m.id, filename=m.filename, url=m.path) for m in found]
