"""``/api/images/collections/{id}/pipeline`` and ``/api/images/images/{id}/reprocess``.

Reading the pipeline is an ``edit`` on the collection: its progress counts cover
every image, including ones whose redaction has not settled, so a viewer gets none.
Saving it and restarting the whole collection are owner or ``images.manage`` (``CollectionOwner``);
reprocessing one image is an ``edit`` - and ``force`` (re-run every step,
including the ones that completed) is the owner's or manager's only.

Restart and reprocess run through the executor's in-process helpers when the
runtime is eager (:mod:`sm_images.pipeline.control`), so they work from this
event loop; a broker-backed process queues the restart instead.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from simple_module_core.resources import ACTION_DELETE, ResourcePrincipal
from simple_module_db.deps import get_db
from simple_module_hosting.resource_deps import resource_principal

from sm_images import redaction
from sm_images.access import POLICY, CollectionEdit, CollectionOwner, ImageCollectionEdit
from sm_images.deps import require_view
from sm_images.endpoints.api._runtime import runtime, tenant
from sm_images.errors import Forbidden, Invalid
from sm_images.map import revoke as map_revoke
from sm_images.pipeline import control
from sm_images.pipeline.config import (
    PipelineConfigError,
    protect_originals,
    validate_pipeline_config,
)
from sm_images.schemas.pipeline import PipelineConfigIn, ReprocessIn, RestartIn
from sm_images.services import gallery

router = APIRouter(tags=["pipeline"])

Principal = Annotated[ResourcePrincipal, Depends(resource_principal)]
CODE_INVALID_CONFIG = "invalid_pipeline_config"


@router.get("/collections/{collection_id}/pipeline", dependencies=[require_view])
async def get_pipeline(collection: CollectionEdit, db=Depends(get_db)) -> dict[str, Any]:
    return await control.overview(db, collection)


@router.put("/collections/{collection_id}/pipeline", dependencies=[require_view])
async def put_pipeline(
    body: PipelineConfigIn, collection: CollectionOwner, db=Depends(get_db)
) -> dict[str, Any]:
    """Save the config after a **strict** validation: params, the shape, one
    display mutator, and the dependency graph (an enabled step whose
    ``requires`` is off or unregistered, or a cycle, is a 422)."""
    from sm_images.ai import prompt_steps

    config = {"steps": body.steps}
    prompts = await prompt_steps.resolve(db, collection.id, tenant=collection.tenant_id)
    try:
        parsed = validate_pipeline_config(config, strict=True, prompts=prompts)
    except PipelineConfigError as exc:
        err = Invalid(str(exc)[:1000])
        err.code = CODE_INVALID_CONFIG
        raise err from exc
    gate = redaction.gate_key(collection)
    collection.pipeline_config = config
    collection.protect_originals = protect_originals(collection.protect_originals, parsed)
    await db.flush()
    await map_revoke.gate_saved(db, collection, gate)  # another gate: the map goes now
    return await control.overview(db, collection)


@router.post(
    "/collections/{collection_id}/pipeline/restart", status_code=202, dependencies=[require_view]
)
async def restart_pipeline(body: RestartIn, collection: CollectionOwner) -> dict[str, str]:
    await control.launch_restart(runtime(), tenant(), collection.id, body.scope)
    return {"status": "accepted", "scope": body.scope}


@router.post("/images/{image_id}/reprocess", status_code=202, dependencies=[require_view])
async def reprocess_image(
    image_id: uuid.UUID,
    body: ReprocessIn,
    collection: ImageCollectionEdit,
    who: Principal,
    db=Depends(get_db),
) -> dict[str, Any]:
    # Delete is never granted by a share, so the in-memory ``can`` is exact.
    # Delete is never granted by a share, so the in-memory ``can`` is exact.
    if body.force and not POLICY.can(who, ACTION_DELETE, collection):
        raise Forbidden("only the owner or a manager can force a full re-run")
    image = await gallery.get(db, collection, image_id)
    steps = await control.reprocess(runtime(), tenant(), image.id, force=body.force)
    return {"status": "accepted", "reset": steps}
