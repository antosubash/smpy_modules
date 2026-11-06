"""``/lists/{key}/subscribers``: the browse, one subscriber's detail, tags and the
admin unsubscribe.

``bind_admin`` first, then ``newsletter.view`` *and* ``records.view`` (a
subscriber is a records row). The browse is a ``POST`` so the search text
travels in the body, never in a URL or an access log; there is no GET listing.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from simple_module_db.deps import get_db
from simple_module_hosting.permissions import RequiresPermission
from sm_records.contracts.newsletter import caller_roles
from sm_records.contracts.newsletter_admin import subscriber_admin_url
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core import clock, constants
from sm_newsletter.core.errors import NotFound
from sm_newsletter.core.errors_audience import InvalidQuery
from sm_newsletter.core.tenancy import bind_admin
from sm_newsletter.subscribers import actions
from sm_newsletter.subscribers import browse as browsing
from sm_newsletter.web.schemas.campaigns import parse_payload
from sm_newsletter.web.schemas.subscribers import (
    EmptyIn,
    SubscriberDetailOut,
    SubscriberOut,
    SubscriberPageOut,
    SubscriberSearchIn,
    SubscriberTagsIn,
)

router = APIRouter(dependencies=[Depends(bind_admin)])

_READ = [
    Depends(RequiresPermission(constants.PERM_VIEW)),
    Depends(RequiresPermission(constants.PERM_RECORDS_VIEW)),
]
_TAG = [
    Depends(RequiresPermission(constants.PERM_EDIT)),
    Depends(RequiresPermission(constants.PERM_RECORDS_VIEW)),
]
_STOP = [
    Depends(RequiresPermission(constants.PERM_MANAGE)),
    Depends(RequiresPermission(constants.PERM_RECORDS_VIEW)),
]
_UUID = re.compile(r"[0-9a-f]{32}")


@router.post(
    "/lists/{list_type_key}/subscribers/search",
    response_model=SubscriberPageOut,
    dependencies=_READ,
)
async def search(
    list_type_key: str,
    request: Request,
    payload: Any = Body(...),
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> SubscriberPageOut:
    data = parse_payload(SubscriberSearchIn, payload, error=InvalidQuery)
    result = await browsing.browse(
        db,
        tenant_id=tenant,
        list_type_key=list_type_key,
        roles=caller_roles(request),
        status=data.status,
        q=data.q,
        tag=data.tag,
        segment_id=data.segment,
        offset=data.offset,
        limit=data.limit,
    )
    return SubscriberPageOut(
        items=[SubscriberOut.of(r) for r in result.rows],
        total=result.total,
        counts=result.counts,
        records_url=subscriber_admin_url(list_type_key),
    )


@router.get(
    "/lists/{list_type_key}/subscribers/{uuid}",
    response_model=SubscriberDetailOut,
    dependencies=_READ,
)
async def subscriber(
    list_type_key: str,
    uuid: str,
    request: Request,
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> SubscriberDetailOut:
    if not _UUID.fullmatch(uuid):
        raise NotFound()
    found = await browsing.detail(
        db,
        tenant_id=tenant,
        list_type_key=list_type_key,
        uuid=uuid,
        roles=caller_roles(request),
    )
    return SubscriberDetailOut.of(found)


@router.post(
    "/lists/{list_type_key}/subscribers/{uuid}/tags",
    response_model=SubscriberOut,
    dependencies=_TAG,
)
async def tag_subscriber(
    list_type_key: str,
    uuid: str,
    request: Request,
    payload: Any = Body(...),
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> SubscriberOut:
    data = parse_payload(SubscriberTagsIn, payload, error=InvalidQuery)
    if not _UUID.fullmatch(uuid):
        raise NotFound()
    hit = await actions.set_subscriber_tags(
        request.app,
        db,
        tenant_id=tenant,
        list_type_key=list_type_key,
        uuid=uuid,
        add=data.add,
        remove=data.remove,
        roles=caller_roles(request),
    )
    return SubscriberOut.of(await actions.row_of(db, tenant_id=tenant, hit=hit))


@router.post(
    "/lists/{list_type_key}/subscribers/{uuid}/unsubscribe",
    response_model=SubscriberOut,
    dependencies=_STOP,
)
async def unsubscribe_subscriber(
    list_type_key: str,
    uuid: str,
    request: Request,
    payload: Any = Body(...),
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> SubscriberOut:
    parse_payload(EmptyIn, payload, error=InvalidQuery)
    if not _UUID.fullmatch(uuid):
        raise NotFound()
    hit = await actions.unsubscribe_subscriber(
        request.app,
        db,
        tenant_id=tenant,
        list_type_key=list_type_key,
        uuid=uuid,
        roles=caller_roles(request),
        now=clock.utcnow(),
    )
    return SubscriberOut.of(await actions.row_of(db, tenant_id=tenant, hit=hit))
