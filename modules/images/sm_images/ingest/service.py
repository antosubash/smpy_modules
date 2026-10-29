"""``IngestService.add_image``: the one way an image enters a collection.

Every path calls it - multipart batch, base64, direct upload, and later the
GeoJSON, ZIP and download imports - so dedupe, the object write and the row
are decided once:

1. inspect (size cap, magic-byte sniff, pixel guard) and hash;
2. dedupe: the external-id pre-check, this service's in-batch set, and the
   content hash when ``dedupe_by_hash`` is on;
3. write the original under a recorded intent (or adopt a staged key);
4-7. in one savepoint: insert the image, its pending ``StepRun`` rows for the
   collection's enabled steps, the collection stats, and clear the intent. A
   unique-index loss to a concurrent duplicate re-checks identity and answers
   :class:`Duplicate`;
8. after the commit: ``ImageAdded``, ``pipeline.dispatch`` and
   ``pipeline.queue_auto_run`` (the collection's ``auto_run`` prompts; an
   import passes its job's ``auto_run_prompts`` as ``auto_run``).

**The intent ordering rule (Task 5).** An intent commits through its own
session, so it must be written before the caller's session first writes:
on file-backed SQLite the caller then holds the writer lock and the intent
waits on it. A caller adding several images in one transaction calls
:meth:`IngestService.reserve` for all of them first and passes each
:class:`Slot` in. The storage hold (``sm_images.billing``) follows the same
rule, so ``reserve(..., sizes=)`` takes it there too; it is committed with
the row's commit, or released after it when nothing kept it.

The savepoint is also the per-file isolation of a batch: a file that fails
rolls back its own rows only, and its object is deleted again.
"""

from __future__ import annotations

import contextlib
import hashlib
import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy.exc import IntegrityError

from sm_images import billing, events, pipeline, storage_keys
from sm_images.errors import StorageQuotaExceeded
from sm_images.ingest import dedupe
from sm_images.ingest import slots as holds
from sm_images.ingest.guards import Inspected, inspect
from sm_images.ingest.meta import IngestMeta, normalise
from sm_images.ingest.slots import Duplicate, Slot, safe_filename
from sm_images.intents import clear_intents, object_intent
from sm_images.models import Collection, Image, StepRun
from sm_images.services import stats
from sm_images.storage import ImageStore
from sm_images.tenancy import bound_tenant

__all__ = ["Duplicate", "IngestService", "Slot", "safe_filename"]


class IngestService:
    def __init__(
        self,
        db: Any,
        store: ImageStore,
        settings: Any,
        *,
        bus: Any = None,
        intent_factory: Any = None,
    ) -> None:
        self.db = db
        self.store = store
        self.settings = settings
        self.bus = bus
        self.intent_factory = intent_factory
        self._seen_external: dict[tuple[uuid.UUID, str, str], uuid.UUID] = {}
        self._seen_hash: dict[tuple[uuid.UUID, str], uuid.UUID] = {}

    # -- intents ---------------------------------------------------------

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
        factory = self._factory()
        return [
            await holds.hold_slot(factory, tenant, s, n) for s, n in zip(slots, sizes, strict=True)
        ]

    def _factory(self) -> Any:
        """Where billing's own short transactions run (``sm_images.billing``)."""
        return billing.factory_of(self.db, self.intent_factory)

    def inspect(self, data: bytes) -> Inspected:
        return inspect(data, max_bytes=self.settings.max_image_bytes)

    # -- the one entry point ---------------------------------------------

    async def add_image(
        self,
        collection: Collection,
        *,
        data: bytes | None = None,
        staged_key: str | None = None,
        image_id: uuid.UUID | None = None,
        slot: Slot | None = None,
        filename: str | None,
        meta: IngestMeta,
        source: str,
        inspected: Inspected | None = None,
        auto_run: bool = True,
    ) -> Image | Duplicate:
        """Add one image; ``data`` *or* ``staged_key`` (+ its ``image_id``).

        A staged object is adopted at its key, never copied. It is deleted only
        on a pre-insert duplicate, and only while no row owns ``image_id``. After
        an insert failure it is never touched: the key may be a concurrent
        winner's committed original (two ``complete`` calls for one upload), so
        the row is re-read by id and returned, or the object and its intent are
        left for the janitor. A refusal (``ImagesError``) raised before the
        insert leaves a staged object for the caller to remove.
        """
        if (data is None) == (staged_key is None):
            raise TypeError("pass exactly one of data= or staged_key=")
        if staged_key is not None and image_id is None:
            raise TypeError("a staged key needs the image_id it was minted for")
        if staged_key is not None:
            data = await self.store.read(staged_key)
        assert data is not None
        info = inspected or self.inspect(data)
        sha = hashlib.sha256(data).hexdigest()
        meta = normalise(meta, source)

        found = await self._precheck(collection.id, meta, sha)
        if found is not None:
            if staged_key is None or not await dedupe.find_id(self.db, image_id):
                await self._discard(staged_key, slot)
            await holds.drop_slot(self.db, self._factory(), slot)
            return Duplicate(found)

        if staged_key is not None:
            assert image_id is not None
            key, new_id = staged_key, image_id
            slot = await holds.hold_slot(
                self._factory(), bound_tenant(), Slot(new_id, key), len(data)
            )
            if slot.refused:  # the caller removes its staged object
                raise StorageQuotaExceeded(billing.FULL)
        else:
            slot = slot or (await self.reserve(collection, [info.ext], [len(data)]))[0]
            key, new_id = slot.key, slot.image_id
            if slot.refused:
                await self._discard(None, slot)
                raise StorageQuotaExceeded(billing.FULL)
            await self.store.put(key, data, content_type=info.content_type, size=len(data))

        row = Image(
            id=new_id,
            collection_id=collection.id,
            storage_key=key,
            storage_bytes=len(data),
            storage_hold_id=slot.hold,
            filename=safe_filename(filename),
            content_type=info.content_type,
            size_bytes=len(data),
            width=info.width,
            height=info.height,
            sha256=sha,
            lat=meta.lat,
            lng=meta.lng,
            location_source=meta.location_source if meta.located else None,
            captured_at=meta.captured_at,
            external_source=meta.external_source,
            external_id=meta.external_id,
            properties=meta.properties,
            group_role=meta.group_role,
        )
        try:
            await self._insert(collection, row, meta, key)
        except IntegrityError:
            if staged_key is not None:
                if await dedupe.find_id(self.db, new_id):
                    return Duplicate(new_id)  # a concurrent complete won; its object stays
                again = await self._recheck(collection.id, meta)
                if again is None:
                    raise
                return Duplicate(again)  # the staged object is left to the janitor
            again = await self._recheck(collection.id, meta)
            if again is None:
                await self._delete_object(key)
                raise
            await self._discard(key, None)
            return Duplicate(again)
        except Exception:
            if staged_key is None:
                await self._delete_object(key)
            raise
        self._remember(collection.id, meta, sha, row.id)
        events.emit(self.db, self.bus, events.image_added(row, source))
        pipeline.dispatch(self.db, row.id)
        await pipeline.queue_auto_run(self.db, collection, row.id, enabled=auto_run)
        return row

    # -- steps -------------------------------------------------------------

    async def _precheck(self, collection_id: uuid.UUID, meta: IngestMeta, sha: str):
        if meta.external_id is not None:
            assert meta.external_source is not None
            ident = (collection_id, meta.external_source, meta.external_id)
            if ident in self._seen_external:
                return self._seen_external[ident]
            found = await dedupe.find_external(self.db, *ident)
            if found is not None:
                return found
        if self.settings.dedupe_by_hash:
            if (collection_id, sha) in self._seen_hash:
                return self._seen_hash[(collection_id, sha)]
            return await dedupe.find_hash(self.db, collection_id, sha)
        return None

    async def _recheck(self, collection_id: uuid.UUID, meta: IngestMeta) -> uuid.UUID | None:
        if meta.external_id is None or meta.external_source is None:
            return None
        return await dedupe.find_external(
            self.db, collection_id, meta.external_source, meta.external_id
        )

    async def _insert(self, collection: Collection, row: Image, meta: IngestMeta, key: str) -> None:
        try:
            await self._insert_rows(collection, row, meta, key)
        except Exception:  # released outside the rolled-back savepoint
            await holds.drop_hold(self.db, self._factory(), row.id, row.storage_hold_id)
            raise

    async def _insert_rows(self, collection: Collection, row: Image, meta, key: str) -> None:
        async with self.db.begin_nested():
            if meta.group_key is not None:
                row.group_id = await dedupe.ensure_group(self.db, collection.id, meta.group_key)
            self.db.add(row)
            await self.db.flush()
            for step in pipeline.enabled_steps(collection.pipeline_config):
                self.db.add(StepRun(image_id=row.id, step=step))
            await self.db.flush()
            await stats.on_image_added(self.db, collection.id, row.lat, row.lng)
            await clear_intents(self.db, [key])
            await holds.keep_hold(  # rolled back with the savepoint
                self.db, self._factory(), row.id, row.storage_hold_id, row.storage_bytes
            )

    def _remember(self, collection_id: uuid.UUID, meta: IngestMeta, sha: str, image_id) -> None:
        if meta.external_id is not None and meta.external_source is not None:
            self._seen_external[(collection_id, meta.external_source, meta.external_id)] = image_id
        self._seen_hash[(collection_id, sha)] = image_id

    async def _delete_object(self, key: str) -> None:
        """Best effort: if it fails, the intent (still recorded) lets the janitor reap it."""
        with contextlib.suppress(Exception):
            await self.store.delete_keys([key])

    async def _discard(self, staged_key: str | None, slot: Slot | None) -> None:
        """Nothing will reference these keys: drop the object, then the intent."""
        keys = [k for k in (staged_key, slot.key if slot else None) if k is not None]
        if not keys:
            return
        try:
            await self.store.delete_keys(keys)
        except Exception:  # the intent stays, and the janitor retries
            return
        await clear_intents(self.db, keys)
