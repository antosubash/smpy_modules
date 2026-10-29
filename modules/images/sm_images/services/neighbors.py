"""The image before and after one in its collection's gallery order.

The gallery lists newest first (``created_at`` then ``id``, both descending:
``services.gallery.list_page``), so ``prev`` is the next newer image and
``next`` the next older one. ``gated`` (a viewer who cannot edit) skips every
image the viewer may not open (``redaction.ready_clause``), so a withheld image
is never offered - nor revealed - as a neighbour.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, or_, select

from sm_images import redaction
from sm_images.models import Collection, Image

__all__ = ["neighbors"]


async def _one(db: Any, collection: Collection, cond: Any, order: Any, gated: bool) -> str | None:
    stmt = select(Image.id).where(Image.collection_id == collection.id, cond)
    if gated:
        stmt = stmt.where(redaction.ready_clause(collection))
    found = (await db.execute(stmt.order_by(*order).limit(1))).scalar_one_or_none()
    return None if found is None else str(found)


async def neighbors(
    db: Any, collection: Collection, image: Image, *, gated: bool
) -> dict[str, str | None]:
    at, iid = image.created_at, image.id
    newer = or_(Image.created_at > at, and_(Image.created_at == at, Image.id > iid))
    older = or_(Image.created_at < at, and_(Image.created_at == at, Image.id < iid))
    return {
        "prev": await _one(db, collection, newer, (Image.created_at, Image.id), gated),
        "next": await _one(
            db, collection, older, (Image.created_at.desc(), Image.id.desc()), gated
        ),
    }
