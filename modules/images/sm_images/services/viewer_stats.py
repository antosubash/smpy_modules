"""Collection counts and box as a *viewer* may see them.

``Collection.image_count``/``located_count``/``bbox_*`` cover every live image,
including ones whose picture is withheld until redaction settles. Handing those
to someone who may only view the collection leaks that such an image exists and
where it is, so a viewer's numbers are recomputed here over the display-safe
images (``redaction.ready_clause``), the same set the map and the gallery show.
An editor (owner, edit share, ``images.manage``) sees the raw stored numbers.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from simple_module_core.resources import ACTION_EDIT, ResourcePrincipal
from sqlalchemy import func, select

from sm_images import redaction
from sm_images.access import POLICY
from sm_images.contracts.schemas import collection_fields
from sm_images.models import Collection, Image
from sm_images.schemas.collection import CollectionOut

__all__ = ["collection_outs", "public_fields", "viewer_fields"]


async def _gated(db: Any, collection: Collection) -> dict[str, Any]:
    stmt = select(
        func.count(Image.id),
        func.count(Image.lat),
        func.min(Image.lng),
        func.min(Image.lat),
        func.max(Image.lng),
        func.max(Image.lat),
    ).where(
        Image.collection_id == collection.id,
        Image.is_deleted.is_(False),
        redaction.ready_clause(collection),
    )
    total, located, *corners = (await db.execute(stmt)).one()
    return {
        "image_count": int(total),
        "located_count": int(located),
        "bbox": None if None in corners else [float(c) for c in corners],
    }


async def public_fields(db: Any, collection: Collection) -> dict[str, Any]:
    """The anonymous page's view: always the gated numbers."""
    return {**collection_fields(collection), **await _gated(db, collection)}


async def _editable(db: Any, who: ResourcePrincipal, rows: Sequence[Collection]) -> set[Any]:
    if not rows:
        return set()
    stmt = POLICY.filter(
        who, ACTION_EDIT, select(Collection.id).where(Collection.id.in_([r.id for r in rows]))
    )
    return set((await db.execute(stmt)).scalars())


async def viewer_fields(
    db: Any, who: ResourcePrincipal, rows: Sequence[Collection]
) -> list[dict[str, Any]]:
    """``collection_fields`` of each row, gated for the rows *who* cannot edit."""
    editable = await _editable(db, who, rows)
    return [
        collection_fields(r)
        if r.id in editable
        else {**collection_fields(r), **await _gated(db, r)}
        for r in rows
    ]


async def collection_outs(
    db: Any, who: ResourcePrincipal, rows: Sequence[Collection]
) -> list[CollectionOut]:
    fields = await viewer_fields(db, who, rows)
    return [
        CollectionOut(**f, is_owner=who.user_id == r.owner_id)
        for f, r in zip(fields, rows, strict=True)
    ]
