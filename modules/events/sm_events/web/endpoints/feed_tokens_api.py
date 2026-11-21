"""``/api/events``: a user's private feed links, listed without their secrets.

The parent router binds the tenant (first) and the CSRF check. Every route needs
``events.view``; the calendar's own visibility then decides (404 for one the caller may not
see, as everywhere). A person lists and revokes their own links; ``events.manage`` lists
everyone's (``?all=true``) and revokes any. The token appears **once**, in the ``201`` body of
the create call (``no-store``, ``no-referrer``), and in no other response.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from simple_module_core.resources import ResourcePrincipal
from simple_module_db.deps import get_db
from simple_module_hosting.resource_deps import resource_principal

from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.feeds.tokens import service
from sm_events.models import FeedToken
from sm_events.web.endpoints.deps import require_view
from sm_events.web.endpoints.public import _urls
from sm_events.web.schemas.feed_tokens import TokenCreate, TokenCreated, TokenOut
from sm_events.web.services.names import member_names

router = APIRouter(tags=["feed-tokens"], dependencies=[require_view])

Principal = Annotated[ResourcePrincipal, Depends(resource_principal)]


def _out(row: FeedToken, who: ResourcePrincipal, names: dict[str, str | None]) -> TokenOut:
    return TokenOut(
        id=row.id,
        label=row.label,
        locale=row.locale,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        user_id=row.user_id,
        user_name=names.get(row.user_id),
        mine=who.user_id == row.user_id,
    )


@router.get("/calendars/{calendar_id}/feed-tokens")
async def list_feed_tokens(
    calendar_id: uuid.UUID,
    request: Request,
    who: Principal,
    db=Depends(get_db),
    all: bool = Query(False),
) -> list[TokenOut]:
    rows = await service.list_tokens(db, who, calendar_id, everyone=all)
    names = await member_names(request, db, [r.user_id for r in rows])
    return [_out(row, who, names) for row in rows]


@router.post("/calendars/{calendar_id}/feed-tokens", status_code=201)
async def create_feed_token(
    calendar_id: uuid.UUID,
    body: TokenCreate,
    request: Request,
    response: Response,
    who: Principal,
    db=Depends(get_db),
) -> TokenCreated:
    created = await service.create_token(
        db, request, who, calendar_id, label=body.label, locale=body.locale, now=utcnow()
    )
    path = _urls.private_feed_path(created.secret)
    link = _urls.absolute(request, path)
    names = await member_names(request, db, [created.token.user_id])
    response.headers["Cache-Control"] = constants.PRIVATE_FEED_NO_STORE
    response.headers["Referrer-Policy"] = constants.NO_REFERRER
    return TokenCreated(
        **_out(created.token, who, names).model_dump(),
        url=link,
        webcal_url=constants.WEBCAL_SCHEME + link.split("://", 1)[1],
    )


@router.delete("/feed-tokens/{token_id}", status_code=204)
async def revoke_feed_token(token_id: uuid.UUID, who: Principal, db=Depends(get_db)) -> Response:
    await service.revoke_token(db, who, token_id, now=utcnow())
    return Response(status_code=204)
