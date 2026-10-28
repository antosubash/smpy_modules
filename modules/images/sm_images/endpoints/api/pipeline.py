"""``/api/images/collections/{id}/pipeline`` and ``/api/images/images/{id}/reprocess``.

Reading the pipeline is a ``view`` on the collection; saving it and restarting
the whole collection are owner or ``images.manage`` (``CollectionOwner``);
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
from simple_module_db.listeners import current_tenant_id
from simple_module_hosting.resource_deps import resource_principal

from sm_images.access import POLICY, CollectionOwner, CollectionView, ImageCollectionEdit
from sm_images.deps import require_view
from sm_images.errors import Forbidden, Invalid, ServiceUnavailable
from sm_images.pipeline import control
from sm_images.pipeline.config import PipelineConfigError, validate_pipeline_config
from sm_images.pipeline.runtime import Runtime, current_runtime
from sm_images.schemas.pipeline import PipelineConfigIn, ReprocessIn, RestartIn
from sm_images.services import gallery

router = APIRouter(tags=["pipeline"])

Principal = Annotated[ResourcePrincipal, Depends(resource_principal)]
CODE_INVALID_CONFIG = "invalid_pipeline_config"


def _runtime() -> Runtime:
    runtime = current_runtime()
    if runtime is None:
        raise ServiceUnavailable("the image pipeline is not running in this process")
    return runtime


def _tenant() -> str:
    tenant = current_tenant_id.get()
    if tenant is None:  # bind_admin ran first; this is the executor's own guard
        raise ServiceUnavailable("no tenant is bound")
    return tenant


@router.get("/collections/{collection_id}/pipeline", dependencies=[require_view])
async def get_pipeline(collection: CollectionView, db=Depends(get_db)) -> dict[str, Any]:
    return await control.overview(db, collection)


@router.put("/collections/{collection_id}/pipeline", dependencies=[require_view])
async def put_pipeline(
    body: PipelineConfigIn, collection: CollectionOwner, db=Depends(get_db)
) -> dict[str, Any]:
    """Save the config after a **strict** validation: params, the shape, one
    display mutator, and the dependency graph (an enabled step whose
    ``requires`` is off or unregistered, or a cycle, is a 422)."""
    config = {"steps": body.steps}
    try:
        validate_pipeline_config(config, strict=True)
    except PipelineConfigError as exc:
        err = Invalid(str(exc)[:1000])
        err.code = CODE_INVALID_CONFIG
        raise err from exc
    collection.pipeline_config = config
    await db.flush()
    return await control.overview(db, collection)


@router.post(
    "/collections/{collection_id}/pipeline/restart", status_code=202, dependencies=[require_view]
)
async def restart_pipeline(body: RestartIn, collection: CollectionOwner) -> dict[str, str]:
    await control.launch_restart(_runtime(), _tenant(), collection.id, body.scope)
    return {"status": "accepted", "scope": body.scope}


@router.post("/images/{image_id}/reprocess", status_code=202, dependencies=[require_view])
async def reprocess_image(
    image_id: uuid.UUID,
    body: ReprocessIn,
    collection: ImageCollectionEdit,
    who: Principal,
    db=Depends(get_db),
) -> dict[str, Any]:
    if body.force and not POLICY.can(who, ACTION_DELETE, collection):
        raise Forbidden("only the owner or a manager can force a full re-run")
    image = await gallery.get(db, collection, image_id)
    steps = await control.reprocess(_runtime(), _tenant(), image.id, force=body.force)
    return {"status": "accepted", "reset": steps}
