"""Object access for images, over the framework's ``file_storage`` backend.

Bytes go straight to the backend under images' own key layout (``storage.keys``),
not through ``StoredFile`` rows or the file_storage quota (plan decision 5).

Two ways to get a store, because two kinds of process write objects:

* the web process: :func:`store_for` reads ``app.state.file_storage.backend``;
* a Celery worker, which never builds the app: :func:`worker_store` builds the
  backend from the DB-backed ``FileStorageSettings`` and caches it per process
  until those settings change.

Optional backend capabilities degrade rather than fail: without ``get_range``
the range is cut from a full stream; without ``head`` (``DirectUploadBackend``)
the size comes from ``exists`` plus reading the object once. The filesystem and
S3 backends both have ``head``, so the fallback only serves third-party ones.
"""

from __future__ import annotations

import os
import threading
from collections.abc import AsyncIterable, AsyncIterator, Iterable
from typing import Any

from file_storage.contracts.service import StorageNotFoundError

_CHUNK = 1024 * 1024


async def _one(data: bytes) -> AsyncIterator[bytes]:
    yield data


class ImageStore:
    def __init__(self, backend: Any) -> None:
        self.backend = backend

    async def put(
        self,
        key: str,
        data: bytes | AsyncIterable[bytes],
        *,
        content_type: str,
        size: int,
    ) -> None:
        stream = _one(data) if isinstance(data, bytes | bytearray | memoryview) else data
        await self.backend.put(key, stream, content_type=content_type, size=size)

    async def stream(self, key: str) -> AsyncIterator[bytes]:
        """Open the object; a missing key raises ``StorageNotFoundError`` here."""
        return await self.backend.get(key)

    async def read(self, key: str) -> bytes:
        """The whole object in memory. Only for bounded objects (images, not archives)."""
        return b"".join([chunk async for chunk in await self.stream(key)])

    async def stream_range(self, key: str, start: int, end: int) -> AsyncIterator[bytes]:
        """Bytes ``start`` through ``end`` inclusive (HTTP ``Range`` semantics)."""
        get_range = getattr(self.backend, "get_range", None)
        if get_range is not None:
            return await get_range(key, start, end)
        return _slice(await self.stream(key), start, end)

    async def exists(self, key: str) -> bool:
        return await self.backend.exists(key)

    async def head(self, key: str) -> tuple[int, str | None] | None:
        """``(size, etag)``, or ``None`` when absent."""
        head = getattr(self.backend, "head", None)
        if head is not None:
            try:
                info = await head(key)
            except StorageNotFoundError:
                return None
            return info.size, info.etag
        if not await self.backend.exists(key):
            return None
        try:
            size = sum([len(c) async for c in await self.backend.get(key)])
        except StorageNotFoundError:
            return None
        return size, None

    async def delete_keys(self, keys: Iterable[str]) -> int:
        """Delete each key; absent keys are fine. Returns how many were attempted."""
        n = 0
        for key in keys:
            await self.backend.delete(key)
            n += 1
        return n


async def _slice(source: AsyncIterator[bytes], start: int, end: int) -> AsyncIterator[bytes]:
    pos = 0
    async for chunk in source:
        lo, hi = max(start - pos, 0), min(end + 1 - pos, len(chunk))
        if lo < hi:
            yield chunk[lo:hi]
        pos += len(chunk)
        if pos > end:
            return


def store_for(app: Any) -> ImageStore:
    """The web process's store: the backend ``file_storage`` mounted on the app."""
    return ImageStore(app.state.file_storage.backend)


_worker_lock = threading.Lock()
_worker_store: tuple[tuple[int, str], ImageStore] | None = None


def _fingerprint(settings: Any) -> str:
    """Everything that decides which backend (and where) - the whole settings
    object, so a backend id, root, bucket, endpoint or credential edit counts."""
    return settings.model_dump_json()


def worker_store() -> ImageStore:
    """The store for a process with no app (Celery).

    ``settings_for`` re-reads ``FileStorageSettings`` at most every 30 s; the
    backend is rebuilt when they change (an admin moved storage) and in a
    forked child, which must not reuse its parent's clients. A namespace change
    is a data-location change: old objects stay where they were.
    """
    global _worker_store
    from background_tasks import settings_for
    from file_storage import backends
    from file_storage.settings import FileStorageSettings

    settings = settings_for(FileStorageSettings, "file_storage")
    key = (os.getpid(), _fingerprint(settings))
    with _worker_lock:
        if _worker_store is None or _worker_store[0] != key:
            _worker_store = (key, ImageStore(backends.build_backend(settings)))
        return _worker_store[1]


def reset_worker_store() -> None:
    """Drop the cached store (tests, and a prefork child at ``worker_process_init``)."""
    global _worker_store
    with _worker_lock:
        _worker_store = None
