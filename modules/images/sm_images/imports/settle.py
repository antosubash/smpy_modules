"""Settling one import item: its image, its status and the job's counters commit
together, or not at all.

:func:`settle_bytes` is shared by base64 imports (inline, by the runner) and
URL imports (``download``): ``IngestService.add_image(source="import")`` - the
sniff, the decode guards, the dedupe and the object write - then, **in the
same transaction**,

* the item's compare-and-set out of ``pending`` (:func:`mark_item`), which for
  a download also requires the claim token it holds, and
* the counter increment, **fenced** on the job being ``running`` in the
  settler's generation (``jobs.bump``).

If either fails - a redelivered message, a download whose claim was taken
over, a job paused, restarted or reclaimed meanwhile - the transaction rolls
back, so the image row vanishes, and the object it wrote is deleted (or, if
that fails, left behind its intent for the janitor).

An ``ImagesError`` from ingest or the base64 decoder (not an image, too large,
too many pixels, bad base64) is the item's permanent failure, with its code.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from collections.abc import Sequence
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import update

from sm_images import constants
from sm_images.errors import ImagesError
from sm_images.imports import jobs
from sm_images.imports.chunk import pending_items
from sm_images.imports.features import Parsed
from sm_images.ingest import Duplicate, IngestMeta, IngestService
from sm_images.ingest.b64 import decode_base64
from sm_images.models import Collection, Image, ImportItem
from sm_images.models.enums import ItemStatus, LocationSource
from sm_images.pipeline.runtime import Runtime

__all__ = ["fail_item", "ingest_chunk", "ingest_item", "item_meta", "mark_item", "settle_bytes"]

logger = logging.getLogger(__name__)


def item_meta(
    item: ImportItem | Parsed, *, located_by: LocationSource = LocationSource.IMPORT_
) -> IngestMeta:
    """``located_by``: where the item's coordinates came from - a feed's
    properties (``import``), or a person's ``metadata.json`` (``manual``)."""
    return IngestMeta(
        lat=item.lat,
        lng=item.lng,
        captured_at=item.captured_at,
        external_source=item.external_source,
        external_id=item.external_id,
        group_key=item.group_key,
        group_role=item.group_role,
        properties=item.properties,
        location_source=located_by,
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
    token: str | None = None,
) -> bool:
    """Move a ``pending`` item (held by ``token``, when given) to ``status``;
    ``False`` if it is not pending, or not this claim's, any more."""
    values: dict[str, Any] = {
        "status": status,
        "updated_at": jobs.now(),
        "claim_token": None,
        "claim_expires_at": None,
        "claim_generation": None,
        "next_attempt_at": None,
    }
    if image_id is not None:
        values["image_id"] = image_id
    if error is not None:
        values["last_error"] = error[:2000]
    if attempts:
        values["attempts"] = ImportItem.attempts + attempts
    conds = [
        ImportItem.id == item_id,
        ImportItem.tenant_id == tenant,
        ImportItem.status == ItemStatus.PENDING,
    ]
    if token is not None:
        conds.append(ImportItem.claim_token == token)
    stmt = (
        update(ImportItem)
        .where(*conds)
        .values(**values)
        .returning(ImportItem.id)
        .execution_options(**jobs.SYNC)
    )
    return (await db.execute(stmt)).first() is not None


async def ingest_item(
    ingest: IngestService,
    collection: Collection,
    *,
    data: bytes,
    filename: str | None,
    meta,
    auto_run: bool = False,
) -> Image | Duplicate:
    """The one ingest call (a seam for the replay tests)."""
    return await ingest.add_image(
        collection,
        data=data,
        filename=filename,
        meta=meta,
        source=constants.SOURCE_IMPORT,
        auto_run=auto_run,
    )


async def fail_item(
    runtime: Runtime,
    tenant: str,
    job_id: uuid.UUID,
    generation: int,
    item_id: int,
    code: str,
    *,
    attempts: int = 1,
    token: str | None = None,
) -> bool:
    async with runtime.session_factory() as db:
        moved = await mark_item(
            db, tenant, item_id, ItemStatus.FAILED, error=code, attempts=attempts, token=token
        )
        if moved and not await jobs.bump(db, tenant, job_id, {ItemStatus.FAILED: 1}, generation):
            await db.rollback()
            return False
        await finalize_session(db)
    return moved


async def _discard(runtime: Runtime, created: Image | None) -> None:
    """Its row rolled back: nothing references the object (best effort; the
    intent written before the object stays for the janitor otherwise)."""
    if created is not None:
        with contextlib.suppress(Exception):
            await runtime.store().delete_keys([created.storage_key])


async def settle_bytes(
    runtime: Runtime,
    tenant: str,
    job_id: uuid.UUID,
    generation: int,
    collection: Collection,
    item_id: int,
    data: bytes,
    *,
    filename: str | None,
    meta: IngestMeta,
    auto_run: bool,
    attempts: int = 1,
    token: str | None = None,
) -> ItemStatus | None:
    """Ingest ``data`` as item ``item_id``; its final status, or ``None`` when it
    lost (settled elsewhere, claim lost, job moved on) and nothing was kept.
    ``auto_run`` is the job's ``auto_run_prompts``, read once per job."""
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
            outcome = await ingest_item(
                ingest, collection, data=data, filename=filename, meta=meta, auto_run=auto_run
            )
        except ImagesError as exc:
            await db.rollback()
            code = exc.code or "rejected"
            failed = await fail_item(
                runtime, tenant, job_id, generation, item_id, code, attempts=attempts, token=token
            )
            return ItemStatus.FAILED if failed else None
        if isinstance(outcome, Duplicate):
            status, image_id = ItemStatus.DUPLICATE, outcome.image_id
        else:
            status, image_id, created = ItemStatus.DONE, outcome.id, outcome
        kept = await mark_item(
            db, tenant, item_id, status, image_id=image_id, attempts=attempts, token=token
        )
        if kept:
            kept = await jobs.bump(db, tenant, job_id, {status: 1}, generation)
        if not kept:
            await db.rollback()
            await _discard(runtime, created)
            return None
        await finalize_session(db)
    return status


async def ingest_chunk(
    runtime: Runtime,
    tenant: str,
    job: jobs.JobSnap,
    collection: Collection,
    parsed: Sequence[Parsed],
) -> int:
    """Base64 mode: settle the chunk's items still waiting for an image - from
    the payloads parsed out of the source, or as failed when the feature itself
    is unusable (a replay after retry-failed must settle them, not skip them).
    Returns how many were settled."""
    if not parsed:
        return 0
    by_index = {p.index: p for p in parsed}
    max_bytes = runtime.settings().max_image_bytes
    settled = 0
    first, last = parsed[0].index, parsed[-1].index
    for item_id, index in await pending_items(runtime, tenant, job.id, first, last):
        p = by_index.get(index)
        if p is None:
            continue
        if p.error is not None or p.payload is None:
            code = p.error or "missing_image"
            settled += await fail_item(runtime, tenant, job.id, job.generation, item_id, code)
            continue
        try:
            data = decode_base64(p.payload, max_bytes)
        except ImagesError as refused:
            code = refused.code or "invalid_base64"
            settled += await fail_item(runtime, tenant, job.id, job.generation, item_id, code)
            continue
        finally:
            p.payload = None  # release the encoded text as soon as it is decoded
        outcome = await settle_bytes(
            runtime,
            tenant,
            job.id,
            job.generation,
            collection,
            item_id,
            data,
            filename=p.filename,
            meta=item_meta(p),
            auto_run=job.auto_run_prompts,
        )
        settled += outcome is not None
    return settled
