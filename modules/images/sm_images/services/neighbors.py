"""The image before and after one in its collection's gallery order.

The gallery lists newest first (``created_at`` then ``id``, both descending:
``services.gallery.list_page``), so ``prev`` is the next newer image and
``next`` the next older one. ``gated`` (a viewer who cannot edit) skips every
image the viewer may not open (``redaction.ready_clause``), so a withheld image
is never offered - nor revealed - as a neighbour.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, tuple_

from sm_images.access import redaction
from sm_images.models import Collection, Image

__all__ = ["neighbors", "side_statements"]


def _side(collection: Collection, cond: Any, order: Any, gated: bool) -> Any:
    stmt = select(Image.id).where(Image.collection_id == collection.id, cond)
    if gated:
        stmt = stmt.where(redaction.ready_clause(collection))
    return stmt.order_by(*order).limit(1)


def side_statements(collection: Collection, image: Image, *, gated: bool) -> tuple[Any, Any]:
    """``(prev, next)``: one ``LIMIT 1`` query each."""
    # Row values, not an OR of the halves: each side is one seek of the
    # (collection_id, created_at, id) gallery index (``ix_images_image_gallery``).
    key, here = tuple_(Image.created_at, Image.id), tuple_(image.created_at, image.id)
    newer, older = key > here, key < here
    return (
        _side(collection, newer, (Image.created_at, Image.id), gated),
        _side(collection, older, (Image.created_at.desc(), Image.id.desc()), gated),
    )


async def neighbors(
    db: Any, collection: Collection, image: Image, *, gated: bool
) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name, stmt in zip(
        ("prev", "next"), side_statements(collection, image, gated=gated), strict=True
    ):
        found = (await db.execute(stmt)).scalar_one_or_none()
        out[name] = None if found is None else str(found)
    return out
