"""``/api/images/presets`` and applying a preset to a collection (spec §8.1).

The list is deployment-wide - what the installed plugins registered - so it
needs only ``images.view`` and names no collection. Applying one is the
owner's or a manager's (``CollectionOwner``): it can switch ``auto_run`` on,
which spends AI requests on every new image (:mod:`sm_images.services.presets`).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from simple_module_db.deps import get_db

from sm_images.access import CollectionOwner
from sm_images.deps import require_view
from sm_images.schemas.prompt import PromptOut
from sm_images.services import presets as service

router = APIRouter(tags=["presets"])


class ApplyPresetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset_id: str = Field(min_length=1, max_length=100)


class ApplyPresetOut(BaseModel):
    preset_id: str
    created: list[PromptOut]
    """The prompts this application made; empty when it was applied before."""


@router.get("/presets", dependencies=[require_view])
async def list_presets() -> dict[str, list[dict[str, Any]]]:
    return {"items": [service.preset_out(p) for p in service.list_presets()]}


@router.post("/collections/{collection_id}/apply-preset", dependencies=[require_view])
async def apply_preset(
    body: ApplyPresetIn, collection: CollectionOwner, db=Depends(get_db)
) -> ApplyPresetOut:
    created = await service.apply_preset(db, collection, body.preset_id)
    return ApplyPresetOut(
        preset_id=body.preset_id,
        created=[PromptOut.model_validate(p, from_attributes=True) for p in created],
    )
