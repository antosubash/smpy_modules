"""Images as the console shows them: the row plus the URLs that fetch its bytes."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from simple_module_core.resources import ResourcePrincipal
from sqlalchemy import select

from sm_images import access, constants, urls
from sm_images.models import Collection, Group, Image, Rendition, StepRun
from sm_images.schemas.image import ImageOut, StepRunOut

__all__ = ["present", "present_detail", "present_one"]


async def present(db: Any, collection: Collection, images: Sequence[Image]) -> list[ImageOut]:
    """One query for the page's ``small`` renditions. A rendition cut from an
    older display copy is not offered: the route would 404 it."""
    if not images:
        return []
    stmt = select(Rendition).where(
        Rendition.image_id.in_([i.id for i in images]), Rendition.size == constants.THUMB_SIZE
    )
    cuts = {r.image_id: r for r in (await db.execute(stmt)).scalars()}
    out = []
    for image in images:
        cut = cuts.get(image.id)
        current = cut is not None and cut.source_generation == image.display_generation
        thumb = urls.rendition_url(image, cut, collection=collection) if current else None
        out.append(
            ImageOut.from_row(
                image,
                thumb_url=thumb,
                display_url=urls.display_url(image, collection=collection),
            )
        )
    return out


async def present_one(db: Any, collection: Collection, image: Image) -> ImageOut:
    return (await present(db, collection, [image]))[0]


async def present_detail(
    db: Any, collection: Collection, image: Image, who: ResourcePrincipal
) -> ImageOut:
    """``present_one`` plus the image's step runs, for the viewer's result views.

    Output (region coordinates, extracted text) and error messages (internals)
    are for those who can edit the collection; a viewer gets the step, its
    status and its error code only."""
    out = await present_one(db, collection, image)
    detailed = await access.can_edit(db, who, collection)
    stmt = select(StepRun).where(StepRun.image_id == image.id).order_by(StepRun.step)
    if image.group_id is not None:
        key = select(Group.key).where(
            Group.id == image.group_id, Group.collection_id == collection.id
        )
        out.group_key = (await db.execute(key)).scalar_one_or_none()
    out.step_runs = [
        StepRunOut(
            step=r.step,
            status=r.status.value,
            error_code=r.error_code,
            step_version=r.step_version if detailed else None,
            error_message=r.error_message if detailed else None,
            finished_at=r.finished_at if detailed else None,
            output=r.output if detailed else None,
            output_visible=detailed,
        )
        for r in (await db.execute(stmt)).scalars()
    ]
    return out
