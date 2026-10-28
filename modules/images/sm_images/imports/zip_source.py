"""A ZIP's identity at the seal, and a download held to it: :func:`fetch_verified`.

The seal records the object's size and a **fingerprint**: the backend's etag
when ``head`` has one (S3), else one derived from the assembled parts' MD5s -
S3's own multipart-etag recipe, ``md5(part md5s)-<n>`` - prefixed with the part
size, so it can be recomputed from the bytes (the filesystem backend has no
object etag but keeps each part's MD5). A backend with neither falls back to a
SHA-256 of the object, read once at the seal.

Extraction re-checks before it trusts a byte: ``head`` must still show the
sealed size (and etag), the download stops past that size, a derived
fingerprint is recomputed from what arrived, and an etag is checked again
after the download - so an object replaced after the seal (a presigned PUT
still valid, a part re-sent) is refused as ``archive_changed``.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from file_storage.contracts.service import StorageNotFoundError

from sm_images.imports.zip_safety import ZipRejected

__all__ = ["PARTS_PREFIX", "SHA_PREFIX", "fetch_verified", "parts_fingerprint", "sha_fingerprint"]

PARTS_PREFIX: Final = "md5parts:"
SHA_PREFIX: Final = "sha256:"
_MD5: Final = re.compile(r"^[0-9a-f]{32}$")


def _bare(etag: str | None) -> str:
    return (etag or "").strip().strip('"').lower()


def _md5():
    return hashlib.md5(usedforsecurity=False)


def parts_fingerprint(parts: Sequence[Any], part_size: int) -> str | None:
    """From the assembled parts' etags, when each is an MD5; else ``None``."""
    etags = [_bare(p.etag) for p in parts]
    if not etags or not all(_MD5.match(e) for e in etags):
        return None
    digest = _md5()
    for etag in etags:
        digest.update(bytes.fromhex(etag))
    return f"{PARTS_PREFIX}{part_size}:{digest.hexdigest()}-{len(etags)}"


async def sha_fingerprint(store: Any, key: str) -> str:
    digest = hashlib.sha256()
    async for chunk in await store.stream(key):
        digest.update(chunk)
    return f"{SHA_PREFIX}{digest.hexdigest()}"


def is_etag(fingerprint: str) -> bool:
    return not fingerprint.startswith((PARTS_PREFIX, SHA_PREFIX))


class _Digest:
    """Recomputes a derived fingerprint over the downloaded bytes."""

    def __init__(self, fingerprint: str) -> None:
        self.sha = hashlib.sha256() if fingerprint.startswith(SHA_PREFIX) else None
        self.part_size = 0 if self.sha else int(fingerprint[len(PARTS_PREFIX) :].split(":")[0])
        self.current, self.filled, self.parts = _md5(), 0, []

    def update(self, data: bytes) -> None:
        if self.sha is not None:
            self.sha.update(data)
            return
        view = memoryview(data)
        while view:
            take = min(len(view), self.part_size - self.filled)
            self.current.update(view[:take])
            self.filled += take
            view = view[take:]
            if self.filled == self.part_size:
                self.parts.append(self.current.digest())
                self.current, self.filled = _md5(), 0

    def result(self) -> str:
        if self.sha is not None:
            return f"{SHA_PREFIX}{self.sha.hexdigest()}"
        parts = self.parts + ([self.current.digest()] if self.filled else [])
        joined = _md5()
        for part in parts:
            joined.update(part)
        return f"{PARTS_PREFIX}{self.part_size}:{joined.hexdigest()}-{len(parts)}"


async def _head(store: Any, key: str, size: int, fingerprint: str) -> None:
    found = await store.head(key)
    if found is None:
        raise ZipRejected("source_missing")
    if found[0] != size or (is_etag(fingerprint) and _bare(found[1]) != _bare(fingerprint)):
        raise ZipRejected("archive_changed")


async def fetch_verified(store: Any, key: str, *, fingerprint: str, size: int, dest: Path) -> None:
    """Copy the sealed archive to ``dest``, or raise :class:`ZipRejected`
    (``source_missing``, ``archive_changed``). Other storage errors propagate
    (transient: reconcile retries the run)."""
    await _head(store, key, size, fingerprint)
    digest = None if is_etag(fingerprint) else _Digest(fingerprint)
    received = 0
    try:
        with dest.open("wb") as out:
            async for chunk in await store.stream(key):
                received += len(chunk)
                if received > size:
                    raise ZipRejected("archive_changed")
                if digest is not None:
                    digest.update(chunk)
                out.write(chunk)
    except StorageNotFoundError as exc:
        raise ZipRejected("source_missing") from exc
    if received != size or (digest is not None and digest.result() != fingerprint):
        raise ZipRejected("archive_changed")
    if digest is None:
        await _head(store, key, size, fingerprint)  # replaced while it downloaded
