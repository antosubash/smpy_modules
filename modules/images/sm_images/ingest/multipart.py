"""The multipart mechanics behind every direct upload - an image's
(``ingest.direct``) and an import's ZIP (``imports.zip_upload``).

:func:`open_upload` records the key's intent, opens the backend's multipart
upload and the ``open`` session row, and signs the ticket; :func:`write_part`
relays one part while the session is ``open``; :func:`assemble` completes the
backend upload from the parts it holds, each the expected size (and claimed
etag). What a completed upload *becomes* is the caller's business.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any

from file_storage.contracts.service import NotSupportedError, StorageError, StorageNotFoundError

from sm_images import constants
from sm_images.errors import DirectUploadUnsupported, InvalidUpload, PartsMismatch, UploadNotFound
from sm_images.ingest import upload_session as state
from sm_images.ingest.service import safe_filename
from sm_images.ingest.ticket import _BAD_PART, _GONE, Ticket, serializer
from sm_images.intents import object_intent
from sm_images.models import Collection
from sm_images.tenancy import bound_tenant

__all__ = ["assemble", "backend_of", "open_upload", "write_part"]

_NO_DIRECT = "This storage backend does not support direct uploads"


def backend_of(store: Any) -> Any:
    backend = store.backend
    if not getattr(backend, "supports_direct_upload", False):
        raise DirectUploadUnsupported(_NO_DIRECT)
    return backend


async def open_upload(
    db: Any,
    store: Any,
    collection: Collection,
    *,
    key: str,
    image_id: uuid.UUID,
    size: int,
    content_type: str,
    filename: str,
    owner: str,
    secret: str,
    kind: str = "image",
    intent_factory: Any = None,
) -> tuple[str, Ticket, list[str], bool]:
    """The multipart upload behind every direct upload (an image, an import's
    ZIP): the key's intent, the backend upload, the ``open`` session row (in
    ``db``'s transaction) and the signed ticket with its part URLs."""
    backend = backend_of(store)
    signer = serializer(secret)
    async with object_intent([key], session_factory=intent_factory):
        upload = await backend.create_multipart(key, content_type)
    ticket = Ticket(
        session=str(uuid.uuid4()),
        key=key,
        upload=upload,
        collection=str(collection.id),
        image=str(image_id),
        tenant=bound_tenant(),
        owner=owner,
        size=size,
        part_size=constants.DIRECT_PART_BYTES,
        filename=safe_filename(filename),
        content_type=content_type,
        kind=kind,
    )
    db.add(state.new_session(ticket, collection.id))
    await db.flush()
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


async def write_part(
    db: Any, store: Any, ticket: Ticket, no: int, body: AsyncIterator[bytes]
) -> Any:
    """Relay one part (backends that cannot presign), only while the session is
    ``open`` (``state.require_open``). Exactly the expected size."""
    limit = ticket.part_bytes(no)
    await state.require_open(db, ticket)
    try:
        part = await backend_of(store).write_part(
            ticket.key, ticket.upload, no, body, max_bytes=limit
        )
    except StorageNotFoundError as exc:
        raise UploadNotFound(_GONE) from exc
    except StorageError as exc:
        raise InvalidUpload(_BAD_PART, constants.CODE_PARTS_MISMATCH) from exc
    if part.size != limit:
        raise InvalidUpload(_BAD_PART, constants.CODE_PARTS_MISMATCH)
    return part


async def assemble(store: Any, ticket: Ticket, claimed: dict[int, str | None]) -> list[Any]:
    """Complete the backend's multipart upload from the parts it holds - each
    the expected size (and, when the client claimed one, its etag); the parts."""
    backend = backend_of(store)
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
    parts = [held[n] for n in wanted]
    await backend.complete_multipart(ticket.key, ticket.upload, parts)
    return parts
