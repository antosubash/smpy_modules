"""Prompts: CRUD, their results, and running an image prompt (spec §3, §8).

Reading is a ``view`` on the collection; creating, editing, deleting and
running on named images are an ``edit`` (owner, an edit share,
``images.manage``). What can spend AI requests without bound is the owner's or
a manager's, like a collection restart or a forced reprocess: a run over the
whole collection, a run with scope ``all``, and switching ``auto_run`` on. A prompt is
reachable exactly when its collection is, so a stranger gets the 404 an
unknown id gets. An image prompt runs on ``image_ids``, a group prompt on
``group_ids`` (:mod:`sm_images.pipeline.ai.group_request`); the other list is a 422
``invalid_run_target``.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from simple_module_core.resources import (
    ACTION_DELETE,
    ACTION_EDIT,
    ACTION_VIEW,
    ResourcePrincipal,
)
from simple_module_db.deps import get_db
from simple_module_hosting.resource_deps import RequiresResource, resource_principal
from sqlalchemy import select

from sm_images.core import constants
from sm_images.core.access import POLICY, CollectionEdit, CollectionView
from sm_images.core.access.starter_right import owner_or_manage_basis
from sm_images.core.errors import Forbidden, Invalid, ServiceUnavailable
from sm_images.models import Collection, Prompt, PromptResult
from sm_images.models.enums import PromptScope
from sm_images.pipeline import ai
from sm_images.pipeline.ai import codes
from sm_images.pipeline.ai import run as runs
from sm_images.web.endpoints.api._runtime import runtime, tenant
from sm_images.web.endpoints.deps import require_view
from sm_images.web.schemas.prompt import (
    PromptCreate,
    PromptListOut,
    PromptOut,
    PromptResultOut,
    PromptResultPageOut,
    PromptRunIn,
    PromptRunOut,
    PromptUpdate,
)
from sm_images.web.services import prompts as service
from sm_images.web.services.viewer_stats import viewer_only

router = APIRouter(tags=["prompts"])
Principal = Annotated[ResourcePrincipal, Depends(resource_principal)]


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


def _owner_or_manager(who: ResourcePrincipal, collection: Collection, what: str) -> None:
    # Delete is never granted by a share, so the in-memory ``can`` is exact.
    if not POLICY.can(who, ACTION_DELETE, collection):
        raise Forbidden(f"only the owner or a manager can {what}")


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
    body: PromptCreate, collection: CollectionEdit, who: Principal, db=Depends(get_db)
) -> PromptOut:
    if body.auto_run:
        _owner_or_manager(who, collection, "switch auto-run on")
    return _out(await service.create(db, collection, body))


@router.get("/prompts/{prompt_id}", dependencies=[require_view])
async def get_prompt(
    prompt_id: uuid.UUID, collection: PromptCollectionView, db=Depends(get_db)
) -> PromptOut:
    return _out(await service.get(db, collection, prompt_id))


@router.patch("/prompts/{prompt_id}", dependencies=[require_view])
async def patch_prompt(
    prompt_id: uuid.UUID,
    body: PromptUpdate,
    collection: PromptCollectionEdit,
    who: Principal,
    db=Depends(get_db),
) -> PromptOut:
    row = await service.get(db, collection, prompt_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("auto_run") is True and not row.auto_run:
        _owner_or_manager(who, collection, "switch auto-run on")
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
    who: Principal,
    db=Depends(get_db),
    limit: int = Query(constants.PAGE_DEFAULT, ge=1, le=constants.PAGE_MAX),
    after: int | None = Query(None, ge=0),
) -> PromptResultPageOut:
    row = await service.get(db, collection, prompt_id)
    gate = collection if await viewer_only(db, who, collection) else None
    found, cursor = await service.results_page(db, row, limit=limit, after=after, gate=gate)
    return PromptResultPageOut(items=[_result(r, row.revision) for r in found], next_cursor=cursor)


@router.post("/prompts/{prompt_id}/run", status_code=202, dependencies=[require_view])
async def run_prompt(
    prompt_id: uuid.UUID,
    body: PromptRunIn,
    collection: PromptCollectionEdit,
    who: Principal,
    db=Depends(get_db),
) -> PromptRunOut:
    """Request the prompt's run on the collection's images or groups
    (``scope``), or on ``image_ids``/``group_ids`` of it, and dispatch them; a
    whole collection may be queued."""
    row = await service.get(db, collection, prompt_id)
    group = row.scope is PromptScope.GROUP
    if (body.image_ids if group else body.group_ids) is not None:
        raise Invalid(
            "an image prompt runs on image_ids, a group prompt on group_ids",
            code=codes.CODE_INVALID_RUN_TARGET,
        )
    named = body.group_ids if group else body.image_ids
    # A manager's run re-checks their right in the worker; a named list (an
    # editor may run one) is handled inside this request.
    starter: dict[str, str | None] = {"run_as": None, "access_basis": None}
    if named is None or body.scope == "all":
        _owner_or_manager(who, collection, "run a prompt on the whole collection or on everything")
        starter = {"run_as": who.user_id, "access_basis": owner_or_manage_basis(who, collection)}
    if not ai.ai_available():
        raise ServiceUnavailable("the ai module is not installed", code=codes.CODE_AI_UNAVAILABLE)
    await db.rollback()  # read-only so far: release it before the per-item transactions
    requested = await runs.launch(
        runtime(),
        tenant(),
        prompt_id,
        body.scope,
        body.image_ids,
        body.group_ids,
        **starter,
    )
    return PromptRunOut(scope=body.scope, requested=requested)
