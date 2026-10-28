"""Direct (multipart) uploads for files over ``direct_upload_threshold``.

The parts go through ``file_storage``'s ``DirectUploadBackend``: presigned URLs
straight to storage on S3, or, on a backend that cannot presign (filesystem),
``PUT /api/images/uploads/{id}/parts/{n}`` relayed through this app.

**No session table.** The upload is staged straight at the image's final
``original_key`` (no copy on completion), and that key's write-ahead intent is
recorded when the upload starts - so an abandoned upload is an orphan the
janitor already knows about. Everything else the later calls need (key,
backend upload id, collection, image id, tenant, owner, size, part size) is in
the ``upload_id`` the client gets back: a token signed with the host's
``secret_key`` (``itsdangerous``, the library behind the framework's session
cookie) and valid for ``DIRECT_UPLOAD_TTL_SECONDS``. A tampered, expired,
foreign-tenant or other user's token is a 404 like an unknown one. The backend's
own part listing is the truth about what arrived, as in ``file_storage``'s own
sessions; the database never mirrors it.

Replay is safe: once the image row exists, ``complete`` answers with it again,
and nothing here deletes a key a row references - including the winner's
original when two ``complete`` calls for one upload race (the loser re-reads the
row, see ``IngestService.add_image``).

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
from collections.abc import AsyncIterator
from dataclasses import asdict
from pathlib import PurePosixPath
from typing import Any

from file_storage.contracts.service import NotSupportedError, StorageError, StorageNotFoundError
from sqlalchemy import select

from sm_images import constants, storage_keys
from sm_images.errors import (
    DirectUploadUnsupported,
    FileTooLarge,
    ImagesError,
    InvalidUpload,
    PartsMismatch,
    UnsupportedType,
    UploadNotFound,
)
from sm_images.ingest.meta import IngestMeta
from sm_images.ingest.service import Duplicate, IngestService, safe_filename
from sm_images.ingest.sniff import EXTENSIONS, sniff
from sm_images.ingest.ticket import _BAD_PART, _GONE, Ticket, load_ticket, serializer
from sm_images.intents import object_intent
from sm_images.models import Collection, Image
from sm_images.tenancy import bound_tenant

__all__ = ["Ticket", "abort", "complete", "load_ticket", "start", "write_part"]

_NO_DIRECT = "This storage backend does not support direct uploads"
_TOO_LARGE = "The upload is larger than the image size limit"
_BAD_TYPE = "The upload is not a supported image of the declared type"
_SIZE_MISMATCH = "The stored upload is not the declared size"


def _backend(store: Any) -> Any:
    backend = store.backend
    if not getattr(backend, "supports_direct_upload", False):
        raise DirectUploadUnsupported(_NO_DIRECT)
    return backend


def _declared_type(filename: str, content_type: str | None) -> str:
    """The accepted type the client declared (content type, else extension); 415 if none."""
    if content_type in EXTENSIONS:
        return content_type
    suffix = PurePosixPath(filename).suffix.lower().lstrip(".")
    by_ext = {ext: ctype for ctype, ext in EXTENSIONS.items()}
    by_ext |= {"jpeg": "image/jpeg", "tiff": "image/tiff", "heif": "image/heif"}
    if content_type is None and suffix in by_ext:
        return by_ext[suffix]
    raise UnsupportedType(_BAD_TYPE)


async def start(
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
    backend = _backend(store)
    signer = serializer(secret)
    declared = _declared_type(filename, content_type)
    image_id = uuid.uuid4()
    tenant = bound_tenant()
    ext = EXTENSIONS[declared]
    key = storage_keys.original_key(tenant, str(collection.id), str(image_id), ext)
    async with object_intent([key], session_factory=intent_factory):
        upload = await backend.create_multipart(key, declared)
    ticket = Ticket(
        key=key,
        upload=upload,
        collection=str(collection.id),
        image=str(image_id),
        tenant=tenant,
        owner=owner,
        size=size,
        part_size=constants.DIRECT_PART_BYTES,
        filename=safe_filename(filename),
        content_type=declared,
    )
    token = signer.dumps(asdict(ticket))
    numbers = range(1, ticket.parts + 1)
    try:
        urls = [
            await backend.presign_part(
                key, upload, n, constants.DIRECT_PRESIGN_TTL_SECONDS, ticket.part_bytes(n)
            )
            for n in numbers
        ]
        return token, ticket, urls, True
    except NotSupportedError:
        relay = [constants.PART_PATH.format(upload_id=token, part_no=n) for n in numbers]
        return token, ticket, relay, False


async def write_part(store: Any, ticket: Ticket, no: int, body: AsyncIterator[bytes]) -> Any:
    """Relay one part (backends that cannot presign). Exactly the expected size."""
    limit = ticket.part_bytes(no)
    try:
        part = await _backend(store).write_part(
            ticket.key, ticket.upload, no, body, max_bytes=limit
        )
    except StorageNotFoundError as exc:
        raise UploadNotFound(_GONE) from exc
    except StorageError as exc:
        raise InvalidUpload(_BAD_PART, constants.CODE_PARTS_MISMATCH) from exc
    if part.size != limit:
        raise InvalidUpload(_BAD_PART, constants.CODE_PARTS_MISMATCH)
    return part


async def _existing(db: Any, ticket: Ticket) -> Image | None:
    stmt = select(Image).where(Image.id == uuid.UUID(ticket.image))
    return (await db.execute(stmt.execution_options(include_deleted=True))).scalars().first()


async def _assemble(store: Any, ticket: Ticket, claimed: dict[int, str | None]) -> None:
    backend = _backend(store)
    held = {p.no: p for p in await backend.list_parts(ticket.key, ticket.upload)}
    wanted = range(1, ticket.parts + 1)
    bad = [n for n in wanted if n not in held or held[n].size != ticket.part_bytes(n)]
    bad += [
        n
        for n, etag in claimed.items()
        if etag and n in held and held[n].etag.strip('"') != etag.strip('"')
    ]
    if bad or set(held) - set(wanted):
        raise PartsMismatch(_BAD_PART)
    await backend.complete_multipart(ticket.key, ticket.upload, [held[n] for n in wanted])


async def complete(
    ingest: IngestService,
    collection: Collection,
    ticket: Ticket,
    *,
    claimed: dict[int, str | None],
    filename: str | None,
    meta: IngestMeta,
) -> Image | Duplicate:
    """Assemble, then re-check the *stored* object (the declared size was only a
    claim) and ingest it in place."""
    existing = await _existing(ingest.db, ticket)
    if existing is not None:
        return existing
    try:
        await _assemble(ingest.store, ticket, claimed)
    except StorageError as exc:
        # A concurrent complete already assembled (and consumed) the parts.
        existing = await _existing(ingest.db, ticket)
        if existing is not None:
            return existing
        raise UploadNotFound(_GONE) from exc
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
    """Discard the parts, and the staged object unless a row already owns it."""
    await _backend(store).abort_multipart(ticket.key, ticket.upload)
    if await _existing(db, ticket) is None:
        await store.delete_keys([ticket.key])
