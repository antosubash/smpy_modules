"""The purge's storage half: delete the keys group by group, shared keys last.

A key can belong to more than one group of a pass - two selected images
pointing at one object, or an upload session's staged key that is also its
image's original. Such a **shared** key is deleted only after every one of its
owners has cleared its own keys: if one of them fails and is kept, it still
has its bytes. In order:

1. each image's unshared keys (one batch; on failure, image by image);
2. each whole collection's unshared keys (its map, import staging), for the
   collections none of whose images failed;
3. the shared keys whose owners all cleared; one that fails keeps its owners.

After :data:`FAILURE_LIMIT` failures a pass stops trying (storage is down);
what it did not try is kept but not recorded as failed.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sm_images.jobs.purge_select import Keys

__all__ = ["FAILURE_LIMIT", "Cleared", "delete_keys"]

logger = logging.getLogger(__name__)

FAILURE_LIMIT = 20
"""Storage failures after which one pass stops trying (the rest wait)."""

Owner = tuple[str, uuid.UUID]
"""``("image", id)`` or ``("collection", id)``."""


@dataclass
class Cleared:
    failed: set[Owner] = field(default_factory=set)
    """Owners a delete failed for: kept and recorded."""
    untried: set[Owner] = field(default_factory=set)
    """Owners not tried after the failure limit: kept, not recorded."""
    deleted: set[str] = field(default_factory=set)

    def kept(self) -> set[Owner]:
        return self.failed | self.untried


async def _groups(store: Any, groups: dict[Owner, set[str]], out: Cleared) -> None:
    keys = sorted(set().union(*groups.values())) if groups else []
    if not keys:
        return
    try:
        await store.delete_keys(keys)
        out.deleted.update(keys)
        return
    except Exception:
        logger.warning("images.purge.batch_delete_failed n=%d", len(keys), exc_info=True)
    for owner, group in groups.items():
        if not group:
            continue
        if len(out.failed) >= FAILURE_LIMIT:
            out.untried.add(owner)
            continue
        try:
            await store.delete_keys(sorted(group))
            out.deleted.update(group)
        except Exception:
            logger.warning("images.purge.object_delete_failed owner=%s", owner, exc_info=True)
            out.failed.add(owner)


async def _shared(store: Any, shared: dict[str, set[Owner]], out: Cleared) -> None:
    for key in sorted(shared):
        owners = shared[key]
        if owners & out.kept():
            continue  # an owner is kept: so is the object it still points at
        if len(out.failed) >= FAILURE_LIMIT:
            out.untried |= owners
            continue
        try:
            await store.delete_keys([key])
            out.deleted.add(key)
        except Exception:
            logger.warning("images.purge.shared_delete_failed key=%s", key, exc_info=True)
            out.failed |= owners


async def delete_keys(
    store: Any, keys: Keys, collection_of: dict[uuid.UUID, uuid.UUID], whole: set[uuid.UUID]
) -> Cleared:
    """Delete what may go; ``whole`` is narrowed to the collections that can.
    ``collection_of`` maps each selected image to its collection."""
    owners: dict[str, set[Owner]] = {}
    groups: dict[Owner, set[str]] = {}
    for kind, by_id in (("image", keys.images), ("collection", keys.collections)):
        for ident, group in by_id.items():
            groups[(kind, ident)] = group
            for key in group:
                owners.setdefault(key, set()).add((kind, ident))
    shared = {k: o for k, o in owners.items() if len(o) > 1}
    out = Cleared()

    def narrow() -> None:
        for kind, ident in out.kept():
            whole.discard(collection_of[ident] if kind == "image" else ident)

    await _groups(store, {o: g - shared.keys() for o, g in groups.items() if o[0] == "image"}, out)
    narrow()
    mine = {("collection", c): groups[("collection", c)] - shared.keys() for c in whole}
    await _groups(store, mine, out)
    narrow()
    # A shared key may also belong to a collection that is not going (a lock,
    # an upload that would not abort): that owner is kept too.
    for ident in keys.collections:
        if ident not in whole:
            out.untried.add(("collection", ident))
    await _shared(store, shared, out)
    narrow()
    return out
