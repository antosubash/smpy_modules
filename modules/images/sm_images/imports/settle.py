"""Settling one import item: its image, its status and the job's counters commit
together, or not at all.

:func:`settle_bytes` is shared by base64 imports (inline, by the runner) and
URL imports (``download``): ``IngestService.add_image(source="import")`` - the
sniff, the decode guards, the dedupe and the object write - then, **in the
same transaction**, the item's compare-and-set out of ``pending``
(:func:`mark_item`) and the counter increment. A loser of that compare-and-set
(a redelivered message, a concurrent download of the same item) rolls back,
so its image row vanishes, and deletes the object it wrote.

An ``ImagesError`` from ingest (not an image, too large, too many pixels) is
the item's permanent failure, recorded with its code.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import logging
import uuid
from collections.abc import Sequence
from typing import Any, Final

from simple_module_db import finalize_session
from sqlalchemy import select, update

from sm_images.errors import ImagesError
from sm_images.imports import jobs
from sm_images.imports.chunk import SOURCE, pending_items
from sm_images.imports.features import Parsed
from sm_images.ingest import Duplicate, IngestMeta, IngestService
from sm_images.models import Collection, Image, ImportItem
from sm_images.models.enums import ItemStatus, LocationSource
from sm_images.pipeline.runtime import Runtime

__all__ = [
    "decode_base64",
    "fail_item",
    "ingest_chunk",
    "ingest_item",
    "item_meta",
    "mark_item",
    "settle_bytes",
]

logger = logging.getLogger(__name__)

_DATA_URI: Final = "data:"


class RefusedError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def decode_base64(text: str, max_bytes: int) -> bytes:
    """Raw or data-URI base64, at most ``max_bytes`` decoded; ``RefusedError`` otherwise."""
    text = text.strip()
    if text.startswith(_DATA_URI):
        _, _, text = text.partition(",")
    text = "".join(text.split())
    if len(text) // 4 * 3 > max_bytes + 3:
        raise RefusedError("file_too_large")
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RefusedError("invalid_base64") from exc
    if not data:
        raise RefusedError("invalid_base64")
    if len(data) > max_bytes:
        raise RefusedError("file_too_large")
    return data


def item_meta(item: ImportItem | Parsed) -> IngestMeta:
    return IngestMeta(
        lat=item.lat,
        lng=item.lng,
        captured_at=item.captured_at,
        external_id=item.external_id,
        group_key=item.group_key,
        group_role=item.group_role,
        properties=item.properties,
        location_source=LocationSource.IMPORT_,
    )


async def mark_item(
    db: Any,
    tenant: str,
    item_id: int,
    status: ItemStatus,
    *,
    image_id: uuid.UUID | None = None,
    error: str | None = None,
    attempts: int = 0,
) -> bool:
    """Move a ``pending`` item to ``status``; ``False`` if it is not pending (any more)."""
    values: dict[str, Any] = {"status": status, "updated_at": jobs.now()}
    if image_id is not None:
        values["image_id"] = image_id
    if error is not None:
        values["last_error"] = error[:2000]
    if attempts:
        values["attempts"] = ImportItem.attempts + attempts
    stmt = (
        update(ImportItem)
        .where(
            ImportItem.id == item_id,
            ImportItem.tenant_id == tenant,
            ImportItem.status == ItemStatus.PENDING,
        )
        .values(**values)
        .returning(ImportItem.id)
        .execution_options(synchronize_session=False)
    )
    return (await db.execute(stmt)).first() is not None


async def ingest_item(
    ingest: IngestService, collection: Collection, *, data: bytes, filename: str | None, meta
) -> Image | Duplicate:
    """The one ingest call (a seam for the replay tests)."""
    return await ingest.add_image(
        collection, data=data, filename=filename, meta=meta, source=SOURCE
    )


async def fail_item(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, item_id: int, code: str, *, attempts: int = 1
) -> bool:
    async with runtime.session_factory() as db:
        moved = await mark_item(
            db, tenant, item_id, ItemStatus.FAILED, error=code, attempts=attempts
        )
        if moved:
            await jobs.bump(db, tenant, job_id, {ItemStatus.FAILED: 1})
        await finalize_session(db)
    return moved


async def settle_bytes(
    runtime: Runtime,
    tenant: str,
    job_id: uuid.UUID,
    collection: Collection,
    item_id: int,
    data: bytes,
    *,
    filename: str | None,
    meta: IngestMeta,
    attempts: int = 1,
) -> ItemStatus | None:
    """Ingest ``data`` as item ``item_id``; its final status, or ``None`` when
    another delivery settled it first."""
    created: Image | None = None
    async with runtime.session_factory() as db:
        ingest = IngestService(
            db,
            runtime.store(),
            runtime.settings(),
            bus=runtime.bus(),
            intent_factory=runtime.session_factory,
        )
        try:
            outcome = await ingest_item(ingest, collection, data=data, filename=filename, meta=meta)
        except ImagesError as exc:
            await db.rollback()
            code = exc.code or "rejected"
            failed = await fail_item(runtime, tenant, job_id, item_id, code, attempts=attempts)
            return ItemStatus.FAILED if failed else None
        if isinstance(outcome, Duplicate):
            status, image_id = ItemStatus.DUPLICATE, outcome.image_id
        else:
            status, image_id, created = ItemStatus.DONE, outcome.id, outcome
        if not await mark_item(db, tenant, item_id, status, image_id=image_id, attempts=attempts):
            await db.rollback()
            if created is not None:  # its row rolled back: nothing references the object
                with contextlib.suppress(Exception):
                    await runtime.store().delete_keys([created.storage_key])
            return None
        await jobs.bump(db, tenant, job_id, {status: 1})
        await finalize_session(db)
    return status


async def ingest_chunk(
    runtime: Runtime,
    tenant: str,
    job: jobs.JobSnap,
    collection: Collection,
    parsed: Sequence[Parsed],
) -> int:
    """Base64 mode: ingest the chunk's items still waiting for an image, from
    the payloads parsed out of the source. Returns how many were settled."""
    if not parsed:
        return 0
    by_index = {p.index: p for p in parsed}
    max_bytes = runtime.settings().max_image_bytes
    settled = 0
    for item_id, index in await pending_items(
        runtime, tenant, job.id, parsed[0].index, parsed[-1].index
    ):
        p = by_index.get(index)
        if p is None or p.payload is None:
            continue
        try:
            data = decode_base64(p.payload, max_bytes)
        except RefusedError as refused:
            settled += await fail_item(runtime, tenant, job.id, item_id, refused.code)
            continue
        p.payload = None  # release the encoded text as soon as it is decoded
        outcome = await settle_bytes(
            runtime,
            tenant,
            job.id,
            collection,
            item_id,
            data,
            filename=p.filename,
            meta=item_meta(p),
        )
        settled += outcome is not None
    return settled


async def item_row(runtime: Runtime, tenant: str, item_id: int) -> ImportItem | None:
    async with runtime.session_factory() as db:
        stmt = select(ImportItem).where(ImportItem.id == item_id, ImportItem.tenant_id == tenant)
        row = (await db.execute(stmt)).scalar_one_or_none()
        await finalize_session(db)
    return row
