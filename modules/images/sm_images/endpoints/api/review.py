"""The review queue (spec §6): list a collection's AI results, review one.

Reviewing is an ``edit`` on the collection (owner, an edit share,
``images.manage``); a viewer is refused and a stranger gets the 404 an unknown
id gets, so the queue lists only what the caller can already open. The review
itself runs under the image's or group's lock and is refused as stale (409
``review_stale``) if a re-run replaced the output meanwhile
(:mod:`sm_images.ai.review`). ``PromptResultReviewed`` is published on commit.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from simple_module_core.resources import ACTION_EDIT, ResourcePrincipal
from simple_module_db.deps import get_db
from simple_module_hosting.resource_deps import RequiresResource, resource_principal
from sqlalchemy import select

from sm_images.access import POLICY, CollectionEdit
from sm_images.ai import review as service
from sm_images.core import constants, events
from sm_images.endpoints.api._runtime import tenant
from sm_images.endpoints.deps import get_settings, require_view
from sm_images.models import Collection, Prompt, PromptResult
from sm_images.models.enums import ReviewStatus
from sm_images.schemas.review import ReviewedOut, ReviewIn, ReviewPageOut
from sm_images.services import review_queue

router = APIRouter(tags=["review"])
Principal = Annotated[ResourcePrincipal, Depends(resource_principal)]


def result_collection_stmt(result_id: int):
    return (
        select(Collection)
        .join(Prompt, Prompt.collection_id == Collection.id)
        .join(PromptResult, PromptResult.prompt_id == Prompt.id)
        .where(PromptResult.id == result_id)
    )


ResultCollectionEdit = Annotated[
    Collection, Depends(RequiresResource(POLICY, ACTION_EDIT, result_collection_stmt))
]


@router.get("/collections/{collection_id}/review", dependencies=[require_view])
async def review_queue_page(
    collection: CollectionEdit,
    db=Depends(get_db),
    status: Literal["unreviewed", "accepted", "corrected", "rejected", "all"] = "unreviewed",
    prompt: uuid.UUID | None = None,
    limit: int = Query(constants.PAGE_DEFAULT, ge=1, le=constants.PAGE_MAX),
    after: int | None = Query(None, ge=0),
) -> ReviewPageOut:
    wanted = None if status == "all" else ReviewStatus(status)
    items, cursor = await review_queue.page(
        db, collection, status=wanted, prompt_id=prompt, limit=limit, after=after
    )
    return ReviewPageOut(items=items, next_cursor=cursor)


@router.post("/prompt-results/{result_id}/review", dependencies=[require_view])
async def review_result(
    result_id: int,
    body: ReviewIn,
    request: Request,
    collection: ResultCollectionEdit,
    who: Principal,
    db=Depends(get_db),
) -> ReviewedOut:
    limit = getattr(get_settings(request), "step_output_max_bytes", None)
    row, prompt = await service.apply(
        db,
        tenant(),
        result_id,
        collection.id,
        action=body.action,
        data=body.data,
        version=body.version,
        reviewer=str(who.user_id),
        max_bytes=limit,
    )
    bus = getattr(getattr(request.app.state, "sm", None), "event_bus", None)
    events.emit(db, bus, events.result_reviewed(row, collection.id, body.action, str(who.user_id)))
    item = await review_queue.item_out(db, collection, row, prompt)
    return ReviewedOut(item=item, collection_id=collection.id)
