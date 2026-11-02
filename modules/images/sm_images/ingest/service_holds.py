"""The storage-hold half of :class:`~sm_images.ingest.service.IngestService`.

Reserving slots (intent plus hold), handing holds back after a rollback and
finalizing the caller's transaction around them. The composing class supplies
``db``, ``intent_factory`` and ``acquired``; nothing else is read from it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sm_images.core import billing
from sm_images.core.storage import keys as storage_keys
from sm_images.core.storage.intents import object_intent
from sm_images.core.tenancy import bound_tenant
from sm_images.ingest import slots as holds
from sm_images.ingest._holds_host import HostBase
from sm_images.ingest.slots import Slot
from sm_images.models import Collection

__all__ = ["HoldsMixin"]


class HoldsMixin(HostBase):
    """Reads only what :class:`~sm_images.ingest._holds_host.HoldsHost` declares."""

    async def reserve(
        self, collection: Collection, exts: Iterable[str], sizes: Iterable[int] | None = None
    ) -> list[Slot]:
        """Mint ids and keys for originals and record their intents in one go;
        with ``sizes``, also reserve each original's storage hold (``slots``)."""
        tenant = bound_tenant()
        slots = []
        for ext in exts:
            image_id = uuid.uuid4()
            key = storage_keys.original_key(tenant, str(collection.id), str(image_id), ext)
            slots.append(Slot(image_id, key))
        async with object_intent([s.key for s in slots], session_factory=self.intent_factory):
            pass
        if sizes is None:
            return slots
        payer = await holds.slot_subject(self._factory(), tenant, collection)  # once, not per slot
        return [
            await self._hold(collection, s, n, payer) for s, n in zip(slots, sizes, strict=True)
        ]

    async def _hold(
        self, collection: Collection, slot: Slot, size: int, payer: str | None = None
    ) -> Slot:
        held = await holds.hold_slot(self._factory(), bound_tenant(), slot, size, collection, payer)
        self.acquired += [held.op] if held.op is not None else []
        return held

    async def release_holds(self) -> None:
        """After a rollback (no write lock held): hand every op taken back on its own."""
        await holds.release_after_rollback(self._factory(), self.acquired)

    async def finalize(self) -> None:
        """Finalize the caller's transaction; its holds follow the outcome
        (:func:`~sm_images.ingest.slots.finalize_or_release`)."""
        await holds.finalize_or_release(self.db, self._factory(), self.acquired)

    def _factory(self) -> Any:
        """Where billing's own short transactions run (``sm_images.core.billing``)."""
        return billing.factory_of(self.db, self.intent_factory)
