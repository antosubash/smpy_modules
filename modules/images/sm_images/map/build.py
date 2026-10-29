"""One fenced map build: snapshot, convert, upload, publish (the portal's three phases).

No database connection is held through tippecanoe or the upload:

1. **Snapshot** - a short session checks that generation ``gen`` is still the
   collection's (else the message is stale: nothing to do), extends the claim
   for the build's timeout and reads ``map_changes`` *before* any point, so a
   change landing mid-build stays pending and triggers the next build. The
   points (:func:`sm_images.map.points.located`) are then streamed to NDJSON
   in keyset chunks, each in its own short session.
2. **Convert and upload** - tippecanoe (:mod:`~sm_images.map.pmtiles_build`),
   then the archive goes to storage under a write-ahead intent at a key no
   other build uses (``storage_keys.map_key``: generation plus a nonce).
3. **Publish** - one conditional ``UPDATE ... WHERE map_generation = gen``
   names the archive, stamped with the redaction gate the snapshot used
   (``redaction.gate_key``; serving refuses it under any other). A newer
   request or a withdrawal (``map.revoke``) moved the generation on: nothing
   is published and the upload is deleted. Published, the previous archive is
   deleted after the commit.

An empty snapshot publishes "no map" (``map_key`` cleared), which also drops
the previous archive. A failed or impossible build (no tippecanoe) keeps the
current map and cools the claim down (``schedule.FAILED_COOLDOWN``).
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from simple_module_db import finalize_session
from sqlalchemy import select, update

from sm_images import constants, redaction, storage_keys
from sm_images.constants import NO_SYNC
from sm_images.intents import add_intents, clear_intents, object_intent
from sm_images.map import pmtiles_build
from sm_images.map.objects import drop_objects
from sm_images.map.points import located
from sm_images.map.schedule import FAILED_COOLDOWN, request_if_due
from sm_images.models import Collection, Image
from sm_images.pipeline.runtime import Runtime

__all__ = ["FAILED", "PUBLISHED", "SUPERSEDED", "UNAVAILABLE", "build_map_async"]

logger = logging.getLogger(__name__)

PUBLISHED: Final = "published"
SUPERSEDED: Final = "superseded"
UNAVAILABLE: Final = "unavailable"
FAILED: Final = "failed"
CHUNK: Final = 5000
UPLOAD_MARGIN: Final = timedelta(minutes=10)
_READ_BYTES: Final = 1024 * 1024


@dataclass(frozen=True)
class Snapshot:
    changes: int
    count: int
    taken_at: datetime
    policy: str
    """The redaction gate the points were selected under (``redaction.gate_key``)."""


def _ours(collection_id: uuid.UUID, gen: int) -> tuple[Any, ...]:
    return (Collection.id == collection_id, Collection.map_generation == gen)


async def _cool_down(runtime: Runtime, collection_id: uuid.UUID, gen: int) -> None:
    async with runtime.session_factory() as db:
        await db.execute(
            update(Collection)
            .where(*_ours(collection_id, gen))
            .values(map_claimed_until=datetime.now(UTC) + FAILED_COOLDOWN)
            .execution_options(**NO_SYNC)
        )
        await finalize_session(db)


async def _snapshot(
    runtime: Runtime, collection_id: uuid.UUID, gen: int, out: Path
) -> Snapshot | None:
    taken_at = datetime.now(UTC)
    async with runtime.session_factory() as db:
        coll = (await db.execute(select(Collection).where(*_ours(collection_id, gen)))).scalar()
        if coll is None:  # superseded, trashed or gone
            await db.rollback()
            return None
        changes, stmt = coll.map_changes, located(coll)  # the gate, as configured now
        policy = redaction.gate_key(coll)
        budget = timedelta(seconds=pmtiles_build.timeout_for(coll.located_count)) + UPLOAD_MARGIN
        await db.execute(
            update(Collection)
            .where(*_ours(collection_id, gen))
            .values(map_claimed_until=taken_at + budget)
            .execution_options(**NO_SYNC)
        )
        await finalize_session(db)
    count, after = 0, None
    with out.open("w", encoding="utf-8") as fh:
        while True:
            chunk = stmt.order_by(Image.id).limit(CHUNK)
            if after is not None:
                chunk = chunk.where(Image.id > after)
            async with runtime.session_factory() as db:
                rows = list((await db.execute(chunk)).all())
                await db.rollback()
            count += pmtiles_build.write_features(fh, rows)
            if len(rows) < CHUNK:
                return Snapshot(changes, count, taken_at, policy)
            after = rows[-1][0]


async def _chunks(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as fh:
        while data := await asyncio.to_thread(fh.read, _READ_BYTES):
            yield data


async def _upload(runtime: Runtime, key: str, path: Path) -> None:
    async with object_intent([key], session_factory=runtime.session_factory):
        await runtime.store().put(
            key,
            _chunks(path),
            content_type=constants.PMTILES_CONTENT_TYPE,
            size=path.stat().st_size,
        )


async def _publish(
    runtime: Runtime, collection_id: uuid.UUID, gen: int, key: str | None, snap: Snapshot
) -> tuple[bool, str | None]:
    """``(published, previous key)``: the compare-and-set on the generation."""
    async with runtime.session_factory() as db:
        lock = select(Collection.map_key).where(*_ours(collection_id, gen))
        found = (await db.execute(lock.with_for_update(key_share=True))).first()
        if found is None:
            await db.rollback()
            return False, None
        old = found[0]
        await db.execute(
            update(Collection)
            .where(*_ours(collection_id, gen))
            .values(
                map_key=key,
                map_built_at=snap.taken_at,
                map_image_count=snap.count,
                map_built_changes=snap.changes,
                map_policy_rev=snap.policy,
                map_claimed_until=None,
            )
            .execution_options(**NO_SYNC)
        )
        if key:
            await clear_intents(db, [key])
        if old and old != key:
            await add_intents(db, [old])
        await finalize_session(db)
    return True, old if old != key else None


async def _again(runtime: Runtime, tenant: str, collection_id: uuid.UUID) -> None:
    """Changes that landed during the build may already be due again."""
    async with runtime.session_factory() as db:
        await request_if_due(db, runtime, tenant, collection_id)
        await finalize_session(db)


async def _convert_and_upload(
    runtime: Runtime,
    binary: str,
    tenant: str,
    collection_id: uuid.UUID,
    gen: int,
    src: Path,
    count: int,
) -> str:
    out = src.with_suffix(".pmtiles")
    await asyncio.to_thread(pmtiles_build.convert, binary, src, out, count)
    key = storage_keys.map_key(tenant, str(collection_id), gen, uuid.uuid4().hex)
    await _upload(runtime, key, out)
    return key


async def build_map_async(runtime: Runtime, tenant: str, collection_id: uuid.UUID, gen: int) -> str:
    """Build generation ``gen`` of the collection's map; returns the outcome."""
    binary = pmtiles_build.locate(runtime.settings().tippecanoe_path)
    with tempfile.TemporaryDirectory(prefix="sm_images_map_") as tmp:
        src = Path(tmp) / "points.ndjson"
        snap = await _snapshot(runtime, collection_id, gen, src)
        if snap is None:
            return SUPERSEDED
        key = None
        if snap.count:
            if binary is None:
                logger.warning("images.map.tippecanoe_missing collection=%s", collection_id)
                await _cool_down(runtime, collection_id, gen)
                return UNAVAILABLE
            try:
                key = await _convert_and_upload(
                    runtime, binary, tenant, collection_id, gen, src, snap.count
                )
            except Exception:
                logger.exception("images.map.build_failed collection=%s", collection_id)
                await _cool_down(runtime, collection_id, gen)
                return FAILED
    published, old = await _publish(runtime, collection_id, gen, key, snap)
    if not published:
        await drop_objects(runtime, [key] if key else [])
        return SUPERSEDED
    await drop_objects(runtime, [old] if old else [])
    await _again(runtime, tenant, collection_id)
    return PUBLISHED
