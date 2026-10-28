"""Images as the console shows them: the row plus the URLs that fetch its bytes."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select

from sm_images import constants, urls
from sm_images.models import Collection, Image, Rendition
from sm_images.schemas.image import ImageOut

__all__ = ["present", "present_one"]


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
