"""The public counts behind the ``ImageStats`` pagebuilder block (#88).

Only what the anonymous gallery already shows: ``images`` and ``located`` count
the rows :func:`~sm_images.web.services.public_gallery.visible` lets through,
each collection under its own redaction gate, never the stored
``Collection.image_count`` (which includes images withheld from the public).
``collections`` counts the public ones. Trash and tenant are filtered by the
models' mixins; the caller has bound the tenant (``bind_public``) and, for a
single collection, established that it is public (``access.public_collection``).
"""

from __future__ import annotations

from typing import Any, Final, Literal

from sqlalchemy import func, select

from sm_images.models import Collection, Image, Visibility
from sm_images.web.services.public_gallery import visible

__all__ = ["METRICS", "Metric", "public_stat"]

Metric = Literal["images", "located", "collections"]
METRICS: Final[frozenset[str]] = frozenset({"images", "located", "collections"})


async def _public_collections(db: Any) -> list[Collection]:
    stmt = select(Collection).where(Collection.visibility == Visibility.PUBLIC)
    return list((await db.execute(stmt)).scalars())


async def _count(db: Any, metric: Metric, collection: Collection) -> int:
    column = Image.lat if metric == "located" else Image.id
    stmt = visible(select(func.count(column)).select_from(Image), collection)
    return int((await db.execute(stmt)).scalar_one())


async def public_stat(db: Any, *, metric: Metric, collection: Collection | None) -> int:
    """*metric* over *collection*, or over every public collection without one.
    ``collections`` ignores *collection*."""
    if metric == "collections":
        stmt = select(func.count(Collection.id)).where(Collection.visibility == Visibility.PUBLIC)
        return int((await db.execute(stmt)).scalar_one())
    targets = [collection] if collection is not None else await _public_collections(db)
    return sum([await _count(db, metric, c) for c in targets])
