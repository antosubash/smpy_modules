"""Prompts: CRUD, their results, and running an image prompt (spec §3, §8).

Reading is a ``view`` on the collection; creating, editing, deleting and
running are an ``edit`` (owner, an edit share, ``images.manage``) - a prompt
run costs AI requests, which is the same trust as uploading. A prompt is
reachable exactly when its collection is, so a stranger gets the 404 an
unknown id gets. The console's prompt manager is Task 23.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from simple_module_core.resources import ACTION_EDIT, ACTION_VIEW
from simple_module_db.deps import get_db
from simple_module_hosting.resource_deps import RequiresResource
from sqlalchemy import select

from sm_images import ai, constants
from sm_images.access import POLICY, CollectionEdit, CollectionView
from sm_images.ai import run as runs
from sm_images.deps import require_view
from sm_images.endpoints.api._runtime import runtime, tenant
from sm_images.errors import Invalid, ServiceUnavailable
from sm_images.models import Collection, Prompt, PromptResult
from sm_images.models.enums import PromptScope
from sm_images.schemas.prompt import (
    PromptCreate,
    PromptListOut,
    PromptOut,
    PromptResultOut,
    PromptResultPageOut,
    PromptRunIn,
    PromptRunOut,
    PromptUpdate,
)
from sm_images.services import prompts as service

router = APIRouter(tags=["prompts"])


def prompt_collection_stmt(prompt_id: uuid.UUID):
    """The collection holding prompt ``prompt_id``, for the ``/prompts/{id}`` routes."""
    return (
        select(Collection)
        .join(Prompt, Prompt.collection_id == Collection.id)
        .where(Prompt.id == prompt_id)
    )


PromptCollectionView = Annotated[
    Collection, Depends(RequiresResource(POLICY, ACTION_VIEW, prompt_collection_stmt))
]
PromptCollectionEdit = Annotated[
    Collection, Depends(RequiresResource(POLICY, ACTION_EDIT, prompt_collection_stmt))
]


def _out(row: Prompt) -> PromptOut:
    return PromptOut.model_validate(row, from_attributes=True)


def _result(row: PromptResult, revision: int) -> PromptResultOut:
    stale = row.prompt_revision is not None and row.prompt_revision != revision
    return PromptResultOut.model_validate(
        {**row.model_dump(), "history": list(row.history or []), "stale": stale}
    )


@router.get("/collections/{collection_id}/prompts", dependencies=[require_view])
async def list_prompts(collection: CollectionView, db=Depends(get_db)) -> PromptListOut:
    return PromptListOut(items=[_out(p) for p in await service.list_prompts(db, collection)])


@router.post("/collections/{collection_id}/prompts", status_code=201, dependencies=[require_view])
async def create_prompt(
    body: PromptCreate, collection: CollectionEdit, db=Depends(get_db)
) -> PromptOut:
    return _out(await service.create(db, collection, body))


@router.get("/prompts/{prompt_id}", dependencies=[require_view])
async def get_prompt(
    prompt_id: uuid.UUID, collection: PromptCollectionView, db=Depends(get_db)
) -> PromptOut:
    return _out(await service.get(db, collection, prompt_id))


@router.patch("/prompts/{prompt_id}", dependencies=[require_view])
async def patch_prompt(
    prompt_id: uuid.UUID, body: PromptUpdate, collection: PromptCollectionEdit, db=Depends(get_db)
) -> PromptOut:
    row = await service.get(db, collection, prompt_id)
    changes = body.model_dump(exclude_unset=True)
    return _out(await service.update(db, collection, row, changes))


@router.delete("/prompts/{prompt_id}", status_code=204, dependencies=[require_view])
async def delete_prompt(
    prompt_id: uuid.UUID, collection: PromptCollectionEdit, db=Depends(get_db)
) -> Response:
    await service.delete_prompt(db, collection, await service.get(db, collection, prompt_id))
    return Response(status_code=204)


@router.get("/prompts/{prompt_id}/results", dependencies=[require_view])
async def list_results(
    prompt_id: uuid.UUID,
    collection: PromptCollectionView,
    db=Depends(get_db),
    limit: int = Query(constants.PAGE_DEFAULT, ge=1, le=constants.PAGE_MAX),
    after: int | None = Query(None, ge=0),
) -> PromptResultPageOut:
    row = await service.get(db, collection, prompt_id)
    found, cursor = await service.results_page(db, row, limit=limit, after=after)
    return PromptResultPageOut(items=[_result(r, row.revision) for r in found], next_cursor=cursor)


@router.post("/prompts/{prompt_id}/run", status_code=202, dependencies=[require_view])
async def run_prompt(
    prompt_id: uuid.UUID, body: PromptRunIn, collection: PromptCollectionEdit, db=Depends(get_db)
) -> PromptRunOut:
    """Request the prompt's run on the collection's images (``scope``) or on
    ``image_ids`` of it, and plan them; a whole collection may be queued."""
    if not ai.ai_available():
        err = ServiceUnavailable("the ai module is not installed")
        err.code = constants.CODE_AI_UNAVAILABLE
        raise err
    row = await service.get(db, collection, prompt_id)
    if row.scope is not PromptScope.IMAGE:
        err = Invalid("group-scope prompts are run per group")
        err.code = constants.CODE_GROUP_RUN_UNSUPPORTED
        raise err
    await db.rollback()  # read-only so far: release it before the per-image transactions
    requested = await runs.launch(runtime(), tenant(), prompt_id, body.scope, body.image_ids)
    return PromptRunOut(scope=body.scope, requested=requested)
