"""A public collection's gallery for the anonymous page and the pagebuilder block.

Only what a visitor may see: an image that is not trashed, whose picture may be
shown (:func:`sm_images.core.access.redaction.ready_clause`, the map's gate) and that has a
``small`` rendition cut from its current display copy - so every tile this
returns is a URL the anonymous twin will answer. Items carry the id, the pixel
size and two URLs; no filename, metadata or location. The caller has already
established that the collection is public (``access.public_collection``).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, select

from sm_images.core import constants
from sm_images.core.access import redaction
from sm_images.models import Collection, Image, Rendition
from sm_images.web.services import cursor as cursors
from sm_images.web.serving import urls

__all__ = ["page", "visible"]


def visible(stmt: Select[Any], collection: Collection) -> Select[Any]:
    """*stmt* narrowed to the images of *collection* the gallery lists, joined to
    each one's current ``small`` rendition: not trashed, passing the redaction
    gate, and cut from the current display copy. One row per image (a rendition
    is unique per image and size). The gallery and the public counts
    (:mod:`~sm_images.web.services.public_stats`) both go through here."""
    return stmt.join(
        Rendition,
        (Rendition.image_id == Image.id)
        & (Rendition.size == constants.THUMB_SIZE)
        & (Rendition.source_generation == Image.display_generation),
    ).where(
        Image.collection_id == collection.id,
        Image.is_deleted.is_(False),
        redaction.ready_clause(collection),
    )


async def page(
    db: Any,
    collection: Collection,
    *,
    limit: int = constants.PAGE_DEFAULT,
    cursor: str | None = None,
) -> dict[str, Any]:
    limit = max(1, min(int(limit), constants.PAGE_MAX))
    stmt = visible(select(Image, Rendition), collection)
    if cursor:
        stmt = stmt.where(cursors.seek(Image.created_at, Image.id, cursor))
    stmt = stmt.order_by(Image.created_at.desc(), Image.id.desc()).limit(limit + 1)
    rows, token = cursors.cut(list((await db.execute(stmt)).all()), limit, last=lambda row: row[0])
    return {
        "items": [
            {
                "id": str(image.id),
                "width": image.width,
                "height": image.height,
                "thumb_url": urls.public_rendition_url(collection, image, cut),
                "display_url": urls.public_display_url(collection, image),
            }
            for image, cut in rows
        ],
        "next_cursor": token,
    }
