"""``/cards/*`` (article and page search, snapshot), ``/media`` (the image
picker) and ``/campaigns/{id}/cards/refresh``.

``bind_admin`` first on the router (see ``settings_api``), ``newsletter.edit``
on every route after it: these only serve the editor. A source that is not
installed or not mounted answers 409 ``integration_unavailable``. Search,
snapshot and media are not campaign-scoped; the refresh goes through
``require_campaign`` with the caller's roles (ruling C4).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from simple_module_db.deps import get_db
from simple_module_hosting.permissions import RequiresPermission
from sm_records.contracts.newsletter import caller_roles
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.content import cards
from sm_newsletter.content.integrations import news, pagebuilder
from sm_newsletter.core import constants
from sm_newsletter.core.tenancy import bind_admin
from sm_newsletter.web.schemas.campaigns import CampaignDetail, parse_payload
from sm_newsletter.web.schemas.cards import (
    CardHitOut,
    CardSnapshot,
    MediaHitOut,
    RefreshRequest,
    SnapshotRequest,
)

router = APIRouter(
    dependencies=[Depends(bind_admin), Depends(RequiresPermission(constants.PERM_EDIT))]
)

_Q = Query("", max_length=200)
_LOCALE = Query(None, max_length=16)


@router.get("/cards/articles", response_model=list[CardHitOut])
async def search_articles(
    request: Request,
    q: str = _Q,
    locale: str | None = _LOCALE,
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> list[CardHitOut]:
    hits = await news.search(request.app, db, tenant_id=tenant, q=q, locale=locale or None)
    return [CardHitOut.model_validate(h) for h in hits]


@router.get("/cards/pages", response_model=list[CardHitOut])
async def search_pages(
    request: Request,
    q: str = _Q,
    locale: str | None = _LOCALE,
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> list[CardHitOut]:
    hits = await pagebuilder.search(request.app, db, tenant_id=tenant, q=q, locale=locale or None)
    return [CardHitOut.model_validate(h) for h in hits]


@router.post("/cards/snapshot", response_model=CardSnapshot)
async def snapshot(
    request: Request,
    payload: Any = Body(...),
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> CardSnapshot:
    data = parse_payload(SnapshotRequest, payload)
    props = await cards.snapshot(
        request.app, db, tenant_id=tenant, kind=data.kind, source_id=data.source_id
    )
    return CardSnapshot.model_validate(props)


@router.get("/media", response_model=list[MediaHitOut])
async def search_media(
    request: Request,
    q: str = _Q,
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> list[MediaHitOut]:
    hits = await pagebuilder.search_media(request.app, db, tenant_id=tenant, q=q)
    return [MediaHitOut.model_validate(h) for h in hits]


@router.post("/campaigns/{campaign_id}/cards/refresh", response_model=CampaignDetail)
async def refresh_card(
    campaign_id: int,
    request: Request,
    payload: Any = Body(...),
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> CampaignDetail:
    data = parse_payload(RefreshRequest, payload)
    campaign = await cards.refresh_block(
        request.app,
        db,
        tenant_id=tenant,
        campaign_id=campaign_id,
        block_id=data.block_id,
        expected_revision=data.expected_revision,
        roles=caller_roles(request),
    )
    return CampaignDetail.model_validate(campaign)
