"""Staging a GeoJSON source in storage, and reading it back into a spool.

The source is stored under ``images/<tenant>/imports/<job>/source.geojson``
(``storage_keys.import_key``), behind a write-ahead intent (plan decision 4)
that the job's row clears when it records the key. Streaming always reads a
local **spool** - 8 MiB in memory, then a temporary file - never the storage
connection, which is released before hours of parsing.

* An uploaded file (:func:`put_upload`) is validated and counted first (a
  complete count is what catches a truncated body), then stored.
* A source URL (:func:`fetch_source`) goes through ``safe_stream`` - the SSRF
  guard, DNS pinning, redirects re-checked - capped at ``geojson_max_bytes``.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import IO, Any, Final

from file_storage.contracts.service import StorageNotFoundError

from sm_images import storage_keys
from sm_images.imports.fetch import safe_stream
from sm_images.imports.geojson_stream import GeoJSONError, validate_and_count
from sm_images.intents import object_intent
from sm_images.pipeline.runtime import Runtime

__all__ = [
    "SOURCE_NAME",
    "SOURCE_TIMEOUT_SECONDS",
    "SPOOL_MEMORY_BYTES",
    "count",
    "fetch_source",
    "open_source",
    "put_spool",
    "put_upload",
    "spool",
]

SOURCE_NAME: Final = "source.geojson"
SPOOL_MEMORY_BYTES: Final = 8 * 1024 * 1024
SOURCE_TIMEOUT_SECONDS: Final = 1800
"""Wall-clock budget of one source fetch (``safe_stream``'s absolute deadline)."""
HEARTBEAT_SECONDS: Final = 30.0
_CHUNK: Final = 1024 * 1024
_CONTENT_TYPE: Final = "application/geo+json"


def spool() -> IO[bytes]:
    return tempfile.SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES)


def _size(stream: IO[bytes]) -> int:
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    return size


async def _chunks(stream: IO[bytes]) -> AsyncIterator[bytes]:
    stream.seek(0)
    while chunk := stream.read(_CHUNK):
        yield chunk


async def count(stream: IO[bytes], max_features: int) -> int:
    """:func:`validate_and_count` off the event loop (it parses the whole file)."""
    return await asyncio.to_thread(validate_and_count, stream, max_features)


async def put_spool(runtime: Runtime, tenant: str, job_id: uuid.UUID, stream: IO[bytes]) -> str:
    """Store ``stream`` as the job's source behind an intent; returns its key.
    The caller clears the intent with the row that records the key."""
    key = storage_keys.import_key(tenant, str(job_id), SOURCE_NAME)
    async with object_intent([key], session_factory=runtime.session_factory):
        await runtime.store().put(
            key, _chunks(stream), content_type=_CONTENT_TYPE, size=_size(stream)
        )
    return key


async def put_upload(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, stream: IO[bytes], max_features: int
) -> tuple[str, int]:
    """Validate, count and store an uploaded source: ``(key, feature count)``."""
    total = await count(stream, max_features)
    return await put_spool(runtime, tenant, job_id, stream), total


async def fetch_source(
    url: str,
    *,
    max_bytes: int,
    beat: Callable[[], Awaitable[Any]] | None = None,
    timeout: float = SOURCE_TIMEOUT_SECONDS,
) -> IO[bytes]:
    """Download ``url`` into a spool through ``safe_stream``; ``beat`` is awaited
    every :data:`HEARTBEAT_SECONDS` while the body arrives."""
    out = spool()
    last = time.monotonic()
    try:
        async for chunk in safe_stream(url, max_bytes=max_bytes, timeout=timeout):
            out.write(chunk)
            if beat is not None and time.monotonic() - last > HEARTBEAT_SECONDS:
                await beat()
                last = time.monotonic()
    except BaseException:
        out.close()
        raise
    out.seek(0)
    return out


async def open_source(runtime: Runtime, key: str) -> IO[bytes]:
    """The staged source, copied into a spool. A missing object is permanent
    (``source_missing``); any other storage failure propagates (transient)."""
    out = spool()
    try:
        async for chunk in await runtime.store().stream(key):
            out.write(chunk)
    except StorageNotFoundError as exc:
        out.close()
        raise GeoJSONError("source_missing") from exc
    except BaseException:
        out.close()
        raise
    out.seek(0)
    return out
