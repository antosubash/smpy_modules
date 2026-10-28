"""Direct (multipart) uploads for files over ``direct_upload_threshold``.

The parts go through ``file_storage``'s ``DirectUploadBackend``: presigned URLs
straight to storage on S3, or, on a backend that cannot presign (filesystem),
``PUT /api/images/uploads/{id}/parts/{n}`` relayed through this app.

**State is a table, the handle is a token.** The upload is staged straight at
the image's final ``original_key`` (no copy on completion), and that key's
write-ahead intent is recorded when the upload starts - so an abandoned upload
is an orphan the janitor already knows about. ``start`` also records an
``images_upload_session`` row (``ingest.upload_session``), and that row is
authoritative: ``complete`` and ``abort`` each claim it by compare-and-set
before touching storage, so an abort can never delete an object a complete
has validated and is inserting (it gets 409 ``upload_in_progress``), and a
complete after an abort is a 404. The ``upload_id`` the client gets back is a
token signed with the host's ``secret_key`` (``itsdangerous``, the library
behind the framework's session cookie), valid for
``DIRECT_UPLOAD_TTL_SECONDS``, naming the session and carrying what the part
relay needs. A tampered, expired, foreign-tenant or other user's token is a
404 like an unknown one. The backend's own part listing is the truth about
what arrived, as in ``file_storage``'s own sessions; the database never
mirrors it.

Replay is safe: once the image row exists, ``complete`` answers with it again,
and nothing here deletes a key a row references.

**The token is signed, not encrypted.** Anyone holding it can read the key,
ids and size inside (base64 JSON); only forging or altering it is prevented.
It appears in the relay part URLs and so in access logs; it grants nothing
without the owner's session, an ``edit`` on the collection and a bound tenant.

The declared type is binding: ``start`` refuses one that maps to no accepted
image type (415), and ``complete`` refuses (415, object deleted) when the
sniffed bytes are another type - so the key's extension, the row's
``content_type`` and the object agree.
"""

from __future__ import annotations

import uuid
from typing import Any

from file_storage.contracts.service import StorageError
from sqlalchemy import select

from sm_images import constants, storage_keys
from sm_images.errors import (
    FileTooLarge,
    ImagesError,
    PartsMismatch,
    UnsupportedType,
    UploadNotFound,
)
from sm_images.ingest import upload_session as state
from sm_images.ingest.meta import IngestMeta
from sm_images.ingest.multipart import assemble as _assemble
from sm_images.ingest.multipart import backend_of, open_upload, write_part
from sm_images.ingest.service import Duplicate, IngestService
from sm_images.ingest.sniff import EXTENSIONS, sniff
from sm_images.ingest.ticket import (
    _BAD_TYPE,
    _GONE,
    Ticket,
    declared_type,
    load_ticket,
    serializer,
)
from sm_images.models import Collection, Image, UploadStatus
from sm_images.tenancy import bound_tenant

__all__ = [
    "Ticket",
    "abort",
    "complete",
    "load_ticket",
    "start",
    "write_part",
]

_TOO_LARGE = "The upload is larger than the image size limit"
_SIZE_MISMATCH = "The stored upload is not the declared size"


async def start(
    db: Any,
    store: Any,
    collection: Collection,
    *,
    filename: str,
    size: int,
    content_type: str | None,
    max_bytes: int,
    owner: str,
    secret: str,
    intent_factory: Any = None,
) -> tuple[str, Ticket, list[str], bool]:
    """``(upload_id, ticket, part_urls, direct)``. The key's extension is the
    declared type, which ``complete`` then holds the bytes to."""
    if size > max_bytes:
        raise FileTooLarge(_TOO_LARGE)
    # Refuse in the order a client can act on: no direct uploads here (503),
    # no secret to sign with (503), then the declared type (415).
    backend_of(store)
    serializer(secret)
    declared = declared_type(filename, content_type)
    image_id = uuid.uuid4()
    key = storage_keys.original_key(
        bound_tenant(), str(collection.id), str(image_id), EXTENSIONS[declared]
    )
    return await open_upload(
        db,
        store,
        collection,
        key=key,
        image_id=image_id,
        size=size,
        content_type=declared,
        filename=filename,
        owner=owner,
        secret=secret,
        intent_factory=intent_factory,
    )


async def _existing(db: Any, ticket: Ticket) -> Image | None:
    stmt = select(Image).where(Image.id == uuid.UUID(ticket.image))
    return (await db.execute(stmt.execution_options(include_deleted=True))).scalars().first()


async def complete(
    ingest: IngestService,
    collection: Collection,
    ticket: Ticket,
    *,
    claimed: dict[int, str | None],
    filename: str | None,
    meta: IngestMeta,
) -> Image | Duplicate:
    """Claim the session, assemble, re-check the *stored* object (the declared
    size was only a claim) and ingest it in place; ``completed`` commits with
    the row. A failure hands the claim back (``state.settle``)."""
    existing = await _existing(ingest.db, ticket)
    if existing is not None:
        return existing
    token = await state.claim_complete(ingest.db, ticket)
    if token is None:
        existing = await _existing(ingest.db, ticket)
        if existing is None:
            raise UploadNotFound(_GONE)
        return existing
    assembled = False
    try:
        try:
            await _assemble(ingest.store, ticket, claimed)
        except StorageError as exc:
            raise UploadNotFound(_GONE) from exc
        assembled = True
        await state.renew(ingest.db, ticket, token)  # each phase is bounded by the lease
        outcome = await _ingest(ingest, collection, ticket, token, filename=filename, meta=meta)
    except Exception:
        handed_back = UploadStatus.ABORTED if assembled else UploadStatus.OPEN
        await state.settle(ingest.db, ticket, token, handed_back)
        raise
    await state.finish(ingest.db, ticket, token)
    return outcome


async def _ingest(
    ingest: IngestService,
    collection: Collection,
    ticket: Ticket,
    token: uuid.UUID,
    *,
    filename: str | None,
    meta: IngestMeta,
) -> Image | Duplicate:
    head = await ingest.store.head(ticket.key)
    if head is None:
        raise UploadNotFound(_GONE)
    if head[0] != ticket.size:
        await _drop(ingest, ticket)
        raise PartsMismatch(_SIZE_MISMATCH)
    if head[0] > ingest.settings.max_image_bytes:
        await _drop(ingest, ticket)
        raise FileTooLarge(_TOO_LARGE)
    first = b"".join([c async for c in await ingest.store.stream_range(ticket.key, 0, 31)])
    if sniff(first) != ticket.content_type:
        await _drop(ingest, ticket)
        raise UnsupportedType(_BAD_TYPE)
    await state.renew(ingest.db, ticket, token)
    try:
        return await ingest.add_image(
            collection,
            staged_key=ticket.key,
            image_id=uuid.UUID(ticket.image),
            filename=filename or ticket.filename,
            meta=meta,
            source=constants.SOURCE_UPLOAD,
        )
    except ImagesError:
        await _drop(ingest, ticket)
        raise


async def _drop(ingest: IngestService, ticket: Ticket) -> None:
    """Delete the staged object - unless a row (a concurrent winner) owns it."""
    if await _existing(ingest.db, ticket) is None:
        await ingest.store.delete_keys([ticket.key])


async def abort(db: Any, store: Any, ticket: Ticket) -> None:
    """Claim the session ``aborted``, then discard the parts and the staged
    object (never one a row owns), then record ``cleaned_at``; a cleanup that
    fails leaves it NULL for the reaper to retry. A completed upload is left
    alone; one a complete is still working on is 409 ``upload_in_progress``."""
    if not await state.claim_abort(db, ticket):
        return
    backend_of(store)  # 503 on a backend without multipart uploads
    await state.discard(db, store, ticket.key, ticket.upload, uuid.UUID(ticket.image))
    await state.mark_cleaned(db, uuid.UUID(ticket.session))
