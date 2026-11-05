"""Article and page cards: snapshotted server-side, refreshed server-side (ruling R9).

A card's props are a *snapshot* of its source, read through the source
module's contract: what was sent is what the snapshot said, whatever the
article says later. *Refresh* rewrites one card's snapshot in the stored draft
through :func:`~sm_newsletter.campaigns.drafts.write_draft`, the same
conditional, revision-bumping write a PATCH makes (amendment 2). A source that
is no longer published, trashed, gone or another tenant's answers 409
``card_source_gone`` and the stored campaign is left exactly as it was.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns import drafts
from sm_newsletter.campaigns.access import Roles, require_campaign
from sm_newsletter.content.blocks import CardProps, dump_body, parse_body
from sm_newsletter.content.integrations import CardHit, news, pagebuilder
from sm_newsletter.content.urls import check_image, check_link
from sm_newsletter.core.clock import utcnow
from sm_newsletter.core.errors import (
    BlockNotFound,
    CardSourceGone,
    NotADraft,
    NotFound,
    StaleCampaign,
)
from sm_newsletter.models import Campaign

_SOURCES = {"article": news, "page": pagebuilder}
_KIND_OF_BLOCK = {"ArticleCard": "article", "PageCard": "page"}
# CardProps' bounds; `snapshot_props` validates against the model all the same.
_TITLE, _EXCERPT, _LOCALE = 300, 1000, 16


def _fits(check: Any, value: str) -> bool:
    try:
        check(value)
    except ValueError:
        return False
    return True


def snapshot_props(hit: CardHit, *, block_id: str, now: datetime) -> dict[str, Any]:
    """The card block's props for ``hit``: clipped to what the body accepts, an
    image it would refuse dropped. A source whose address the body would refuse
    cannot be carded (:class:`CardSourceGone`)."""
    if not _fits(check_link, hit.url):
        raise CardSourceGone()
    props = {
        "id": block_id,
        "source_id": hit.source_id,
        "title": hit.title[:_TITLE],
        "excerpt": hit.excerpt[:_EXCERPT],
        "image_url": hit.image_url if _fits(check_image, hit.image_url) else "",
        "url": hit.url,
        "locale": hit.locale[:_LOCALE],
        "snapshot_at": now.isoformat(),
    }
    return CardProps.model_validate(props).model_dump(mode="json")


async def _read(app: Any, session: AsyncSession, *, tenant_id: str, kind: str, source_id: int):
    return await _SOURCES[kind].card(app, session, tenant_id=tenant_id, source_id=source_id)


async def snapshot(
    app: Any, session: AsyncSession, *, tenant_id: str, kind: str, source_id: int
) -> dict[str, Any]:
    """A new card's props, with a fresh block id. :class:`IntegrationUnavailable`
    when the source module is not there, :class:`NotFound` when the article or
    page is not published in ``tenant_id``."""
    hit = await _read(app, session, tenant_id=tenant_id, kind=kind, source_id=source_id)
    if hit is None:
        raise NotFound()
    return snapshot_props(hit, block_id=uuid4().hex[:12], now=utcnow())


async def refresh_block(
    app: Any,
    session: AsyncSession,
    *,
    tenant_id: str,
    campaign_id: int,
    block_id: str,
    expected_revision: int,
    roles: Roles,
) -> Campaign:
    """Re-read card ``block_id``'s source and write its new snapshot into the
    draft: the block keeps its ``id``, every other prop is replaced."""
    campaign = await require_campaign(
        session, tenant_id=tenant_id, campaign_id=campaign_id, roles=roles
    )
    if campaign.status != drafts.DRAFT:
        raise NotADraft()
    if campaign.revision != expected_revision:
        raise StaleCampaign()  # before reading the source: the editor's view is old
    blocks = parse_body(campaign.body)
    index = next((i for i, b in enumerate(blocks) if b.props.id == block_id), None)
    if index is None or blocks[index].type not in _KIND_OF_BLOCK:
        raise BlockNotFound()
    block = blocks[index]
    assert isinstance(block.props, CardProps)  # both card blocks carry CardProps
    kind = _KIND_OF_BLOCK[block.type]
    hit = await _read(app, session, tenant_id=tenant_id, kind=kind, source_id=block.props.source_id)
    if hit is None:
        raise CardSourceGone()
    body = dump_body(blocks)
    body[index]["props"] = snapshot_props(hit, block_id=block_id, now=utcnow())
    return await drafts.write_draft(
        session,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        expected_revision=expected_revision,
        values={"body": body},
        roles=roles,
    )
