"""The public counts behind the ``ImageStats`` pagebuilder block (#88).

Only what the anonymous gallery already shows: ``images`` and ``located`` count
the rows :func:`~sm_images.web.services.public_gallery.visible` lets through,
each collection under its own redaction gate, never the stored
``Collection.image_count`` (which includes images withheld from the public).
``collections`` counts the public ones. Trash and tenant are filtered by the
models' mixins; the caller has bound the tenant (``bind_public``) and, for a
single collection, established that it is public (``access.public_collection``).

**Bounded**, because the route is anonymous and a cache miss is anyone's to
cause. Every answer is ``(value, capped)``:

* a count reads at most :data:`MAX_COUNT` ``+ 1`` rows and is
  ``(MAX_COUNT, True)`` past it - the records stats' shape;
* the all-collections total is **one** count over every public collection's
  images, not one per collection. A collection's redaction gate is decided in
  Python (its pipeline against the installed step registry,
  :func:`~sm_images.core.access.redaction.ready_clause`), so it cannot be read
  off the joined ``Collection`` row in SQL; instead the public collections are
  grouped by :func:`~sm_images.core.access.redaction.gate_key` and the
  statement ORs one ``collection_id IN (...) AND <gate>`` term per distinct
  gate - usually one or two, however many collections there are. Deciding the
  gates still reads the collections, so at most :data:`MAX_COLLECTIONS` are
  considered; past that the total is ``(None, True)``, because a partial sum is
  not the total. One named collection is never refused.
"""

from __future__ import annotations

from typing import Any, Final, Literal

from sqlalchemy import JSON, Select, func, or_, select
from sqlalchemy.orm import aliased

from sm_images.core.access import redaction
from sm_images.models import Collection, Image, Visibility
from sm_images.web.services.public_gallery import gate, visible, visible_where

__all__ = ["MAX_COLLECTIONS", "MAX_COUNT", "METRICS", "Metric", "public_stat"]

Metric = Literal["images", "located", "collections"]
METRICS: Final[frozenset[str]] = frozenset({"images", "located", "collections"})

MAX_COUNT: Final = 10_000
"""Where a count stops: the block shows "10,000+" past it. A stats band has
no use for an exact figure beyond five digits, and the bound keeps a count's
cost independent of how many images the tenant holds."""

MAX_COLLECTIONS: Final = 200
"""How many public collections the all-collections total considers. Each one's
pipeline is read and its gate decided in Python, so this bounds that work; a
site with more public collections than this counts per collection instead."""

Answer = tuple[int | None, bool]


def _columns(model: Any) -> list[Any]:
    """Every mapped column but the JSON ones, for a bounded count's subquery.

    The outer count runs over ``aliased(model, <limited subquery>)`` so the
    statement still names the mapper the framework's tenant and trash criteria
    attach to; they are rendered against the alias, so the subquery must
    expose every column a criterion may name (only ``id`` would let one fall
    back to the base table: a cross join). JSON is left out as the bulk of a row.
    """
    return [getattr(model, c.key) for c in model.__table__.columns if not isinstance(c.type, JSON)]


async def _bounded(db: Any, model: Any, inner: Select[Any]) -> Answer:
    counted = aliased(model, inner.limit(MAX_COUNT + 1).subquery())
    total = int(
        (await db.execute(select(func.count(counted.id)).select_from(counted))).scalar_one()
    )
    return (MAX_COUNT, True) if total > MAX_COUNT else (total, False)


def _images(metric: Metric) -> Select[Any]:
    stmt = select(*_columns(Image))
    return stmt.where(Image.lat.is_not(None)) if metric == "located" else stmt


def _public() -> Select[Any]:
    return select(Collection).where(Collection.visibility == Visibility.PUBLIC)


async def _total(db: Any, metric: Metric) -> Answer:
    stmt = _public().order_by(Collection.id).limit(MAX_COLLECTIONS + 1)
    collections = list((await db.execute(stmt)).scalars())
    if len(collections) > MAX_COLLECTIONS:
        return None, True
    by_gate: dict[str, list[Collection]] = {}
    for coll in collections:
        by_gate.setdefault(redaction.gate_key(coll), []).append(coll)
    if not by_gate:
        return 0, False
    # One representative decides the gate for its group: equal keys place the
    # same images (``gate_key``'s contract), so its clause is every member's.
    where = or_(*[gate([c.id for c in group], group[0]) for group in by_gate.values()])
    return await _bounded(db, Image, visible_where(_images(metric), where))


async def public_stat(db: Any, *, metric: Metric, collection: Collection | None) -> Answer:
    """``(value, capped)`` for *metric* over *collection*, or over every public
    collection without one. ``collections`` ignores *collection*."""
    if metric == "collections":
        return await _bounded(db, Collection, _public().with_only_columns(*_columns(Collection)))
    if collection is None:
        return await _total(db, metric)
    return await _bounded(db, Image, visible(_images(metric), collection))
